"""MCP stdio server exposing the bookstore tools."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .tool_schemas import TOOL_DISPATCH, TOOL_SCHEMAS


def _build_server() -> Server:
    server: Server = Server("agentic-bookstore")

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return [
            Tool(
                name=t["name"],
                description=t["description"],
                inputSchema=t["input_schema"],
            )
            for t in TOOL_SCHEMAS
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        fn = TOOL_DISPATCH.get(name)
        if fn is None:
            payload = {"error": f"unknown tool: {name}"}
        else:
            try:
                payload = fn(**arguments)
            except TypeError as e:
                payload = {"error": f"bad arguments: {e}"}
            except Exception as e:  # noqa: BLE001
                payload = {"error": f"{type(e).__name__}: {e}"}
        return [TextContent(type="text", text=json.dumps(payload, default=str))]

    return server


async def _serve() -> None:
    server = _build_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
