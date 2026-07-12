from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import ANY
from uuid import UUID

import pytest

from ai_job_finder.sync_source import main


class _SessionContext:
    def __init__(self, session: object) -> None:
        self._session = session

    def __enter__(self) -> object:
        return self._session

    def __exit__(self, *_args: object) -> None:
        return None


@pytest.mark.parametrize(
    ("status", "expected_exit_code"),
    [("succeeded", 0), ("partial", 1), ("failed", 1)],
)
def test_sync_source_main_exit_codes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: str,
    expected_exit_code: int,
) -> None:
    source_id = UUID("00000000-0000-0000-0000-000000000123")
    settings = SimpleNamespace(
        greenhouse_api_base_url="https://boards-api.greenhouse.io/v1",
        greenhouse_timeout_seconds=5,
        greenhouse_transient_retry_count=1,
        greenhouse_user_agent="ai-job-finder-test/1.0",
        greenhouse_max_response_bytes=2048,
        greenhouse_max_jobs=50,
        greenhouse_retain_raw_payload=True,
        greenhouse_close_on_empty_result=False,
        job_source_stale_after_seconds=1234,
    )
    captured: dict[str, object] = {}
    session = object()

    class _Connector:
        def __init__(self, **kwargs: object) -> None:
            captured["connector_kwargs"] = kwargs

    def fake_run_job_source_import(*args: object, **kwargs: object) -> object:
        captured["run_kwargs"] = kwargs
        return SimpleNamespace(
            id=UUID("00000000-0000-0000-0000-000000000999"),
            status=status,
            jobs_fetched=2,
            jobs_created=1,
            jobs_updated=0,
            jobs_unchanged=1,
            jobs_closed=0,
            evaluations_created=1,
            error_message="provider unavailable" if status != "succeeded" else None,
        )

    monkeypatch.setattr("ai_job_finder.sync_source.get_settings", lambda: settings)
    monkeypatch.setattr("ai_job_finder.sync_source.GreenhouseJobSourceConnector", _Connector)
    monkeypatch.setattr(
        "ai_job_finder.sync_source.get_session_factory",
        lambda: lambda: _SessionContext(session),
    )
    monkeypatch.setattr(
        "ai_job_finder.sync_source.run_job_source_import",
        fake_run_job_source_import,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["sync_source.py", "--source-id", str(source_id)],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == expected_exit_code
    assert f"status={status}" in output
    if status == "succeeded":
        assert "error=" not in output
    else:
        assert "error=provider unavailable" in output
    assert captured["connector_kwargs"] == {
        "api_base_url": settings.greenhouse_api_base_url,
        "timeout_seconds": settings.greenhouse_timeout_seconds,
        "transient_retry_count": settings.greenhouse_transient_retry_count,
        "user_agent": settings.greenhouse_user_agent,
        "max_response_bytes": settings.greenhouse_max_response_bytes,
        "max_jobs": settings.greenhouse_max_jobs,
    }
    assert captured["run_kwargs"] == {
        "source_id": source_id,
        "connector": ANY,
        "retain_raw_payload": settings.greenhouse_retain_raw_payload,
        "close_on_empty": settings.greenhouse_close_on_empty_result,
        "stale_after_seconds": settings.job_source_stale_after_seconds,
    }
