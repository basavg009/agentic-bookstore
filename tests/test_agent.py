"""Tests for the chat agent orchestrator (Ollama client mocked)."""
from __future__ import annotations

from typing import Any

import pytest

from agentic_bookstore.config import settings
from agentic_bookstore.services import agent as agent_svc
from agentic_bookstore.services import cart as cart_svc
from agentic_bookstore.services import conversation as conversation_svc


class FakeStream:
    def __init__(self, chunks: list[dict[str, Any]]):
        self._chunks = chunks

    def __aiter__(self):
        self._it = iter(self._chunks)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class FakeClient:
    """Ollama-compatible stub: `chat` returns pre-scripted streams per call."""

    def __init__(self, script: list[list[dict[str, Any]]]):
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        if not self._script:
            raise AssertionError("FakeClient ran out of scripted turns")
        return FakeStream(self._script.pop(0))


async def _collect(session_id: str, message: str, client: FakeClient) -> list[dict[str, Any]]:
    events = []
    async for e in agent_svc.stream_chat(
        session_id=session_id, user_message=message, client=client, model="qwen2.5:7b"
    ):
        events.append(e)
    return events


@pytest.mark.asyncio
async def test_streams_plain_reply_without_tools(sid):
    client = FakeClient([[
        {"message": {"content": "Hi "}, "done": False},
        {"message": {"content": "there!"}, "done": True},
    ]])
    events = await _collect(sid, "hello", client)
    types = [e["type"] for e in events]
    assert types == ["token", "token", "done"]
    assert "".join(e["text"] for e in events if e["type"] == "token") == "Hi there!"


@pytest.mark.asyncio
async def test_search_tool_call_sequence(sid):
    script = [
        [
            {
                "message": {
                    "content": "",
                    "tool_calls": [{
                        "function": {
                            "name": "search_books",
                            "arguments": {"query": "dragons", "limit": 3},
                        }
                    }],
                },
                "done": True,
            }
        ],
        [
            {"message": {"content": "Here's one: Dragons of Vareth."}, "done": True},
        ],
    ]
    client = FakeClient(script)
    events = await _collect(sid, "find dragon books", client)
    types = [e["type"] for e in events]
    assert "tool_call" in types
    assert "tool_result" in types
    assert types[-1] == "done"
    tool_call = next(e for e in events if e["type"] == "tool_call")
    assert tool_call["name"] == "search_books"
    tool_result = next(e for e in events if e["type"] == "tool_result")
    assert tool_result["result"]["total"] >= 1


@pytest.mark.asyncio
async def test_agent_forces_correct_session_id(sid):
    """Agent may hallucinate session_id; orchestrator must overwrite it."""
    script = [
        [
            {
                "message": {
                    "content": "",
                    "tool_calls": [{
                        "function": {
                            "name": "add_to_cart",
                            "arguments": {
                                "session_id": "hallucinated-id",
                                "isbn": "9781000000017",
                                "quantity": 1,
                            },
                        }
                    }],
                },
                "done": True,
            }
        ],
        [
            {"message": {"content": "Added!"}, "done": True},
        ],
    ]
    client = FakeClient(script)
    await _collect(sid, "buy that fantasy book", client)
    assert cart_svc.view_cart(sid)["count"] == 1
    assert cart_svc.view_cart("hallucinated-id")["count"] == 0


@pytest.mark.asyncio
async def test_iteration_cap(sid):
    """If the model keeps calling tools forever, orchestrator gives up."""
    infinite_turn = [{
        "message": {
            "content": "",
            "tool_calls": [{
                "function": {
                    "name": "view_cart",
                    "arguments": {},
                }
            }],
        },
        "done": True,
    }]
    client = FakeClient([infinite_turn] * (agent_svc.MAX_ITERATIONS + 2))
    events = await _collect(sid, "loop forever", client)
    assert events[-1]["type"] == "error"
    assert "iterations" in events[-1]["message"]


@pytest.mark.asyncio
async def test_ollama_client_failure_yields_error(sid):
    class BrokenClient:
        async def chat(self, **_):
            raise ConnectionError("ollama down")

    events = await _collect(sid, "hi", BrokenClient())
    assert events == [{"type": "error", "message": "ConnectionError: ollama down"}]


def _tool_turn(name: str, arguments: dict[str, Any], **done_fields: Any) -> list[dict[str, Any]]:
    return [{
        "message": {"content": "", "tool_calls": [{"function": {"name": name, "arguments": arguments}}]},
        "done": True,
        **done_fields,
    }]


def _text_turn(text: str) -> list[dict[str, Any]]:
    return [{"message": {"content": text}, "done": True}]


