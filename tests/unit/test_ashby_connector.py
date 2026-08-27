from __future__ import annotations

import json
from datetime import UTC, datetime
from io import BytesIO
from uuid import UUID

import pytest

from ai_job_finder.domain.enums import JobSourceProvider, WorkplaceType
from ai_job_finder.domain.job_sources import JobSourceConfigurationSnapshot
from ai_job_finder.infrastructure.job_sources.ashby import (
    AshbyJobSourceConnector,
    parse_ashby_job,
)


class _Response:
    def __init__(self, payload: bytes) -> None:
        self._buffer = BytesIO(payload)

    def read(self, limit: int = -1) -> bytes:
        return self._buffer.read(limit)

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


def _source_snapshot() -> JobSourceConfigurationSnapshot:
    return JobSourceConfigurationSnapshot(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        provider=JobSourceProvider.ASHBY,
        display_name="Acme Ashby",
        company_name="Acme",
        board_token="Acme",
        source_url="https://jobs.ashbyhq.com/Acme",
        enabled=True,
        last_successful_sync_at=None,
        last_sync_status=None,
        last_sync_error=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _connector() -> AshbyJobSourceConnector:
    return AshbyJobSourceConnector(
        api_base_url="https://api.ashbyhq.com/posting-api/job-board",
        timeout_seconds=5,
        transient_retry_count=0,
        user_agent="ai-job-finder-test/1.0",
        max_response_bytes=1024,
        max_jobs=25,
    )


def _job_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "posting-123",
        "title": "Director, Platform Engineering",
        "location": "Remote - United States",
        "workplaceType": "Remote",
        "isRemote": True,
        "descriptionHtml": "<p>Lead platform engineering.</p>",
        "descriptionPlain": "Lead platform engineering.",
        "publishedAt": "2026-01-02T03:04:05Z",
        "employmentType": "FullTime",
        "department": "Engineering",
        "team": "Platform",
        "jobUrl": "https://jobs.ashbyhq.com/Acme/posting-123",
    }
    payload.update(overrides)
    return payload


def test_parse_ashby_job_normalizes_canonical_posting() -> None:
    posting = parse_ashby_job(_source_snapshot(), _job_payload())

    assert posting.provider is JobSourceProvider.ASHBY
    assert posting.source_url == "https://jobs.ashbyhq.com/Acme/posting-123"
    assert posting.workplace_type is WorkplaceType.REMOTE
    assert posting.source_updated_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert posting.departments == ["Engineering"]
    assert posting.metadata["employment_type"] == "FullTime"


def test_fetch_jobs_collects_malformed_entries_without_aborting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ai_job_finder.infrastructure.job_sources.ashby.urlopen",
        lambda *_args, **_kwargs: _Response(
            json.dumps({"jobs": [_job_payload(), {"id": "missing-title"}]}).encode("utf-8")
        ),
    )

    result = _connector().fetch_jobs(_source_snapshot())

    assert len(result.jobs) == 1
    assert result.jobs[0].external_id == "posting-123"
    assert result.job_failures[0].external_id == "missing-title"


def test_validate_board_token_returns_a_valid_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "ai_job_finder.infrastructure.job_sources.ashby.urlopen",
        lambda *_args, **_kwargs: _Response(json.dumps({"jobs": [_job_payload()]}).encode("utf-8")),
    )

    validation = _connector().validate_board_token("Acme")

    assert validation.valid is True
    assert validation.token == "Acme"
    assert validation.sample_titles == ["Director, Platform Engineering"]
