"""Tests for the chat agent orchestrator (Ollama client mocked)."""
from __future__ import annotations

from typing import Any

import pytest

from agentic_bookstore.services import agent as agent_svc


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
    events = await _collect(sid, "buy that fantasy book", client)
    tool_call = next(e for e in events if e["type"] == "tool_call")
    assert tool_call["arguments"]["session_id"] == sid


@pytest.mark.asyncio
async def test_iteration_cap(sid):
    """If the model keeps calling tools forever, orchestrator gives up."""
    infinite_turn = [{
        "message": {
            "content": "",
            "tool_calls": [{
                "function": {
                    "name": "view_cart",
                    "arguments": {"session_id": sid},
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
