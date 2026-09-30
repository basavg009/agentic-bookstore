"""Session-cookie middleware — issues an HMAC-signed opaque UUID on first visit.

The cookie value is `<uuid>.<signature>`. A cookie whose signature doesn't verify
(forged, tampered, or signed with an old secret) is ignored and a new session is
issued, so a guessed or leaked-looking id alone can't select someone's cart.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from ..config import settings

SESSION_COOKIE = "bookstore_sid"


def _signature(sid: str) -> str:
    mac = hmac.new(settings.session_secret.encode(), sid.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b"=").decode()


def sign_session_id(sid: str) -> str:
    return f"{sid}.{_signature(sid)}"


def verify_session_cookie(value: str | None) -> str | None:
    """Return the session id if the cookie's signature is valid, else None."""
    if not value or "." not in value:
        return None
    sid, _, sig = value.rpartition(".")
    if sid and hmac.compare_digest(sig, _signature(sid)):
        return sid
    return None


def get_session_id(request: Request) -> str:
    """Return the session id set by the middleware."""
    sid = getattr(request.state, "session_id", None)
    if sid is None:
        sid = verify_session_cookie(request.cookies.get(SESSION_COOKIE)) or str(uuid.uuid4())
        request.state.session_id = sid
    return sid


class SessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        existing = verify_session_cookie(request.cookies.get(SESSION_COOKIE))
        request.state.session_id = existing or str(uuid.uuid4())
        response: Response = await call_next(request)
        if not existing:
            response.set_cookie(
                SESSION_COOKIE,
                sign_session_id(request.state.session_id),
                httponly=True,
                samesite="lax",
                secure=settings.is_production,
                max_age=60 * 60 * 24 * 30,
            )
        return response
