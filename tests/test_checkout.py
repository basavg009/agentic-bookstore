import threading
import time
import uuid

import pytest
from sqlalchemy import func, select, update

from agentic_bookstore.db import session_scope
from agentic_bookstore.models import Book, CheckoutQuote, Order
from agentic_bookstore.services import cart as cart_svc
from agentic_bookstore.services import checkout as checkout_svc
from agentic_bookstore.services import payments
from agentic_bookstore.services.books import get_book


def _checkout(sid, **shipping):
    quote = checkout_svc.prepare_checkout(sid, **shipping)
    return checkout_svc.confirm_checkout(sid, quote["confirmation_token"])


@pytest.fixture
def limited_book():
    """A physical book with exactly one copy, unique per test."""
    isbn = f"979{uuid.uuid4().int % 10**10:010d}"
    with session_scope() as s:
        s.add(Book(
            isbn13=isbn, title="Last Copy", author="Test", genre="Fiction",
            description="Only one left.", format="hardcover", medium="physical",
            price_cents=1000, stock=1, year=2020,
        ))
    return isbn


def _orders_for(sid: str) -> int:
    with session_scope() as s:
        return s.execute(select(func.count()).where(Order.session_id == sid)).scalar_one()


def test_empty_cart_rejected(sid):
    with pytest.raises(checkout_svc.CheckoutError):
        checkout_svc.prepare_checkout(sid)


def test_prepare_places_no_order(sid):
    cart_svc.add_item(sid, "9781000000017", 1)
    quote = checkout_svc.prepare_checkout(sid)
    assert quote["status"] == "awaiting_confirmation"
    assert quote["total_cents"] == 799
    assert quote["confirmation_token"]
    assert _orders_for(sid) == 0
    assert cart_svc.view_cart(sid)["count"] == 1


def test_digital_only_checkout_no_address(sid):
    cart_svc.add_item(sid, "9781000000017", 1)
    order = _checkout(sid)
    assert order["payment_status"] == "paid"
    assert order["total_cents"] == 799
    assert order["requires_shipping"] is False
    assert cart_svc.view_cart(sid)["count"] == 0


def test_physical_requires_shipping_address(sid):
    cart_svc.add_item(sid, "9781000000024", 1)
    with pytest.raises(checkout_svc.CheckoutError):
        checkout_svc.prepare_checkout(sid)


def test_physical_decrements_stock(sid):
    stock_before = get_book("9781000000024")["stock"]
    cart_svc.add_item(sid, "9781000000024", 2)
    order = _checkout(sid, shipping_address="221B Baker Street, London")
    assert order["payment_status"] == "paid"
    assert get_book("9781000000024")["stock"] == stock_before - 2


def test_digital_stock_unlimited_after_checkout(sid):
    cart_svc.add_item(sid, "9781000000031", 3)
    _checkout(sid)
    assert get_book("9781000000031")["stock"] == -1


def test_checkout_creates_order_id(sid):
    cart_svc.add_item(sid, "9781000000017", 1)
    order = _checkout(sid)
    assert len(order["order_id"]) == 36
    assert order["items"][0]["title"] == "Dragons of Vareth"


# --- idempotency -------------------------------------------------------------

def test_confirm_is_idempotent(sid):
    cart_svc.add_item(sid, "9781000000017", 1)
    token = checkout_svc.prepare_checkout(sid)["confirmation_token"]
    first = checkout_svc.confirm_checkout(sid, token)
    second = checkout_svc.confirm_checkout(sid, token)
    assert second["order_id"] == first["order_id"]
    assert second["replayed"] is True
    assert _orders_for(sid) == 1


def test_concurrent_confirms_create_one_order(sid):
    cart_svc.add_item(sid, "9781000000017", 1)
    token = checkout_svc.prepare_checkout(sid)["confirmation_token"]
    barrier = threading.Barrier(4)
    outcomes: list[str] = []

    def worker():
        barrier.wait()
        try:
            outcomes.append(checkout_svc.confirm_checkout(sid, token)["order_id"])
        except checkout_svc.CheckoutConflict:
            outcomes.append("conflict")

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert _orders_for(sid) == 1
    order_ids = {o for o in outcomes if o != "conflict"}
    assert len(order_ids) == 1  # every success is the same order
    # A retry after a conflict returns that order.
    assert checkout_svc.confirm_checkout(sid, token)["order_id"] in order_ids


