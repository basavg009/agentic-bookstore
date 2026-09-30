import json

import pytest
from mcp import types
from mcp.shared.memory import create_connected_server_and_client_session

from agentic_bookstore.mcp.server import build_server
from agentic_bookstore.mcp.tool_schemas import (
    AGENT_TOOL_NAMES,
    MAX_TOOL_QUANTITY,
    TOOL_SCHEMAS,
    call_tool,
    to_ollama_tools,
)
from agentic_bookstore.services import cart as cart_svc

ALL_TOOLS = {
    "search_books", "get_book", "add_to_cart", "view_cart",
    "remove_from_cart", "prepare_checkout", "confirm_checkout",
}


def test_all_tools_registered():
    assert {t["name"] for t in TOOL_SCHEMAS} == ALL_TOOLS


def test_no_schema_accepts_session_id():
    for t in TOOL_SCHEMAS:
        assert "session_id" not in t["input_schema"].get("properties", {}), t["name"]


def test_agent_cannot_place_orders():
    assert "confirm_checkout" not in AGENT_TOOL_NAMES
    names = {t["function"]["name"] for t in to_ollama_tools()}
    assert names == ALL_TOOLS - {"confirm_checkout"}
    assert all("parameters" in t["function"] for t in to_ollama_tools())


def test_disallowed_tool_is_refused(sid):
    result = call_tool("confirm_checkout", {"confirmation_token": "x"},
                       session_id=sid, allowed=AGENT_TOOL_NAMES)
    assert result == {"error": "unknown tool: confirm_checkout"}


def test_model_supplied_session_id_is_ignored(sid):
    victim = f"victim-{sid}"
    cart_svc.add_item(victim, "9781000000017", 1)
    view = call_tool("view_cart", {"session_id": victim}, session_id=sid)
    assert view["session_id"] == sid
    assert view["count"] == 0


def test_quantity_is_clamped(sid):
    result = call_tool("add_to_cart", {"isbn": "9781000000017",
                                       "quantity": MAX_TOOL_QUANTITY + 1}, session_id=sid)
    assert "error" in result
    assert cart_svc.view_cart(sid)["count"] == 0


def test_search_results_omit_descriptions(sid):
    result = call_tool("search_books", {"query": "dragons"}, session_id=sid)
    assert result["total"] >= 1
    assert result["items"][0]["title"] == "Dragons of Vareth"
    assert all("description" not in i for i in result["items"])


def test_errors_returned_as_dict(sid):
    assert "error" in call_tool("add_to_cart", {"isbn": "0000000000000"}, session_id=sid)
    assert "error" in call_tool("get_book", {"isbn": "0000000000000"}, session_id=sid)
    assert "error" in call_tool("nope", {}, session_id=sid)


def test_schemas_json_serializable():
    json.dumps(TOOL_SCHEMAS)


# --- the real MCP server over an in-memory transport ------------------------------

def _payload(result: types.CallToolResult) -> dict:
    return json.loads(result.content[0].text)


async def _buy(sid: str, elicitation_callback=None) -> tuple[dict, dict]:
    server = build_server(session_id=sid)
    kwargs = {"elicitation_callback": elicitation_callback} if elicitation_callback else {}
    async with create_connected_server_and_client_session(server, **kwargs) as client:
        listed = await client.list_tools()
        confirm_tool = next(t for t in listed.tools if t.name == "confirm_checkout")
        assert confirm_tool.annotations.destructiveHint is True
        await client.call_tool("add_to_cart", {"isbn": "9781000000017"})
        quote = _payload(await client.call_tool("prepare_checkout", {}))
        order = _payload(await client.call_tool(
            "confirm_checkout", {"confirmation_token": quote["confirmation_token"]}
        ))
        return quote, order


@pytest.mark.anyio
async def test_mcp_server_end_to_end_with_user_approval(sid):
    prompts = []

    async def approve(_ctx, params):
        prompts.append(params.message)
        return types.ElicitResult(action="accept", content={"confirm": True})

    quote, order = await _buy(sid, approve)
    assert order["payment_status"] == "paid"
    assert order["total_cents"] == quote["total_cents"] == 799
    assert "$7.99" in prompts[0]


@pytest.mark.anyio
async def test_mcp_server_refuses_order_when_user_declines(sid):
    async def decline(_ctx, _params):
        return types.ElicitResult(action="decline")

    _, order = await _buy(sid, decline)
    assert "did not confirm" in order["error"]
    assert cart_svc.view_cart(sid)["count"] == 1  # nothing charged, cart intact


@pytest.mark.anyio
async def test_mcp_server_without_elicitation_relies_on_host_approval(sid):
    # Hosts without elicitation gate destructive tools with their own approval prompt.
    _, order = await _buy(sid)
    assert order["payment_status"] == "paid"