@pytest.mark.asyncio
async def test_history_is_sent_and_transcript_recorded(sid):
    history = [
        {"role": "user", "content": "find me a dragon book"},
        {"role": "assistant", "content": "Dragons of Vareth is $7.99. Want it?"},
    ]
    client = FakeClient([_tool_turn("add_to_cart", {"isbn": "9781000000017"}), _text_turn("Added!")])
    transcript: list[dict[str, Any]] = []
    async for _ in agent_svc.stream_chat(
        session_id=sid, user_message="yes", history=history,
        transcript=transcript, client=client, model="m",
    ):
        pass
    sent = client.calls[0]["messages"]
    assert sent[1:3] == history and sent[3] == {"role": "user", "content": "yes"}
    assert [m["role"] for m in transcript] == ["user", "assistant", "tool", "assistant"]
    assert transcript[-1]["content"] == "Added!"


@pytest.mark.asyncio
async def test_conversation_round_trips_through_storage(sid):
    client = FakeClient([_tool_turn("view_cart", {}), _text_turn("Your cart is empty.")])
    transcript: list[dict[str, Any]] = []
    async for _ in agent_svc.stream_chat(
        session_id=sid, user_message="what's in my cart?",
        transcript=transcript, client=client, model="m",
    ):
        pass
    conversation_svc.append_messages(sid, transcript)
    history = conversation_svc.load_history(sid)
    assert [m["role"] for m in history] == ["user", "assistant", "tool", "assistant"]
    assert history[1]["tool_calls"][0]["function"]["name"] == "view_cart"
    assert history[2]["tool_name"] == "view_cart"
    assert conversation_svc.visible_transcript(sid) == [
        {"role": "user", "content": "what's in my cart?"},
        {"role": "assistant", "content": "Your cart is empty."},
    ]
    conversation_svc.clear_history(sid)
    assert conversation_svc.load_history(sid) == []


def test_history_window_starts_at_a_user_message(sid):
    conversation_svc.append_messages(sid, [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "view_cart", "arguments": {}}}]},
        {"role": "tool", "tool_name": "view_cart", "content": "{}"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
    ])
    # A 4-message window would begin at the orphaned tool result; it must be trimmed.
    history = conversation_svc.load_history(sid, limit=4)
    assert [m["content"] for m in history] == ["q2", "a2"]


@pytest.mark.asyncio
async def test_agent_cannot_confirm_checkout(sid):
    cart_svc.add_item(sid, "9781000000017", 1)
    client = FakeClient([
        _tool_turn("confirm_checkout", {"confirmation_token": "guess"}),
        _text_turn("I can't do that."),
    ])
    events = await _collect(sid, "just buy it", client)
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["result"] == {"error": "unknown tool: confirm_checkout"}
    offered = {t["function"]["name"] for t in client.calls[0]["tools"]}
    assert "confirm_checkout" not in offered
    assert cart_svc.view_cart(sid)["count"] == 1


@pytest.mark.asyncio
async def test_prepare_checkout_token_goes_to_browser_not_model(sid):
    cart_svc.add_item(sid, "9781000000017", 1)
    client = FakeClient([_tool_turn("prepare_checkout", {}), _text_turn("Total is $7.99 — please confirm.")])
    events = await _collect(sid, "check out", client)
    result = next(e for e in events if e["type"] == "tool_result")
    token = result["result"]["confirmation_token"]
    assert token
    tool_msg = next(m for m in client.calls[1]["messages"] if m["role"] == "tool")
    assert tool_msg["tool_name"] == "prepare_checkout"
    assert token not in tool_msg["content"]
    assert "799" in tool_msg["content"]


@pytest.mark.asyncio
async def test_token_budget(sid, monkeypatch):
    monkeypatch.setattr(settings, "agent_max_tokens", 100)
    client = FakeClient([_tool_turn("view_cart", {}, prompt_eval_count=90, eval_count=20)] * 3)
    events = await _collect(sid, "hi", client)
    assert events[-1] == {"type": "error", "message": "agent exceeded its token budget"}
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_tool_call_budget(sid, monkeypatch):
    monkeypatch.setattr(settings, "agent_max_tool_calls", 2)
    many = [{
        "message": {"content": "", "tool_calls": [{"function": {"name": "view_cart", "arguments": {}}}] * 3},
        "done": True,
    }]
    events = await _collect(sid, "hi", FakeClient([many]))
    assert events[-1] == {"type": "error", "message": "agent exceeded its tool-call budget"}
    assert not any(e["type"] == "tool_call" for e in events)


@pytest.mark.asyncio
async def test_time_budget(sid, monkeypatch):
    monkeypatch.setattr(settings, "agent_max_seconds", -1)
    events = await _collect(sid, "hi", FakeClient([]))
    assert events == [{"type": "error", "message": "agent exceeded its time budget"}]


@pytest.mark.asyncio
async def test_failure_while_streaming_yields_error(sid):
    """Streaming clients send the request lazily, so errors arrive mid-iteration."""

    class DroppingStream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise ConnectionError("server disconnected")

    class LazyClient:
        async def chat(self, **_):
            return DroppingStream()

    events = await _collect(sid, "hi", LazyClient())
    assert events == [{"type": "error", "message": "ConnectionError: server disconnected"}]
