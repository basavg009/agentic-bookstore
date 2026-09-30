"""Payment provider seam. Checkout depends on the protocol, never on a concrete PSP."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class PaymentResult:
    status: Literal["paid", "declined"]
    reference: str
    decline_reason: str = ""


class PaymentProvider(Protocol):
    def charge(self, *, amount_cents: int, idempotency_key: str) -> PaymentResult:
        """Charge the customer. Must be idempotent on `idempotency_key`."""
        ...


class MockPaymentProvider:
    """Approves everything up to a ceiling so the declined path is exercisable."""

    def __init__(self, decline_over_cents: int = 1_000_000) -> None:
        self.decline_over_cents = decline_over_cents

    def charge(self, *, amount_cents: int, idempotency_key: str) -> PaymentResult:
        reference = f"mock_{idempotency_key[:16]}"
        if amount_cents > self.decline_over_cents:
            return PaymentResult("declined", reference, "amount exceeds mock limit")
        return PaymentResult("paid", reference)


_provider: PaymentProvider = MockPaymentProvider()


def get_payment_provider() -> PaymentProvider:
    return _provider


def set_payment_provider(provider: PaymentProvider) -> None:
    global _provider
    _provider = provider
