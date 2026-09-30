"""HTTP layer: signed session cookie, two-phase checkout routes, chat history."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentic_bookstore.api import app as app_module
from agentic_bookstore.api.session import (
    SESSION_COOKIE,
    sign_session_id,
    verify_session_cookie,
)
from agentic_bookstore.config import settings
from agentic_bookstore.services import cart as cart_svc
from agentic_bookstore.services import conversation as conversation_svc


@pytest.fixture
def client() -> TestClient:
    with TestClient(app_module.create_app()) as c:
        yield c


def _sid(c: TestClient) -> str:
    sid = verify_session_cookie(c.cookies.get(SESSION_COOKIE))
    assert sid
    return sid


def test_cookie_is_signed(client):
    client.get("/api/cart")
    raw = client.cookies.get(SESSION_COOKIE)
    sid, _, sig = raw.rpartition(".")
    assert sid and sig
    assert verify_session_cookie(raw) == sid


def test_forged_cookie_gets_a_fresh_session():
    victim = "victim-session"
    cart_svc.add_item(victim, "9781000000017", 1)
    with TestClient(app_module.create_app()) as c:
        for forged in (victim, f"{victim}.bogus-signature"):
            c.cookies.set(SESSION_COOKIE, forged)
            cart = c.get("/api/cart").json()
            assert cart["session_id"] != victim
            assert cart["count"] == 0


def test_validly_signed_cookie_is_honoured():
    cart_svc.add_item("known-session", "9781000000017", 1)
    with TestClient(app_module.create_app()) as c:
        c.cookies.set(SESSION_COOKIE, sign_session_id("known-session"))
        assert c.get("/api/cart").json()["count"] == 1


def test_two_phase_checkout_over_http(client):
    client.post("/api/cart/items", json={"isbn": "9781000000017", "quantity": 1})
    quote = client.post("/api/checkout/prepare", json={}).json()
    assert quote["total_cents"] == 799
    body = {"confirmation_token": quote["confirmation_token"]}
    first = client.post("/api/checkout/confirm", json=body)
    again = client.post("/api/checkout/confirm", json=body)
    assert first.status_code == again.status_code == 200
    assert first.json()["order_id"] == again.json()["order_id"]
    assert client.post("/api/checkout", json={}).status_code in (404, 405)


def test_confirm_rejects_bad_token(client):
    r = client.post("/api/checkout/confirm", json={"confirmation_token": "nope"})
    assert r.status_code == 400


def test_chat_history_endpoints(client):
    client.get("/api/cart")
    sid = _sid(client)
    conversation_svc.append_messages(sid, [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello!"},
    ])
    assert client.get("/api/chat/history").json()["messages"] == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello!"},
    ]
    client.delete("/api/chat/history")
    assert client.get("/api/chat/history").json()["messages"] == []


def test_production_refuses_default_secret(monkeypatch):
    monkeypatch.setattr(settings, "env", "production")
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        app_module.create_app()
    monkeypatch.setattr(settings, "session_secret", "x" * 40)
    app_module.create_app()
