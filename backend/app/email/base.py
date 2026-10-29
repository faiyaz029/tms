from dataclasses import dataclass
from typing import Protocol

from ..models import EmailDeliveryStatus


@dataclass(frozen=True)
class EmailResult:
    status: EmailDeliveryStatus
    provider_id: str | None = None


class EmailBackend(Protocol):
    def send(self, recipient: str, subject: str, html_body: str) -> EmailResult: ...
