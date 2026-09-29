"""Local-LLM agent orchestrator (Ollama + Qwen).

Streams a chat completion, executes tool calls against the shared service
layer, and yields typed events for the SSE route to relay to the browser.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from ollama import AsyncClient

from ..config import settings
from ..mcp.tool_schemas import TOOL_DISPATCH, to_ollama_tools

MAX_ITERATIONS = 10

SYSTEM_PROMPT = """You are the shopkeeper AI for an online bookstore.

You help the customer find, choose, and purchase books via the provided tools.
Guidelines:
- Always pass the customer's session_id (given below) to cart/checkout tools.
- Prefer `search_books` with clear filters (genre, medium, max_price_cents in cents — $10 = 1000).
- Confirm the customer's intent before calling `checkout`. When they confirm, call `checkout` with any address/email they provided.
- Keep replies short and conversational. Present at most a few options at a time.
- If a tool returns `{"error": ...}`, explain plainly and suggest an alternative."""


class AgentUnavailable(RuntimeError):
    """Raised when Ollama is not reachable."""


async def check_health() -> dict[str, Any]:
    """Return `{available, model, host, error?}`."""
    try:
        client = AsyncClient(host=settings.ollama_host)
        tags = await client.list()
        models = [m.get("model") or m.get("name") for m in tags.get("models", [])]
        return {
            "available": True,
            "host": settings.ollama_host,
            "model": settings.ollama_model,
            "model_pulled": any(
                m and m.split(":")[0] == settings.ollama_model.split(":")[0]
                for m in models
            ),
            "installed_models": [m for m in models if m],
        }
    except Exception as e:  # noqa: BLE001
        return {
            "available": False,
            "host": settings.ollama_host,
            "model": settings.ollama_model,
            "error": f"{type(e).__name__}: {e}",
        }


def _extract_tool_calls(msg: dict[str, Any]) -> list[dict[str, Any]]:
    raw = msg.get("tool_calls") or []
    calls: list[dict[str, Any]] = []
    for tc in raw:
        fn = tc.get("function", {})
        name = fn.get("name")
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        if name:
            calls.append({"name": name, "arguments": args or {}})
    return calls


def _summarize_result(name: str, result: dict[str, Any]) -> str:
    if "error" in result:
        return f"error: {result['error']}"
    if name == "search_books":
        total = result.get("total", 0)
        items = result.get("items", [])
        titles = ", ".join(f"{i['title']} (${i['price']:.2f})" for i in items[:3])
        return f"{total} hits — top: {titles}" if titles else f"{total} hits"
    if name in {"add_to_cart", "view_cart", "remove_from_cart"}:
        return f"cart: {result.get('count', 0)} items, ${result.get('subtotal', 0):.2f}"
    if name == "checkout":
        return f"order {result.get('order_id', '?')[:8]}… total ${result.get('total', 0):.2f}"
    if name == "get_book":
        return f"{result.get('title', '?')} — ${result.get('price', 0):.2f}"
    return "ok"


async def stream_chat(
    *,
    session_id: str,
    user_message: str,
    history: list[dict[str, Any]] | None = None,
    client: AsyncClient | None = None,
    model: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yield events: `{type: 'token'|'tool_call'|'tool_result'|'done'|'error', ...}`.

    `client` and `model` are injectable so tests can pass a stub.
    """
    if client is None:
        client = AsyncClient(host=settings.ollama_host)
    model = model or settings.ollama_model

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": f"{SYSTEM_PROMPT}\n\nsession_id: {session_id}"},
    ]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    tools = to_ollama_tools()

    for _ in range(MAX_ITERATIONS):
        collected_text = ""
        pending_tool_calls: list[dict[str, Any]] = []

        try:
            stream = await client.chat(
                model=model, messages=messages, tools=tools, stream=True
            )
        except Exception as e:  # noqa: BLE001
            yield {"type": "error", "message": f"{type(e).__name__}: {e}"}
            return

        async for chunk in stream:
            msg = chunk.get("message", {}) or {}
            piece = msg.get("content") or ""
            if piece:
                collected_text += piece
                yield {"type": "token", "text": piece}
            # Ollama surfaces tool_calls once assembled; forward them at chunk time.
            tcs = _extract_tool_calls(msg)
            if tcs:
                pending_tool_calls.extend(tcs)
            if chunk.get("done"):
                break

        if not pending_tool_calls:
            yield {"type": "done"}
            return

        messages.append({
            "role": "assistant",
            "content": collected_text,
            "tool_calls": [
                {"function": {"name": c["name"], "arguments": c["arguments"]}}
                for c in pending_tool_calls
            ],
        })

        for call in pending_tool_calls:
            name = call["name"]
            args = dict(call["arguments"])
            # Force the session_id we were given; agents sometimes hallucinate one.
            if name in {"add_to_cart", "view_cart", "remove_from_cart", "checkout"}:
                args["session_id"] = session_id
            yield {"type": "tool_call", "name": name, "arguments": args}
            fn = TOOL_DISPATCH.get(name)
            if fn is None:
                result: dict[str, Any] = {"error": f"unknown tool: {name}"}
            else:
                try:
                    result = fn(**args)
                except TypeError as e:
                    result = {"error": f"bad arguments: {e}"}
                except Exception as e:  # noqa: BLE001
                    result = {"error": f"{type(e).__name__}: {e}"}
            yield {
                "type": "tool_result",
                "name": name,
                "summary": _summarize_result(name, result),
                "result": result,
            }
            messages.append({
                "role": "tool",
                "name": name,
                "content": json.dumps(result, default=str),
            })

    yield {"type": "error", "message": f"agent exceeded {MAX_ITERATIONS} tool-call iterations"}
