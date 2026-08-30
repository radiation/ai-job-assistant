from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from typing import TYPE_CHECKING, Literal

from ai_job_finder.application.job_discovery.scheduling import (
    ActionableMatchEmail,
    EmailNotificationDelivery,
)
from ai_job_finder.infrastructure.database.models import JobSearchActionableNotificationModel

if TYPE_CHECKING:
    from ai_job_finder.settings import Settings

SmtpTlsMode = Literal["starttls", "implicit", "none"]


class SmtpEmailNotificationDelivery(EmailNotificationDelivery):
    def __init__(
        self,
        *,
        host: str,
        port: int,
        tls_mode: SmtpTlsMode,
        username: str | None,
        password: str | None,
        sender_address: str,
        timeout_seconds: float,
    ) -> None:
        self.host = host
        self.port = port
        self.tls_mode = tls_mode
        self.username = username
        self.password = password
        self.sender_address = sender_address
        self.timeout_seconds = timeout_seconds

    def deliver(
        self,
        notification: JobSearchActionableNotificationModel,
        email: ActionableMatchEmail,
    ) -> None:
        message = EmailMessage()
        message["From"] = self.sender_address
        message["To"] = email.recipient_address
        message["Subject"] = email.subject
        message.set_content(email.plain_text_body)

        if self.tls_mode == "implicit":
            with smtplib.SMTP_SSL(
                self.host,
                self.port,
                timeout=self.timeout_seconds,
                context=ssl.create_default_context(),
            ) as client:
                self._authenticate(client)
                client.send_message(message)
            return

        with smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds) as client:
            client.ehlo()
            if self.tls_mode == "starttls":
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            self._authenticate(client)
            client.send_message(message)

    def _authenticate(self, client: smtplib.SMTP) -> None:
        if self.username is not None and self.password is not None:
            client.login(self.username, self.password)


def smtp_email_notification_delivery(settings: Settings) -> SmtpEmailNotificationDelivery | None:
    password = settings.smtp_password.get_secret_value() if settings.smtp_password else None
    has_credentials = (settings.smtp_username is None) == (password is None)
    if (
        not settings.email_alerts_enabled
        or settings.smtp_host is None
        or settings.email_alert_sender is None
        or settings.email_alert_recipient is None
        or not has_credentials
    ):
        return None
    return SmtpEmailNotificationDelivery(
        host=settings.smtp_host,
        port=settings.smtp_port,
        tls_mode=settings.smtp_tls_mode,
        username=settings.smtp_username,
        password=password,
        sender_address=settings.email_alert_sender,
        timeout_seconds=settings.smtp_timeout_seconds,
    )
