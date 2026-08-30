from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_job_finder.scheduled_discovery import main


class _SessionContext:
    def __enter__(self) -> object:
        return object()

    def __exit__(self, *_args: object) -> None:
        return None


def test_scheduled_discovery_wires_configured_email_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        email_alerts_enabled=True,
        smtp_host="smtp.example.test",
        smtp_port=587,
        smtp_tls_mode="starttls",
        smtp_username=None,
        smtp_password=None,
        email_alert_sender="sender@example.test",
        email_alert_recipient="alerts@example.test",
        smtp_timeout_seconds=10.0,
        public_application_base_url="https://jobs.example.test",
        job_discovery_max_queries_per_run=4,
        job_discovery_result_limit=5,
        job_discovery_max_total_candidates=25,
        source_detection_max_linked_scripts=4,
        source_detection_max_script_bytes=200_000,
        source_detection_total_script_bytes=500_000,
        greenhouse_retain_raw_payload=True,
        greenhouse_close_on_empty_result=False,
        job_source_stale_after_seconds=3600,
        job_discovery_provider="fake",
    )
    captured: dict[str, object] = {}
    email_delivery = object()

    monkeypatch.setattr("ai_job_finder.scheduled_discovery.get_settings", lambda: settings)
    monkeypatch.setattr(
        "ai_job_finder.scheduled_discovery.smtp_email_notification_delivery",
        lambda value: email_delivery,
    )
    monkeypatch.setattr(
        "ai_job_finder.scheduled_discovery.get_db_session",
        lambda: iter([_SessionContext()]),
    )
    monkeypatch.setattr(
        "ai_job_finder.scheduled_discovery.job_discovery_provider_dependency",
        lambda value: object(),
    )
    monkeypatch.setattr(
        "ai_job_finder.scheduled_discovery.public_page_fetcher_dependency",
        lambda value: object(),
    )
    monkeypatch.setattr(
        "ai_job_finder.scheduled_discovery.job_source_board_validator_dependency",
        lambda value: object(),
    )
    monkeypatch.setattr(
        "ai_job_finder.scheduled_discovery.job_source_connector_dependency",
        lambda value: object(),
    )

    def fake_run_due_scheduled_discoveries(*args: object, **kwargs: object) -> list[object]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr(
        "ai_job_finder.scheduled_discovery.run_due_scheduled_discoveries",
        fake_run_due_scheduled_discoveries,
    )

    assert main() == 0
    assert captured["deliver_email_notification"] is email_delivery
    assert captured["email_recipient_address"] == "alerts@example.test"
    assert captured["public_application_base_url"] == "https://jobs.example.test"
