"""Two-phase checkout: prepare a priced quote, then confirm it into an order.

- `prepare_checkout` snapshots the cart and locks prices into a short-lived quote.
- `confirm_checkout` is the only path that creates an order. It is idempotent on the
  quote token, refuses if the cart or prices changed since the quote, claims the quote
  and decrements stock with conditional UPDATEs (safe under concurrent confirms), and
  charges through the payment provider — all in one transaction.

The chat agent can only call `prepare_checkout`; confirmation needs a human click
(web UI) or host approval / elicitation (MCP).
"""
from __future__ import annotations

import json
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ..config import settings
from ..db import session_scope
from ..models import Book, Cart, CheckoutQuote, Order, OrderItem
from .payments import get_payment_provider


class CheckoutError(Exception):
    pass


class CheckoutConflict(CheckoutError):
    """A concurrent confirm holds the quote; retrying returns the finished order."""


def _cart_lines(sess: Session, session_id: str) -> list[dict[str, Any]]:
    cart = sess.get(Cart, session_id)
    if cart is None or not cart.items:
        raise CheckoutError("cart is empty")
    lines: list[dict[str, Any]] = []
    for it in cart.items:
        book = sess.get(Book, it.isbn13)
        if book is None:
            raise CheckoutError(f"unknown book in cart: {it.isbn13}")
        if book.medium == "physical" and book.stock < it.quantity:
            raise CheckoutError(
                f"insufficient stock for {book.title!r}: {book.stock} < {it.quantity}"
            )
        lines.append({
            "isbn13": book.isbn13,
            "title": book.title,
            "medium": book.medium,
            "unit_price_cents": book.price_cents,
            "quantity": it.quantity,
        })
    return sorted(lines, key=lambda line: line["isbn13"])


def _fingerprint(lines: list[dict[str, Any]]) -> list[tuple[str, int, int]]:
    return [(x["isbn13"], x["quantity"], x["unit_price_cents"]) for x in lines]


def _quote_view(quote: CheckoutQuote) -> dict[str, Any]:
    lines = json.loads(quote.lines_json)
    return {
        "confirmation_token": quote.token,
        "total_cents": quote.total_cents,
        "total": quote.total_cents / 100,
        "requires_shipping": quote.requires_shipping,
        "shipping_name": quote.shipping_name,
        "shipping_address": quote.shipping_address,
        "email": quote.email,
        "expires_at": datetime.fromtimestamp(quote.expires_at, UTC).isoformat(),
        "items": [
            {**x, "line_total_cents": x["unit_price_cents"] * x["quantity"]} for x in lines
        ],
        "status": "awaiting_confirmation",
    }


def _order_view(order: Order, *, requires_shipping: bool, replayed: bool) -> dict[str, Any]:
    days = 3 if requires_shipping else 0
    placed = order.created_at.replace(tzinfo=UTC) if order.created_at.tzinfo is None else order.created_at
    return {
        "order_id": order.order_id,
        "total_cents": order.total_cents,
        "total": order.total_cents / 100,
        "payment_status": order.payment_status,
        "estimated_delivery": (placed + timedelta(days=days)).date().isoformat(),
        "requires_shipping": requires_shipping,
        "replayed": replayed,
        "items": [
            {
                "isbn13": it.isbn13,
                "title": it.title,
                "quantity": it.quantity,
                "unit_price_cents": it.unit_price_cents,
                "line_total_cents": it.unit_price_cents * it.quantity,
            }
            for it in order.items
        ],
    }


def prepare_checkout(
    session_id: str,
    *,
    shipping_name: str = "",
    shipping_address: str = "",
    email: str = "",
    session: Session | None = None,
) -> dict[str, Any]:
    """Price the cart and return a quote with a `confirmation_token`. Places no order."""

    def _run(sess: Session) -> dict[str, Any]:
        lines = _cart_lines(sess, session_id)
        requires_shipping = any(x["medium"] == "physical" for x in lines)
        if requires_shipping and not shipping_address.strip():
            raise CheckoutError("shipping_address is required for physical items")
        now = int(time.time())
        quote = CheckoutQuote(
            token=secrets.token_urlsafe(24),
            session_id=session_id,
            lines_json=json.dumps(lines),
            total_cents=sum(x["unit_price_cents"] * x["quantity"] for x in lines),
            requires_shipping=requires_shipping,
            shipping_name=shipping_name.strip(),
            shipping_address=shipping_address.strip(),
            email=email.strip(),
            status="open",
            created_at=now,
            expires_at=now + settings.checkout_quote_ttl_seconds,
        )
        sess.add(quote)
        sess.flush()
        return _quote_view(quote)

    if session is not None:
        return _run(session)
    with session_scope() as s:
        return _run(s)


