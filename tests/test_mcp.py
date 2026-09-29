import json

from agentic_bookstore.mcp.tool_schemas import TOOL_DISPATCH, TOOL_SCHEMAS, to_ollama_tools


def test_all_six_tools_registered():
    names = {t["name"] for t in TOOL_SCHEMAS}
    assert names == {
        "search_books", "get_book", "add_to_cart",
        "view_cart", "remove_from_cart", "checkout",
    }
    assert set(TOOL_DISPATCH) == names


def test_ollama_tool_shape():
    tools = to_ollama_tools()
    assert all(t["type"] == "function" for t in tools)
    assert all("name" in t["function"] and "parameters" in t["function"] for t in tools)


def test_search_books_dispatch():
    result = TOOL_DISPATCH["search_books"](query="dragons", limit=5)
    assert result["total"] >= 1
    assert result["items"][0]["title"] == "Dragons of Vareth"


def test_add_and_view_cart_dispatch(sid):
    add = TOOL_DISPATCH["add_to_cart"](session_id=sid, isbn="9781000000017", quantity=2)
    assert add["count"] == 2
    view = TOOL_DISPATCH["view_cart"](session_id=sid)
    assert view["count"] == 2


def test_checkout_dispatch(sid):
    TOOL_DISPATCH["add_to_cart"](session_id=sid, isbn="9781000000017", quantity=1)
    order = TOOL_DISPATCH["checkout"](session_id=sid)
    assert order["payment_status"] == "paid"


def test_error_returned_as_dict(sid):
    result = TOOL_DISPATCH["add_to_cart"](
        session_id=sid, isbn="0000000000000", quantity=1
    )
    assert "error" in result


def test_get_book_missing():
    result = TOOL_DISPATCH["get_book"](isbn="0000000000000")
    assert "error" in result


def test_schemas_json_serializable():
    # Guardrail: MCP transport requires JSON.
    json.dumps(TOOL_SCHEMAS)
