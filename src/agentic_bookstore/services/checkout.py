"""Mock checkout — creates an order, decrements stock, clears the cart."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..db import session_scope
from ..models import Book, Cart, Order, OrderItem


class CheckoutError(Exception):
    pass


def checkout(
    session_id: str,
    *,
    shipping_name: str = "",
    shipping_address: str = "",
    email: str = "",
    session: Session | None = None,
) -> dict[str, Any]:
    """Convert the cart into a paid order. Fully mocked payment."""

    def _run(sess: Session) -> dict[str, Any]:
        cart = sess.get(Cart, session_id)
        if cart is None or not cart.items:
            raise CheckoutError("cart is empty")

        needs_shipping = False
        line_items: list[tuple[Book, int]] = []
        for it in cart.items:
            book = sess.get(Book, it.isbn13)
            if book is None:
                raise CheckoutError(f"unknown book in cart: {it.isbn13}")
            if book.medium == "physical":
                needs_shipping = True
                if book.stock < it.quantity:
                    raise CheckoutError(
                        f"insufficient stock for {book.title!r}: {book.stock} < {it.quantity}"
                    )
            line_items.append((book, it.quantity))

        if needs_shipping and not shipping_address.strip():
            raise CheckoutError("shipping_address is required for physical items")

        order_id = str(uuid.uuid4())
        total = 0
        order = Order(
            order_id=order_id,
            session_id=session_id,
            total_cents=0,
            shipping_name=shipping_name.strip(),
            shipping_address=shipping_address.strip(),
            email=email.strip(),
            payment_status="paid",
        )
        sess.add(order)
        for book, qty in line_items:
            line_total = book.price_cents * qty
            total += line_total
            sess.add(OrderItem(
                order_id=order_id,
                isbn13=book.isbn13,
                title=book.title,
                unit_price_cents=book.price_cents,
                quantity=qty,
            ))
            if book.medium == "physical":
                book.stock -= qty
        order.total_cents = total

        for it in list(cart.items):
            sess.delete(it)
        sess.flush()

        estimated_delivery = (
            (datetime.now(UTC) + timedelta(days=3 if needs_shipping else 0)).date().isoformat()
        )
        return {
            "order_id": order_id,
            "total_cents": total,
            "total": total / 100,
            "payment_status": "paid",
            "estimated_delivery": estimated_delivery,
            "requires_shipping": needs_shipping,
            "items": [
                {
                    "isbn13": b.isbn13,
                    "title": b.title,
                    "quantity": q,
                    "unit_price_cents": b.price_cents,
                    "line_total_cents": b.price_cents * q,
                }
                for b, q in line_items
            ],
        }

    if session is not None:
        return _run(session)
    with session_scope() as s:
        return _run(s)
