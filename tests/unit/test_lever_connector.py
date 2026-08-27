from __future__ import annotations

import json
from datetime import UTC, datetime
from io import BytesIO
from uuid import UUID

import pytest

from ai_job_finder.domain.enums import JobSourceProvider, WorkplaceType
from ai_job_finder.domain.job_sources import JobSourceConfigurationSnapshot
from ai_job_finder.infrastructure.job_sources.lever import LeverJobSourceConnector, parse_lever_job


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
        provider=JobSourceProvider.LEVER,
        display_name="Acme Lever",
        company_name="Acme",
        board_token="Acme",
        source_url="https://jobs.lever.co/Acme",
        enabled=True,
        last_successful_sync_at=None,
        last_sync_status=None,
        last_sync_error=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _connector() -> LeverJobSourceConnector:
    return LeverJobSourceConnector(
        api_base_url="https://api.lever.co/v0/postings",
        timeout_seconds=5,
        transient_retry_count=0,
        user_agent="ai-job-finder-test/1.0",
        max_response_bytes=1024,
        max_jobs=25,
    )


def _job_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "04866248-eacc-4955-9696-50e427b60a7e",
        "text": "Director, Platform Engineering",
        "description": "<p>Lead platform engineering.</p>",
        "createdAt": 1_767_323_045_000,
        "categories": {
            "location": "Remote - United States",
            "commitment": "Full-time",
            "team": "Platform",
            "department": "Engineering",
        },
        "hostedUrl": "https://example.invalid/not-canonical",
    }
    payload.update(overrides)
    return payload


def test_parse_lever_job_normalizes_structured_posting_deterministically() -> None:
    posting = parse_lever_job(_source_snapshot(), _job_payload())

    assert posting.provider is JobSourceProvider.LEVER
    assert posting.external_id == "04866248-eacc-4955-9696-50e427b60a7e"
    assert posting.source_url == ("https://jobs.lever.co/Acme/04866248-eacc-4955-9696-50e427b60a7e")
    assert posting.location_text == "Remote - United States"
    assert posting.description_normalized == "Lead platform engineering."
    assert posting.workplace_type is WorkplaceType.REMOTE
    assert posting.source_updated_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert posting.departments == ["Engineering", "Platform"]
    assert posting.metadata["employment_type"] == "Full-time"


def test_fetch_jobs_collects_malformed_entries_without_aborting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ai_job_finder.infrastructure.job_sources.lever.urlopen",
        lambda *_args, **_kwargs: _Response(
            json.dumps([_job_payload(), {"id": "missing-title"}]).encode("utf-8")
        ),
    )

    result = _connector().fetch_jobs(_source_snapshot())

    assert [job.external_id for job in result.jobs] == ["04866248-eacc-4955-9696-50e427b60a7e"]
    assert result.job_failures[0].external_id == "missing-title"


def test_validate_board_token_returns_a_valid_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "ai_job_finder.infrastructure.job_sources.lever.urlopen",
        lambda *_args, **_kwargs: _Response(json.dumps([_job_payload()]).encode("utf-8")),
    )

    validation = _connector().validate_board_token("Acme")

    assert validation.valid is True
    assert validation.token == "Acme"
    assert validation.sample_titles == ["Director, Platform Engineering"]