def confirm_checkout(
    session_id: str, confirmation_token: str, *, session: Session | None = None
) -> dict[str, Any]:
    """Turn a quote into a paid order. Safe to retry with the same token."""

    def _run(sess: Session) -> dict[str, Any]:
        quote = sess.get(CheckoutQuote, confirmation_token)
        # Same error for unknown and foreign tokens: don't reveal other sessions' quotes.
        if quote is None or quote.session_id != session_id:
            raise CheckoutError("invalid confirmation token")

        if quote.order_id is not None:  # idempotent replay
            order = sess.get(Order, quote.order_id)
            assert order is not None
            return _order_view(order, requires_shipping=quote.requires_shipping, replayed=True)

        if quote.expires_at < time.time():
            raise CheckoutError("quote expired; review the cart and prepare checkout again")

        quoted = json.loads(quote.lines_json)
        if _fingerprint(_cart_lines(sess, session_id)) != _fingerprint(quoted):
            raise CheckoutError(
                "cart or prices changed since the quote; review and prepare checkout again"
            )

        # Claim the quote. Only one transaction can flip open → used.
        claimed = sess.execute(
            update(CheckoutQuote)
            .where(CheckoutQuote.token == quote.token, CheckoutQuote.status == "open")
            .values(status="used")
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount != 1:
            raise CheckoutConflict("checkout already in progress for this quote; retry")

        # Conditional decrement: never oversell, even if another order raced us.
        for line in quoted:
            if line["medium"] != "physical":
                continue
            res = sess.execute(
                update(Book)
                .where(Book.isbn13 == line["isbn13"], Book.stock >= line["quantity"])
                .values(stock=Book.stock - line["quantity"])
                .execution_options(synchronize_session=False)
            )
            if res.rowcount != 1:
                raise CheckoutError(f"{line['title']!r} sold out before checkout completed")

        # Mock PSP runs inside the transaction; a real PSP call would sit outside it
        # (authorize → commit → capture) and rely on the idempotency key for retries.
        payment = get_payment_provider().charge(
            amount_cents=quote.total_cents, idempotency_key=quote.token
        )
        if payment.status != "paid":
            raise CheckoutError(f"payment declined: {payment.decline_reason}")

        order_id = str(uuid.uuid4())
        order = Order(
            order_id=order_id,
            session_id=session_id,
            total_cents=quote.total_cents,
            shipping_name=quote.shipping_name,
            shipping_address=quote.shipping_address,
            email=quote.email,
            payment_status=payment.status,
        )
        order.items = [
            OrderItem(
                order_id=order_id,
                isbn13=x["isbn13"],
                title=x["title"],
                unit_price_cents=x["unit_price_cents"],
                quantity=x["quantity"],
            )
            for x in quoted
        ]
        sess.add(order)
        quote.order_id = order_id

        cart = sess.get(Cart, session_id)
        if cart is not None:
            for it in list(cart.items):
                sess.delete(it)
        sess.flush()
        return _order_view(order, requires_shipping=quote.requires_shipping, replayed=False)

    try:
        if session is not None:
            return _run(session)
        with session_scope() as s:
            return _run(s)
    except OperationalError as e:
        # SQLite reports a lost write race as "database is locked".
        raise CheckoutConflict("checkout is busy; retry with the same token") from e


def get_quote(session_id: str, confirmation_token: str) -> dict[str, Any] | None:
    with session_scope() as s:
        quote = s.get(CheckoutQuote, confirmation_token)
        if quote is None or quote.session_id != session_id:
            return None
        return _quote_view(quote)
