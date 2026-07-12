from __future__ import annotations

import json
from datetime import UTC, datetime
from email.message import Message
from io import BytesIO
from urllib.error import HTTPError, URLError
from uuid import UUID

import pytest

from ai_job_finder.domain.enums import JobSourceProvider, WorkplaceType
from ai_job_finder.domain.errors import (
    InvalidJobSourceError,
    JobSourceProviderError,
    JobSourceTimeoutError,
    MalformedJobSourcePayloadError,
)
from ai_job_finder.domain.job_sources import JobSourceConfigurationSnapshot
from ai_job_finder.infrastructure.job_sources.greenhouse import (
    GreenhouseJobSourceConnector,
    html_to_plain_text,
    parse_greenhouse_job,
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
        provider=JobSourceProvider.GREENHOUSE,
        display_name="Acme",
        company_name="Acme",
        board_token="acme",
        source_url="https://boards.greenhouse.io/acme",
        enabled=True,
        last_successful_sync_at=None,
        last_sync_status=None,
        last_sync_error=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _connector(
    *,
    api_base_url: str = "https://boards-api.greenhouse.io/v1",
    timeout_seconds: float = 5,
    transient_retry_count: int = 1,
    user_agent: str = "ai-job-finder-test/1.0",
    max_response_bytes: int | None = 1024,
    max_jobs: int = 25,
) -> GreenhouseJobSourceConnector:
    return GreenhouseJobSourceConnector(
        api_base_url=api_base_url,
        timeout_seconds=timeout_seconds,
        transient_retry_count=transient_retry_count,
        user_agent=user_agent,
        max_response_bytes=max_response_bytes,
        max_jobs=max_jobs,
    )


def _http_headers() -> Message[str, str]:
    return Message()


def _job_payload(*, content: str = "<p>Example</p>", **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": 123,
        "title": "Director, Platform Engineering",
        "absolute_url": "https://EXAMPLE.com:443/acme/jobs/123#fragment",
        "content": content,
        "location": {"name": "Remote - US"},
        "updated_at": "2026-01-02T03:04:05+0000",
        "metadata": [],
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (_job_payload(location={"name": "Remote - US"}), WorkplaceType.REMOTE),
        (
            _job_payload(
                location={"name": "San Francisco"},
                content="Workplace type: Hybrid",
            ),
            WorkplaceType.HYBRID,
        ),
        (
            _job_payload(location={"name": "New York"}, content="Location type: On-site"),
            WorkplaceType.ONSITE,
        ),
        (
            _job_payload(
                location={"name": "New York"},
                content="Workplace type: not a remote role",
            ),
            None,
        ),
        (_job_payload(location={"name": "New York"}, content="Our remote team ships fast."), None),
        (
            _job_payload(
                location={"name": "New York"},
                content="Experience with hybrid cloud required.",
            ),
            None,
        ),
        (
            _job_payload(
                location={"name": "New York"},
                content="Competitive benefits and a remote interview process.",
            ),
            None,
        ),
        (_job_payload(location={"name": "New York"}, content="General information only."), None),
    ],
)
def test_workplace_type_inference_is_conservative(
    payload: dict[str, object],
    expected: WorkplaceType | None,
) -> None:
    posting = parse_greenhouse_job(_source_snapshot(), payload)
    assert posting.workplace_type == expected


def test_html_to_plain_text_strips_script_style_and_keeps_structure() -> None:
    text = html_to_plain_text(
        "<style>.x{color:red}</style><p>Hello</p><ul><li>One</li><li>Two</li></ul><script>alert(1)</script>"
    )

    assert text == "Hello\nOne\nTwo"


def test_parse_greenhouse_job_normalizes_urls_and_timezones() -> None:
    posting = parse_greenhouse_job(_source_snapshot(), _job_payload())

    assert posting.source_url == "https://example.com/acme/jobs/123"
    assert posting.source_updated_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_parse_greenhouse_job_drops_unsafe_urls() -> None:
    posting = parse_greenhouse_job(
        _source_snapshot(),
        _job_payload(absolute_url="javascript:alert(1)"),
    )

    assert posting.source_url is None


def test_fetch_jobs_collects_malformed_entries_without_aborting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_payload = {
        "jobs": [
            _job_payload(),
            {"id": 999, "absolute_url": "https://boards.greenhouse.io/acme/jobs/999"},
        ]
    }
    monkeypatch.setattr(
        "ai_job_finder.infrastructure.job_sources.greenhouse.urlopen",
        lambda *_args, **_kwargs: _Response(json.dumps(response_payload).encode("utf-8")),
    )

    result = _connector().fetch_jobs(_source_snapshot())

    assert len(result.jobs) == 1
    assert len(result.job_failures) == 1
    assert result.job_failures[0].external_id == "999"


