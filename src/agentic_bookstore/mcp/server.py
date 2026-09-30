"""MCP stdio server exposing the bookstore tools.

Identity: a stdio server is launched by, and speaks only to, one MCP host, so the
process is the principal. It acts on exactly one cart — `MCP_SESSION_ID` if set,
otherwise a fresh random one — and tools never accept a session id from the model.
A remote (HTTP) deployment would instead derive the session from an OAuth token.

Ordering: `confirm_checkout` is annotated destructive so hosts ask the user before
running it. When the client supports elicitation, the server also asks the user
directly and refuses to place the order without an explicit "yes".
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from ..config import settings
from ..services import checkout as checkout_svc
from .tool_schemas import TOOLS, call_tool


def _confirmation_prompt(quote: dict[str, Any]) -> str:
    lines = "\n".join(
        f"  • {i['quantity']} × {i['title']} — ${i['line_total_cents'] / 100:.2f}"
        for i in quote["items"]
    )
    ship = f"\nShip to: {quote['shipping_address']}" if quote["requires_shipping"] else ""
    return f"Place this order for ${quote['total']:.2f}?\n{lines}{ship}"


async def _human_approves(server: Server, session_id: str, token: str) -> dict[str, Any] | None:
    """Ask the user via elicitation. Returns an error payload unless they accept."""
    session = server.request_context.session
    wants = types.ClientCapabilities(elicitation=types.ElicitationCapability())
    if not session.check_client_capability(wants):
        return None  # fall back to the host's own approval of destructive tools
    quote = await asyncio.to_thread(checkout_svc.get_quote, session_id, token)
    if quote is None:
        return {"error": "invalid confirmation token"}
    answer = await session.elicit(
        message=_confirmation_prompt(quote),
        requestedSchema={
            "type": "object",
            "properties": {"confirm": {"type": "boolean", "title": "Place order"}},
            "required": ["confirm"],
        },
    )
    if answer.action != "accept" or not (answer.content or {}).get("confirm"):
        return {"error": "the customer did not confirm the order; nothing was charged"}
    return None


def build_server(session_id: str | None = None) -> Server:
    session_id = session_id or settings.mcp_session_id or f"mcp-{uuid.uuid4()}"
    server: Server = Server("agentic-bookstore")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=t.name,
                description=t.description,
                inputSchema=t.input_schema,
                annotations=types.ToolAnnotations(**t.annotations),
            )
            for t in TOOLS
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
        payload: dict[str, Any] | None = None
        if name == "confirm_checkout":
            payload = await _human_approves(
                server, session_id, str((arguments or {}).get("confirmation_token", ""))
            )
        if payload is None:
            # Services are synchronous; keep them off the event loop.
            payload = await asyncio.to_thread(
                call_tool, name, arguments, session_id=session_id
            )
        return [types.TextContent(type="text", text=json.dumps(payload, default=str))]

    return server


async def _serve() -> None:
    server = build_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
