"""Server-side chat memory, keyed by the (signed) session cookie."""
from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy import delete, select

from ..config import settings
from ..db import session_scope
from ..models import ChatMessage


def load_history(session_id: str, limit: int | None = None) -> list[dict[str, Any]]:
    """Return the most recent messages in Ollama chat format, oldest first.

    The window always starts at a user message so the model never sees a tool
    result or tool call cut off from the request that caused it.
    """
    limit = limit or settings.chat_history_max_messages
    with session_scope() as s:
        rows = s.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id.desc())
            .limit(limit)
        ).scalars().all()
    rows = list(reversed(rows))
    while rows and rows[0].role != "user":
        rows.pop(0)
    messages: list[dict[str, Any]] = []
    for r in rows:
        msg: dict[str, Any] = {"role": r.role, "content": r.content}
        if r.name:
            msg["tool_name"] = r.name
        if r.tool_calls_json:
            msg["tool_calls"] = json.loads(r.tool_calls_json)
        messages.append(msg)
    return messages


def append_messages(session_id: str, messages: list[dict[str, Any]]) -> None:
    if not messages:
        return
    now = int(time.time())
    with session_scope() as s:
        for m in messages:
            tool_calls = m.get("tool_calls")
            s.add(ChatMessage(
                session_id=session_id,
                role=m["role"],
                content=m.get("content") or "",
                name=m.get("tool_name"),
                tool_calls_json=json.dumps(tool_calls, default=str) if tool_calls else None,
                created_at=now,
            ))


def visible_transcript(session_id: str) -> list[dict[str, str]]:
    """User and assistant text only — what the chat panel re-renders on reload."""
    return [
        {"role": m["role"], "content": m["content"]}
        for m in load_history(session_id)
        if m["role"] in {"user", "assistant"} and m["content"]
    ]


def clear_history(session_id: str) -> None:
    with session_scope() as s:
        s.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))
