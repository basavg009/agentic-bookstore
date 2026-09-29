"""Session-cookie middleware — issues an opaque UUID on first visit."""
from __future__ import annotations

import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

SESSION_COOKIE = "bookstore_sid"


def get_session_id(request: Request) -> str:
    """Return the session id set by the middleware."""
    sid = getattr(request.state, "session_id", None)
    if sid is None:
        sid = request.cookies.get(SESSION_COOKIE) or str(uuid.uuid4())
        request.state.session_id = sid
    return sid


class SessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        existing = request.cookies.get(SESSION_COOKIE)
        request.state.session_id = existing or str(uuid.uuid4())
        response: Response = await call_next(request)
        if not existing:
            response.set_cookie(
                SESSION_COOKIE,
                request.state.session_id,
                httponly=True,
                samesite="lax",
                max_age=60 * 60 * 24 * 30,
            )
        return response
