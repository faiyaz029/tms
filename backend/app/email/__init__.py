from ..config import settings
from .base import EmailBackend
from .console import ConsoleEmailBackend
from .outbox import OutboxEmailBackend
from .smtp import SmtpEmailBackend


def get_email_backend() -> EmailBackend:
    if settings.email_backend == "console":
        return ConsoleEmailBackend()
    if settings.email_backend == "outbox":
        return OutboxEmailBackend()
    if settings.email_backend == "smtp":
        return SmtpEmailBackend()
    raise ValueError(f"Unsupported email backend: {settings.email_backend}")
