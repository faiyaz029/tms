import logging

from ..models import EmailDeliveryStatus
from .base import EmailResult

logger = logging.getLogger(__name__)


class ConsoleEmailBackend:
    def send(self, recipient: str, subject: str, html_body: str) -> EmailResult:
        logger.info(
            "Email logged only; not delivered: recipient=%s subject=%s",
            recipient,
            subject,
        )
        return EmailResult(EmailDeliveryStatus.sent, "console-log")
