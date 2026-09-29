import pytest

from agentic_bookstore.services import cart as cart_svc
from agentic_bookstore.services import checkout as checkout_svc
from agentic_bookstore.services.books import get_book


def test_empty_cart_rejected(sid):
    with pytest.raises(checkout_svc.CheckoutError):
        checkout_svc.checkout(sid)


def test_digital_only_checkout_no_address(sid):
    cart_svc.add_item(sid, "9781000000017", 1)
    order = checkout_svc.checkout(sid)
    assert order["payment_status"] == "paid"
    assert order["total_cents"] == 799
    assert order["requires_shipping"] is False
    # Cart is cleared.
    assert cart_svc.view_cart(sid)["count"] == 0


def test_physical_requires_shipping_address(sid):
    cart_svc.add_item(sid, "9781000000024", 1)
    with pytest.raises(checkout_svc.CheckoutError):
        checkout_svc.checkout(sid)


def test_physical_decrements_stock(sid):
    before = get_book("9781000000024")
    assert before is not None
    stock_before = before["stock"]
    cart_svc.add_item(sid, "9781000000024", 2)
    order = checkout_svc.checkout(
        sid, shipping_address="221B Baker Street, London"
    )
    assert order["payment_status"] == "paid"
    after = get_book("9781000000024")
    assert after is not None
    assert after["stock"] == stock_before - 2


def test_digital_stock_unlimited_after_checkout(sid):
    cart_svc.add_item(sid, "9781000000031", 3)
    checkout_svc.checkout(sid)
    b = get_book("9781000000031")
    assert b is not None
    assert b["stock"] == -1


def test_checkout_creates_order_id(sid):
    cart_svc.add_item(sid, "9781000000017", 1)
    order = checkout_svc.checkout(sid)
    assert len(order["order_id"]) == 36
    assert order["items"][0]["title"] == "Dragons of Vareth"