def test_fetch_jobs_404_maps_to_invalid_source(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_404(*_args: object, **_kwargs: object) -> object:
        raise HTTPError("https://example.com", 404, "missing", _http_headers(), None)

    monkeypatch.setattr("ai_job_finder.infrastructure.job_sources.greenhouse.urlopen", raise_404)

    with pytest.raises(InvalidJobSourceError):
        _connector().fetch_jobs(_source_snapshot())


def test_fetch_jobs_timeout_maps_to_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "ai_job_finder.infrastructure.job_sources.greenhouse.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("boom")),
    )

    with pytest.raises(JobSourceTimeoutError):
        _connector().fetch_jobs(_source_snapshot())


def test_fetch_jobs_retries_transient_error_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}

    def flaky(*_args: object, **_kwargs: object) -> object:
        calls["count"] += 1
        if calls["count"] == 1:
            raise HTTPError("https://example.com", 500, "boom", _http_headers(), None)
        return _Response(json.dumps({"jobs": [_job_payload()]}).encode("utf-8"))

    monkeypatch.setattr("ai_job_finder.infrastructure.job_sources.greenhouse.urlopen", flaky)
    monkeypatch.setattr(
        "ai_job_finder.infrastructure.job_sources.greenhouse.time.sleep",
        lambda *_args: None,
    )

    result = _connector().fetch_jobs(_source_snapshot())

    assert len(result.jobs) == 1
    assert calls["count"] == 2


def test_fetch_jobs_rejects_malformed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "ai_job_finder.infrastructure.job_sources.greenhouse.urlopen",
        lambda *_args, **_kwargs: _Response(b"not-json"),
    )

    with pytest.raises(MalformedJobSourcePayloadError):
        _connector().fetch_jobs(_source_snapshot())


def test_fetch_jobs_enforces_response_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "ai_job_finder.infrastructure.job_sources.greenhouse.urlopen",
        lambda *_args, **_kwargs: _Response(json.dumps({"jobs": []}).encode("utf-8") + b"x" * 2000),
    )

    with pytest.raises(JobSourceProviderError):
        _connector(max_response_bytes=32).fetch_jobs(_source_snapshot())


def test_fetch_jobs_handles_missing_optional_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "ai_job_finder.infrastructure.job_sources.greenhouse.urlopen",
        lambda *_args, **_kwargs: _Response(
            json.dumps({"jobs": [{"id": 1, "title": "Director"}]}).encode("utf-8")
        ),
    )

    result = _connector().fetch_jobs(_source_snapshot())

    assert result.jobs[0].location_text is None
    assert result.jobs[0].source_url is None


def test_fetch_jobs_rejects_large_job_count(monkeypatch: pytest.MonkeyPatch) -> None:
    jobs = [_job_payload(id=index) for index in range(3)]
    monkeypatch.setattr(
        "ai_job_finder.infrastructure.job_sources.greenhouse.urlopen",
        lambda *_args, **_kwargs: _Response(json.dumps({"jobs": jobs}).encode("utf-8")),
    )

    with pytest.raises(JobSourceProviderError):
        _connector(max_jobs=2).fetch_jobs(_source_snapshot())


def test_fetch_jobs_non_retryable_4xx_does_not_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def raise_400(*_args: object, **_kwargs: object) -> object:
        calls["count"] += 1
        raise HTTPError("https://example.com", 400, "bad", _http_headers(), None)

    monkeypatch.setattr("ai_job_finder.infrastructure.job_sources.greenhouse.urlopen", raise_400)

    with pytest.raises(JobSourceProviderError):
        _connector().fetch_jobs(_source_snapshot())
    assert calls["count"] == 1


def test_fetch_jobs_url_errors_retry_then_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    def flaky(*_args: object, **_kwargs: object) -> object:
        calls["count"] += 1
        raise URLError("network")

    monkeypatch.setattr("ai_job_finder.infrastructure.job_sources.greenhouse.urlopen", flaky)
    monkeypatch.setattr(
        "ai_job_finder.infrastructure.job_sources.greenhouse.time.sleep",
        lambda *_args: None,
    )

    with pytest.raises(JobSourceProviderError):
        _connector().fetch_jobs(_source_snapshot())
    assert calls["count"] == 2


def test_parse_greenhouse_job_rejects_missing_required_fields() -> None:
    with pytest.raises(MalformedJobSourcePayloadError):
        parse_greenhouse_job(_source_snapshot(), {"id": 1})
