from __future__ import annotations

from email.message import EmailMessage
from types import SimpleNamespace
from typing import cast

import pytest

from ai_job_finder.application.job_discovery import ActionableMatchEmail
from ai_job_finder.infrastructure.database.models import JobSearchActionableNotificationModel
from ai_job_finder.infrastructure.notifications.smtp import (
    SmtpEmailNotificationDelivery,
    smtp_email_notification_delivery,
)
from ai_job_finder.settings import Settings


def test_smtp_delivery_sends_explicit_recipient_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeSmtp:
        def __init__(self, host: str, port: int, *, timeout: float) -> None:
            captured.update(host=host, port=port, timeout=timeout)

        def __enter__(self) -> FakeSmtp:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def ehlo(self) -> None:
            captured["ehlo"] = True

        def starttls(self, *, context: object) -> None:
            captured["starttls"] = context

        def login(self, username: str, password: str) -> None:
            captured["credentials"] = (username, password)

        def send_message(self, message: object) -> None:
            captured["message"] = message

    monkeypatch.setattr("ai_job_finder.infrastructure.notifications.smtp.smtplib.SMTP", FakeSmtp)
    delivery = SmtpEmailNotificationDelivery(
        host="smtp.example.test",
        port=587,
        tls_mode="starttls",
        username="mailer",
        password="not-logged",
        sender_address="sender@example.test",
        timeout_seconds=4.5,
    )

    delivery.deliver(
        cast(JobSearchActionableNotificationModel, SimpleNamespace()),
        ActionableMatchEmail(
            recipient_address="alerts@example.test",
            subject="New job match: Acme - Director",
            plain_text_body="A concise message.",
        ),
    )

    message = cast(EmailMessage, captured["message"])
    assert captured["host"] == "smtp.example.test"
    assert captured["credentials"] == ("mailer", "not-logged")
    assert message["To"] == "alerts@example.test"
    assert message["Subject"] == "New job match: Acme - Director"


def test_smtp_delivery_factory_requires_enabled_complete_configuration() -> None:
    assert smtp_email_notification_delivery(Settings()) is None
    assert (
        smtp_email_notification_delivery(
            Settings(email_alerts_enabled=True, smtp_host="smtp.example.test")
        )
        is None
    )
    assert (
        smtp_email_notification_delivery(
            Settings(
                email_alerts_enabled=True,
                smtp_host="smtp.example.test",
                email_alert_sender="sender@example.test",
                email_alert_recipient="alerts@example.test",
            )
        )
        is not None
    )
