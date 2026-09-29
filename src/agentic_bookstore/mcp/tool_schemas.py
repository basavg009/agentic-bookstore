"""Single source of truth for tool metadata used by MCP + chat agent."""
from __future__ import annotations

from typing import Any, Callable

from ..services import books as books_svc
from ..services import cart as cart_svc
from ..services import checkout as checkout_svc

# JSON-Schema-ish descriptors. Both the MCP SDK and the Ollama chat client
# accept this shape, adapted per-transport in wrappers below.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "search_books",
        "description": (
            "Search the bookstore catalog. Use `query` for free-text search over title, "
            "author, and description (supports partial words). Use `isbn` for exact "
            "ISBN-13 lookup. Filters: `author` (substring), `genre` (one of Fiction, "
            "Sci-Fi, Fantasy, Mystery, Romance, Biography, History, Self-Help, "
            "Children's, Technical, Poetry, Horror, Thriller, Cookbook, Non-fiction), "
            "`medium` (digital|physical), `format` (hardcover|paperback|epub|pdf|audiobook), "
            "`max_price_cents`, `min_price_cents`. Returns `items`, `total`, `limit`, `offset`."
        ),
        "input_schema": {
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
    },
    {
        "name": "get_book",
        "description": "Fetch a single book's full details by ISBN-13.",
        "input_schema": {
            "type": "object",
            "properties": {"isbn": {"type": "string"}},
            "required": ["isbn"],
        },
    },
    {
        "name": "add_to_cart",
        "description": (
            "Add a book to the shopper's cart. `session_id` identifies the cart and "
            "must be reused across cart/checkout calls in the same session."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "isbn": {"type": "string"},
                "quantity": {"type": "integer", "minimum": 1, "default": 1},
            },
            "required": ["session_id", "isbn"],
        },
    },
    {
        "name": "view_cart",
        "description": "Return the current cart contents and subtotal for a session.",
        "input_schema": {
            "type": "object",
            "properties": {"session_id": {"type": "string"}},
            "required": ["session_id"],
        },
    },
    {
        "name": "remove_from_cart",
        "description": "Remove a book from the cart.",
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "isbn": {"type": "string"},
            },
            "required": ["session_id", "isbn"],
        },
    },
    {
        "name": "checkout",
        "description": (
            "Convert the cart into a paid order. Payment is mocked. "
            "`shipping_address` is required if the cart contains any physical items."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "shipping_name": {"type": "string"},
                "shipping_address": {"type": "string"},
                "email": {"type": "string"},
            },
            "required": ["session_id"],
        },
    },
]


def _search_books(**kwargs: Any) -> dict[str, Any]:
    return books_svc.search_books(**kwargs)


def _get_book(*, isbn: str) -> dict[str, Any]:
    result = books_svc.get_book(isbn)
    return result if result is not None else {"error": f"no book with ISBN {isbn}"}


def _add_to_cart(*, session_id: str, isbn: str, quantity: int = 1) -> dict[str, Any]:
    try:
        return cart_svc.add_item(session_id, isbn, quantity)
    except cart_svc.CartError as e:
        return {"error": str(e)}


def _view_cart(*, session_id: str) -> dict[str, Any]:
    return cart_svc.view_cart(session_id)


def _remove_from_cart(*, session_id: str, isbn: str) -> dict[str, Any]:
    try:
        return cart_svc.remove_item(session_id, isbn)
    except cart_svc.CartError as e:
        return {"error": str(e)}


def _checkout(
    *,
    session_id: str,
    shipping_name: str = "",
    shipping_address: str = "",
    email: str = "",
) -> dict[str, Any]:
    try:
        return checkout_svc.checkout(
            session_id,
            shipping_name=shipping_name,
            shipping_address=shipping_address,
            email=email,
        )
    except checkout_svc.CheckoutError as e:
        return {"error": str(e)}


TOOL_DISPATCH: dict[str, Callable[..., dict[str, Any]]] = {
    "search_books": _search_books,
    "get_book": _get_book,
    "add_to_cart": _add_to_cart,
    "view_cart": _view_cart,
    "remove_from_cart": _remove_from_cart,
    "checkout": _checkout,
}


def to_ollama_tools() -> list[dict[str, Any]]:
    """Adapt schemas into Ollama's OpenAI-compatible `tools` array."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in TOOL_SCHEMAS
    ]
