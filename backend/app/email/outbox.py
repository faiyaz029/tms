from ..models import EmailDeliveryStatus
from .base import EmailResult


class OutboxEmailBackend:
    def send(self, recipient: str, subject: str, html_body: str) -> EmailResult:
        return EmailResult(EmailDeliveryStatus.previewed, "outbox")
