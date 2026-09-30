"""Chat endpoints — SSE streaming from the local LLM, with server-side memory."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from ..services import agent as agent_svc
from ..services import conversation as conversation_svc
from .session import get_session_id

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _sid(request: Request) -> str:
    return get_session_id(request)


class ChatBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


@router.get("/health")
async def health() -> dict:
    return await agent_svc.check_health()


@router.get("/history")
async def history(session_id: str = Depends(_sid)) -> dict:
    messages = await asyncio.to_thread(conversation_svc.visible_transcript, session_id)
    return {"messages": messages}


@router.delete("/history")
async def clear(session_id: str = Depends(_sid)) -> dict:
    await asyncio.to_thread(conversation_svc.clear_history, session_id)
    return {"cleared": True}


@router.post("/stream")
async def stream(body: ChatBody, session_id: str = Depends(_sid)) -> EventSourceResponse:
    prior = await asyncio.to_thread(conversation_svc.load_history, session_id)

    async def _gen():
        transcript: list[dict[str, Any]] = []
        try:
            async for event in agent_svc.stream_chat(
                session_id=session_id,
                user_message=body.message,
                history=prior,
                transcript=transcript,
            ):
                yield {"event": event["type"], "data": json.dumps(event, default=str)}
        finally:
            # Persist whatever completed, even if the client disconnected mid-turn.
            await asyncio.to_thread(conversation_svc.append_messages, session_id, transcript)

    return EventSourceResponse(_gen())
