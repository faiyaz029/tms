import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr

from ..config import settings
from ..models import EmailDeliveryStatus
from .base import EmailResult


class SmtpEmailBackend:
    def send(self, recipient: str, subject: str, html_body: str) -> EmailResult:
        if not settings.email_host:
            raise ValueError("EMAIL_HOST is required for the SMTP backend")
        if not settings.email_from or not parseaddr(settings.email_from)[1]:
            raise ValueError("EMAIL_FROM must contain a valid sender address")
        if bool(settings.email_username) != bool(settings.email_password):
            raise ValueError("EMAIL_USERNAME and EMAIL_PASSWORD must be configured together")

        message = EmailMessage()
        message["From"] = settings.email_from
        message["To"] = recipient
        message["Subject"] = subject
        message["Message-ID"] = make_msgid()
        message.set_content("This statement is available as an HTML email.")
        message.add_alternative(html_body, subtype="html")

        if settings.email_use_ssl:
            with smtplib.SMTP_SSL(
                settings.email_host,
                settings.email_port,
                timeout=15,
                context=ssl.create_default_context(),
            ) as smtp:
                self._send_message(smtp, message)
        else:
            with smtplib.SMTP(settings.email_host, settings.email_port, timeout=15) as smtp:
                if settings.email_starttls:
                    smtp.starttls(context=ssl.create_default_context())
                self._send_message(smtp, message)
        return EmailResult(EmailDeliveryStatus.sent, message["Message-ID"])

    @staticmethod
    def _send_message(smtp: smtplib.SMTP, message: EmailMessage) -> None:
        if settings.email_username:
            smtp.login(settings.email_username, settings.email_password)
        smtp.send_message(message)
