import pytest

from agentic_bookstore.services import cart as cart_svc


def test_add_and_view(sid):
    cart = cart_svc.add_item(sid, "9781000000017", 2)
    assert cart["count"] == 2
    assert cart["subtotal_cents"] == 799 * 2
    again = cart_svc.view_cart(sid)
    assert again["count"] == 2


def test_add_out_of_stock_rejected(sid):
    with pytest.raises(cart_svc.CartError):
        cart_svc.add_item(sid, "9781000000055", 1)


def test_add_over_stock_rejected(sid):
    cart_svc.add_item(sid, "9781000000024", 5)
    with pytest.raises(cart_svc.CartError):
        cart_svc.add_item(sid, "9781000000024", 5)  # 7 in stock, would need 10


def test_update_quantity(sid):
    cart_svc.add_item(sid, "9781000000017", 1)
    cart = cart_svc.update_item(sid, "9781000000017", 3)
    assert cart["items"][0]["quantity"] == 3


def test_update_to_zero_removes(sid):
    cart_svc.add_item(sid, "9781000000017", 1)
    cart = cart_svc.update_item(sid, "9781000000017", 0)
    assert cart["count"] == 0


def test_remove_item(sid):
    cart_svc.add_item(sid, "9781000000017", 1)
    cart_svc.add_item(sid, "9781000000031", 1)
    cart = cart_svc.remove_item(sid, "9781000000017")
    isbns = {i["isbn13"] for i in cart["items"]}
    assert isbns == {"9781000000031"}


def test_sessions_are_isolated(sid):
    other = f"other-{sid}"
    cart_svc.add_item(sid, "9781000000017", 1)
    other_cart = cart_svc.view_cart(other)
    assert other_cart["count"] == 0


def test_add_unknown_isbn(sid):
    with pytest.raises(cart_svc.CartError):
        cart_svc.add_item(sid, "0000000000000", 1)


def test_add_zero_qty_rejected(sid):
    with pytest.raises(cart_svc.CartError):
        cart_svc.add_item(sid, "9781000000017", 0)
