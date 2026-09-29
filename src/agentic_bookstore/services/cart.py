"""Cart service — session-based, no login required."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import session_scope
from ..models import Book, Cart, CartItem


class CartError(Exception):
    pass


def _cart_snapshot(sess: Session, session_id: str) -> dict[str, Any]:
    cart = sess.get(Cart, session_id)
    if cart is None:
        return {"session_id": session_id, "items": [], "subtotal_cents": 0, "count": 0}
    items: list[dict[str, Any]] = []
    subtotal = 0
    for it in cart.items:
        book = sess.get(Book, it.isbn13)
        if book is None:
            continue
        line_total = book.price_cents * it.quantity
        subtotal += line_total
        items.append({
            "isbn13": book.isbn13,
            "title": book.title,
            "author": book.author,
            "format": book.format,
            "medium": book.medium,
            "unit_price_cents": book.price_cents,
            "quantity": it.quantity,
            "line_total_cents": line_total,
        })
    return {
        "session_id": session_id,
        "items": items,
        "subtotal_cents": subtotal,
        "subtotal": subtotal / 100,
        "count": sum(i["quantity"] for i in items),
    }


def _get_or_create(sess: Session, session_id: str) -> Cart:
    cart = sess.get(Cart, session_id)
    if cart is None:
        cart = Cart(session_id=session_id)
        sess.add(cart)
        sess.flush()
    return cart


def view_cart(session_id: str, *, session: Session | None = None) -> dict[str, Any]:
    if session is not None:
        return _cart_snapshot(session, session_id)
    with session_scope() as s:
        return _cart_snapshot(s, session_id)


def add_item(
    session_id: str,
    isbn: str,
    quantity: int = 1,
    *,
    session: Session | None = None,
) -> dict[str, Any]:
    if quantity <= 0:
        raise CartError("quantity must be positive")

    def _run(sess: Session) -> dict[str, Any]:
        book = sess.get(Book, isbn.strip())
        if book is None:
            raise CartError(f"unknown ISBN: {isbn}")
        if book.medium == "physical" and book.stock <= 0:
            raise CartError(f"{book.title!r} is out of stock")
        _get_or_create(sess, session_id)
        existing = sess.execute(
            select(CartItem).where(
                CartItem.session_id == session_id, CartItem.isbn13 == book.isbn13
            )
        ).scalar_one_or_none()
        new_qty = (existing.quantity if existing else 0) + quantity
        if book.medium == "physical" and new_qty > book.stock:
            raise CartError(
                f"only {book.stock} of {book.title!r} in stock (cart would hold {new_qty})"
            )
        if existing:
            existing.quantity = new_qty
        else:
            sess.add(CartItem(session_id=session_id, isbn13=book.isbn13, quantity=quantity))
        sess.flush()
        return _cart_snapshot(sess, session_id)

    if session is not None:
        return _run(session)
    with session_scope() as s:
        return _run(s)


def update_item(
    session_id: str,
    isbn: str,
    quantity: int,
    *,
    session: Session | None = None,
) -> dict[str, Any]:
    if quantity < 0:
        raise CartError("quantity must be >= 0")

    def _run(sess: Session) -> dict[str, Any]:
        existing = sess.execute(
            select(CartItem).where(
                CartItem.session_id == session_id, CartItem.isbn13 == isbn.strip()
            )
        ).scalar_one_or_none()
        if existing is None:
            raise CartError(f"{isbn} is not in the cart")
        if quantity == 0:
            sess.delete(existing)
        else:
            book = sess.get(Book, isbn.strip())
            if book and book.medium == "physical" and quantity > book.stock:
                raise CartError(f"only {book.stock} in stock")
            existing.quantity = quantity
        sess.flush()
        return _cart_snapshot(sess, session_id)

    if session is not None:
        return _run(session)
    with session_scope() as s:
        return _run(s)


def remove_item(
    session_id: str, isbn: str, *, session: Session | None = None
) -> dict[str, Any]:
    def _run(sess: Session) -> dict[str, Any]:
        existing = sess.execute(
            select(CartItem).where(
                CartItem.session_id == session_id, CartItem.isbn13 == isbn.strip()
            )
        ).scalar_one_or_none()
        if existing is not None:
            sess.delete(existing)
            sess.flush()
        return _cart_snapshot(sess, session_id)

    if session is not None:
        return _run(session)
    with session_scope() as s:
        return _run(s)


def clear_cart(session_id: str, *, session: Session | None = None) -> None:
    def _run(sess: Session) -> None:
        cart = sess.get(Cart, session_id)
        if cart is not None:
            for it in list(cart.items):
                sess.delete(it)
            sess.flush()

    if session is not None:
        _run(session)
        return
    with session_scope() as s:
        _run(s)
