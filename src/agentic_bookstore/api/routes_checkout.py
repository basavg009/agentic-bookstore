"""Two-phase checkout endpoints: prepare a quote, then confirm it."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..services import checkout as checkout_svc
from .session import get_session_id

router = APIRouter(prefix="/api/checkout", tags=["checkout"])


def _sid(request: Request) -> str:
    return get_session_id(request)


class PrepareBody(BaseModel):
    shipping_name: str = ""
    shipping_address: str = ""
    email: str = ""


class ConfirmBody(BaseModel):
    confirmation_token: str


@router.post("/prepare")
def prepare(body: PrepareBody | None = None, session_id: str = Depends(_sid)) -> dict:
    body = body or PrepareBody()
    try:
        return checkout_svc.prepare_checkout(
            session_id,
            shipping_name=body.shipping_name,
            shipping_address=body.shipping_address,
            email=body.email,
        )
    except checkout_svc.CheckoutError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/confirm")
def confirm(body: ConfirmBody, session_id: str = Depends(_sid)) -> dict:
    try:
        return checkout_svc.confirm_checkout(session_id, body.confirmation_token)
    except checkout_svc.CheckoutConflict as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except checkout_svc.CheckoutError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
