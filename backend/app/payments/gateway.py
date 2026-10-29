from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from fastapi import HTTPException

from ..config import settings


@dataclass(frozen=True)
class GatewayInitiation:
    reference: str
    amount: Decimal
    label: str


class PaymentGateway(Protocol):
    def initiate(self, intent_id: int, amount: Decimal) -> GatewayInitiation: ...

    def parse_result(self, result: str) -> str: ...


class SimulatedGateway:
    def initiate(self, intent_id: int, amount: Decimal) -> GatewayInitiation:
        return GatewayInitiation(
            reference=f"SIM-{intent_id:08d}",
            amount=amount,
            label="SIMULATED PAYMENT",
        )

    def parse_result(self, result: str) -> str:
        if result not in {"success", "fail", "cancel"}:
            raise HTTPException(422, "Unsupported simulated payment result")
        return result


def get_gateway() -> PaymentGateway:
    if settings.payments_mode != "simulated":
        raise HTTPException(503, "Online payments are disabled")
    return SimulatedGateway()
