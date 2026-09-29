"""Mock checkout endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..services import checkout as checkout_svc
from .session import get_session_id

router = APIRouter(prefix="/api", tags=["checkout"])


def _sid(request: Request) -> str:
    return get_session_id(request)


class CheckoutBody(BaseModel):
    shipping_name: str = ""
    shipping_address: str = ""
    email: str = ""


@router.post("/checkout")
def checkout(body: CheckoutBody | None = None, session_id: str = Depends(_sid)) -> dict:
    body = body or CheckoutBody()
    try:
        return checkout_svc.checkout(
            session_id,
            shipping_name=body.shipping_name,
            shipping_address=body.shipping_address,
            email=body.email,
        )
    except checkout_svc.CheckoutError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
