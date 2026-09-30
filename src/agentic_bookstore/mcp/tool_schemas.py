"""Single source of truth for tool metadata and execution, used by MCP + chat agent.

Trust rules enforced here, so every transport gets them:
- Identity comes from the transport, never from the model. `session_id` is not part
  of any schema; `call_tool` injects it and discards any value the model supplies.
- Model-supplied arguments are clamped (quantity) before reaching services.
- Results are shaped for an LLM: free text from the catalog (descriptions) is
  dropped or truncated, shrinking the prompt-injection surface.
- Placing an order is not in the agent's tool set at all (`agent_allowed=False`).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..services import books as books_svc
from ..services import cart as cart_svc
from ..services import checkout as checkout_svc

MAX_TOOL_QUANTITY = 10
MAX_DESCRIPTION_CHARS = 400


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., dict[str, Any]]
    needs_session: bool = False
    agent_allowed: bool = True
    # MCP ToolAnnotations hints (readOnlyHint, destructiveHint, idempotentHint, ...).
    annotations: dict[str, Any] = field(default_factory=dict)


def _strip_description(book: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in book.items() if k != "description"}


def _truncate_description(book: dict[str, Any]) -> dict[str, Any]:
    desc = book.get("description") or ""
    if len(desc) > MAX_DESCRIPTION_CHARS:
        desc = desc[:MAX_DESCRIPTION_CHARS] + "…"
    return {**book, "description": desc}


def _search_books(**kwargs: Any) -> dict[str, Any]:
    kwargs.setdefault("limit", 10)
    result = books_svc.search_books(**kwargs)
    return {**result, "items": [_strip_description(b) for b in result["items"]]}


def _get_book(*, isbn: str) -> dict[str, Any]:
    result = books_svc.get_book(isbn)
    if result is None:
        return {"error": f"no book with ISBN {isbn}"}
    return _truncate_description(result)


def _add_to_cart(*, session_id: str, isbn: str, quantity: int = 1) -> dict[str, Any]:
    if not 1 <= quantity <= MAX_TOOL_QUANTITY:
        return {"error": f"quantity must be between 1 and {MAX_TOOL_QUANTITY}"}
    return cart_svc.add_item(session_id, isbn, quantity)


def _view_cart(*, session_id: str) -> dict[str, Any]:
    return cart_svc.view_cart(session_id)


def _remove_from_cart(*, session_id: str, isbn: str) -> dict[str, Any]:
    return cart_svc.remove_item(session_id, isbn)


def _prepare_checkout(
    *, session_id: str, shipping_name: str = "", shipping_address: str = "", email: str = ""
) -> dict[str, Any]:
    return checkout_svc.prepare_checkout(
        session_id, shipping_name=shipping_name, shipping_address=shipping_address, email=email
    )


def _confirm_checkout(*, session_id: str, confirmation_token: str) -> dict[str, Any]:
    return checkout_svc.confirm_checkout(session_id, confirmation_token)


TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="search_books",
        description=(
            "Search the bookstore catalog. Use `query` for free-text search over title, "
            "author, and description (supports partial words; results ranked by relevance). "
            "Use `isbn` for exact ISBN-13 lookup. Filters: `author` (substring), `genre` "
            "(one of Fiction, Sci-Fi, Fantasy, Mystery, Romance, Biography, History, "
            "Self-Help, Children's, Technical, Poetry, Horror, Thriller, Cookbook, "
            "Non-fiction), `medium` (digital|physical), `format` "
            "(hardcover|paperback|epub|pdf|audiobook), `max_price_cents`, `min_price_cents`. "
            "Returns `items` (without descriptions — use get_book), `total`, `limit`, `offset`."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Free-text search terms."},
                "isbn": {"type": "string", "description": "Exact ISBN-13."},
                "author": {"type": "string"},
                "genre": {"type": "string"},
                "medium": {"type": "string", "enum": ["digital", "physical"]},
                "format": {
                    "type": "string",
                    "enum": ["hardcover", "paperback", "epub", "pdf", "audiobook"],
                },
                "max_price_cents": {"type": "integer", "minimum": 0},
                "min_price_cents": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
            },
        },
        handler=_search_books,
        annotations={"readOnlyHint": True},
    ),
    ToolSpec(
        name="get_book",
        description="Fetch a single book's details by ISBN-13 (description truncated).",
        input_schema={
            "type": "object",
            "properties": {"isbn": {"type": "string"}},
            "required": ["isbn"],
        },
        handler=_get_book,
        annotations={"readOnlyHint": True},
    ),
    ToolSpec(
        name="add_to_cart",
        description=f"Add a book to the shopper's cart (1–{MAX_TOOL_QUANTITY} copies per call).",
        input_schema={
            "type": "object",
            "properties": {
                "isbn": {"type": "string"},
                "quantity": {
                    "type": "integer", "minimum": 1, "maximum": MAX_TOOL_QUANTITY, "default": 1,
                },
            },
            "required": ["isbn"],
        },
        handler=_add_to_cart,
        needs_session=True,
        annotations={"readOnlyHint": False, "destructiveHint": False},
    ),
    ToolSpec(
        name="view_cart",
        description="Return the current cart contents and subtotal.",
        input_schema={"type": "object", "properties": {}},
        handler=_view_cart,
        needs_session=True,
        annotations={"readOnlyHint": True},
    ),
    ToolSpec(
        name="remove_from_cart",
        description="Remove a book from the cart.",
        input_schema={
            "type": "object",
            "properties": {"isbn": {"type": "string"}},
            "required": ["isbn"],
        },
        handler=_remove_from_cart,
        needs_session=True,
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    ),
    ToolSpec(
        name="prepare_checkout",
        description=(
            "Price the cart and lock prices into a quote for the customer to review. "
            "Does NOT place an order or charge anything. `shipping_address` is required "
            "if the cart contains physical items. The customer must then confirm the quote "
            "themselves before any order is placed."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "shipping_name": {"type": "string"},
                "shipping_address": {"type": "string"},
                "email": {"type": "string"},
            },
        },
        handler=_prepare_checkout,
        needs_session=True,
        annotations={"readOnlyHint": False, "destructiveHint": False},
    ),
    ToolSpec(
        name="confirm_checkout",
        description=(
            "Place the order for a quote from prepare_checkout and charge the customer. "
            "Only call after the customer has explicitly approved the quoted total. "
            "Idempotent: repeating with the same token returns the same order."
        ),
        input_schema={
            "type": "object",
            "properties": {"confirmation_token": {"type": "string"}},
            "required": ["confirmation_token"],
        },
        handler=_confirm_checkout,
        needs_session=True,
        # The in-app agent never gets this tool: a human confirms in the web UI.
        agent_allowed=False,
        annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True},
    ),
]

TOOLS_BY_NAME: dict[str, ToolSpec] = {t.name: t for t in TOOLS}

# JSON-Schema descriptors (kept for transports and tests that want plain dicts).
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {"name": t.name, "description": t.description, "input_schema": t.input_schema}
    for t in TOOLS
]

SESSION_TOOLS = frozenset(t.name for t in TOOLS if t.needs_session)
AGENT_TOOL_NAMES = frozenset(t.name for t in TOOLS if t.agent_allowed)


def call_tool(
    name: str,
    arguments: dict[str, Any] | None,
    *,
    session_id: str,
    allowed: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Run a tool as `session_id`. Errors come back as `{"error": ...}`, never raised."""
    spec = TOOLS_BY_NAME.get(name)
    if spec is None or (allowed is not None and name not in allowed):
        return {"error": f"unknown tool: {name}"}
    args = dict(arguments or {})
    args.pop("session_id", None)  # never trust a model-supplied identity
    if spec.needs_session:
        args["session_id"] = session_id
    try:
        return spec.handler(**args)
    except (cart_svc.CartError, checkout_svc.CheckoutError) as e:
        return {"error": str(e)}
    except TypeError as e:
        return {"error": f"bad arguments: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def to_ollama_tools(names: frozenset[str] = AGENT_TOOL_NAMES) -> list[dict[str, Any]]:
    """Adapt schemas into Ollama's OpenAI-compatible `tools` array."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in TOOLS
        if t.name in names
    ]
