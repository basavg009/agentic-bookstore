"""Cart endpoints (session-cookie identified)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..services import cart as cart_svc
from .session import get_session_id

router = APIRouter(prefix="/api/cart", tags=["cart"])


def _sid(request: Request) -> str:
    return get_session_id(request)


class AddItemBody(BaseModel):
    isbn: str
    quantity: int = Field(1, ge=1)


class UpdateItemBody(BaseModel):
    quantity: int = Field(..., ge=0)


@router.get("")
def view(session_id: str = Depends(_sid)) -> dict:
    return cart_svc.view_cart(session_id)


@router.post("/items")
def add(body: AddItemBody, session_id: str = Depends(_sid)) -> dict:
    try:
        return cart_svc.add_item(session_id, body.isbn, body.quantity)
    except cart_svc.CartError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.patch("/items/{isbn}")
def update(isbn: str, body: UpdateItemBody, session_id: str = Depends(_sid)) -> dict:
    try:
        return cart_svc.update_item(session_id, isbn, body.quantity)
    except cart_svc.CartError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/items/{isbn}")
def delete(isbn: str, session_id: str = Depends(_sid)) -> dict:
    return cart_svc.remove_item(session_id, isbn)
