"""Chat endpoints — SSE streaming from the local LLM."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ..services import agent as agent_svc
from .session import get_session_id

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _sid(request: Request) -> str:
    return get_session_id(request)


class ChatBody(BaseModel):
    message: str


@router.get("/health")
async def health() -> dict:
    return await agent_svc.check_health()


@router.post("/stream")
async def stream(body: ChatBody, session_id: str = Depends(_sid)) -> EventSourceResponse:
    async def _gen():
        async for event in agent_svc.stream_chat(
            session_id=session_id, user_message=body.message
        ):
            yield {"event": event["type"], "data": json.dumps(event, default=str)}

    return EventSourceResponse(_gen())