def test_token_bound_to_session(sid):
    cart_svc.add_item(sid, "9781000000017", 1)
    token = checkout_svc.prepare_checkout(sid)["confirmation_token"]
    with pytest.raises(checkout_svc.CheckoutError, match="invalid confirmation token"):
        checkout_svc.confirm_checkout(f"other-{sid}", token)


# --- race-safe stock -----------------------------------------------------------

def test_last_copy_cannot_be_sold_twice(limited_book):
    a, b = f"a-{uuid.uuid4()}", f"b-{uuid.uuid4()}"
    for s in (a, b):
        cart_svc.add_item(s, limited_book, 1)
    qa = checkout_svc.prepare_checkout(a, shipping_address="1 Main St")
    qb = checkout_svc.prepare_checkout(b, shipping_address="2 Main St")
    checkout_svc.confirm_checkout(a, qa["confirmation_token"])
    with pytest.raises(checkout_svc.CheckoutError, match="insufficient stock|sold out"):
        checkout_svc.confirm_checkout(b, qb["confirmation_token"])
    assert get_book(limited_book)["stock"] == 0
    assert _orders_for(b) == 0


def test_failed_confirm_rolls_back_everything(sid, limited_book):
    cart_svc.add_item(sid, limited_book, 1)
    token = checkout_svc.prepare_checkout(sid, shipping_address="1 Main St")["confirmation_token"]
    payments.set_payment_provider(payments.MockPaymentProvider(decline_over_cents=0))
    try:
        with pytest.raises(checkout_svc.CheckoutError, match="payment declined"):
            checkout_svc.confirm_checkout(sid, token)
    finally:
        payments.set_payment_provider(payments.MockPaymentProvider())
    # Stock restored, quote still open, cart intact — then a retry succeeds.
    assert get_book(limited_book)["stock"] == 1
    assert cart_svc.view_cart(sid)["count"] == 1
    assert checkout_svc.confirm_checkout(sid, token)["payment_status"] == "paid"


# --- price lock ------------------------------------------------------------------

def test_price_change_after_quote_is_rejected(sid, limited_book):
    cart_svc.add_item(sid, limited_book, 1)
    token = checkout_svc.prepare_checkout(sid, shipping_address="1 Main St")["confirmation_token"]
    with session_scope() as s:
        s.execute(update(Book).where(Book.isbn13 == limited_book).values(price_cents=5000))
    with pytest.raises(checkout_svc.CheckoutError, match="changed since the quote"):
        checkout_svc.confirm_checkout(sid, token)
    assert _orders_for(sid) == 0


def test_cart_change_after_quote_is_rejected(sid):
    cart_svc.add_item(sid, "9781000000017", 1)
    token = checkout_svc.prepare_checkout(sid)["confirmation_token"]
    cart_svc.add_item(sid, "9781000000031", 1)
    with pytest.raises(checkout_svc.CheckoutError, match="changed since the quote"):
        checkout_svc.confirm_checkout(sid, token)


def test_order_charges_quoted_price(sid):
    cart_svc.add_item(sid, "9781000000017", 2)
    quote = checkout_svc.prepare_checkout(sid)
    order = checkout_svc.confirm_checkout(sid, quote["confirmation_token"])
    assert order["total_cents"] == quote["total_cents"] == 2 * 799


def test_expired_quote_is_rejected(sid):
    cart_svc.add_item(sid, "9781000000017", 1)
    token = checkout_svc.prepare_checkout(sid)["confirmation_token"]
    with session_scope() as s:
        s.execute(
            update(CheckoutQuote)
            .where(CheckoutQuote.token == token)
            .values(expires_at=int(time.time()) - 1)
        )
    with pytest.raises(checkout_svc.CheckoutError, match="expired"):
        checkout_svc.confirm_checkout(sid, token)


def test_concurrent_buyers_of_last_copy(limited_book):
    buyers = [f"race-{i}-{uuid.uuid4()}" for i in range(4)]
    tokens = {}
    for b in buyers:
        cart_svc.add_item(b, limited_book, 1)
        tokens[b] = checkout_svc.prepare_checkout(b, shipping_address="1 Main St")[
            "confirmation_token"
        ]
    barrier = threading.Barrier(len(buyers))
    winners: list[str] = []

    def worker(b: str):
        barrier.wait()
        try:
            checkout_svc.confirm_checkout(b, tokens[b])
            winners.append(b)
        except checkout_svc.CheckoutError:
            pass

    threads = [threading.Thread(target=worker, args=(b,)) for b in buyers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(winners) == 1
    assert get_book(limited_book)["stock"] == 0
    assert sum(_orders_for(b) for b in buyers) == 1
