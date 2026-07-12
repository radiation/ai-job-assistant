from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ai_job_finder.domain.common import utc_now
from ai_job_finder.domain.enums import JobSourceProvider, WorkplaceType
from ai_job_finder.domain.errors import JobSourceProviderError
from ai_job_finder.domain.job_sources import (
    JobSourceConfigurationSnapshot,
    JobSourceFetchResult,
    JobSourceItemFailure,
    NormalizedJobPosting,
)


@dataclass(slots=True)
class FakeJobSourceConnector:
    jobs: list[NormalizedJobPosting] = field(default_factory=list)
    job_failures: list[JobSourceItemFailure] = field(default_factory=list)
    connector_version: str = "fake-greenhouse-v1"
    suspicious_empty: bool = False
    error: Exception | None = None

    def fetch_jobs(self, source: JobSourceConfigurationSnapshot) -> JobSourceFetchResult:
        if self.error is not None:
            raise self.error
        return JobSourceFetchResult(
            jobs=list(self.jobs),
            fetched_at=utc_now(),
            connector_version=self.connector_version,
            suspicious_empty=self.suspicious_empty,
            job_failures=list(self.job_failures),
        )


@dataclass(slots=True)
class FileBackedFakeJobSourceConnector:
    fixture_path: Path
    connector_version: str = "file-backed-fake-greenhouse-v1"

    def fetch_jobs(self, source: JobSourceConfigurationSnapshot) -> JobSourceFetchResult:
        payload = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise JobSourceProviderError("Fake Greenhouse fixture must be a JSON object.")
        error = payload.get("error")
        if isinstance(error, str) and error:
            raise JobSourceProviderError(error)
        jobs_payload = payload.get("jobs", [])
        if not isinstance(jobs_payload, list):
            raise JobSourceProviderError("Fake Greenhouse fixture jobs must be a list.")
        job_failures_payload = payload.get("job_failures", [])
        if not isinstance(job_failures_payload, list):
            raise JobSourceProviderError("Fake Greenhouse fixture job_failures must be a list.")
        return JobSourceFetchResult(
            jobs=[_posting_from_fixture(source, item) for item in jobs_payload],
            fetched_at=utc_now(),
            connector_version=self.connector_version,
            suspicious_empty=bool(payload.get("suspicious_empty", False)),
            job_failures=[_job_failure_from_fixture(item) for item in job_failures_payload],
        )


def _posting_from_fixture(
    source: JobSourceConfigurationSnapshot,
    payload: Any,
) -> NormalizedJobPosting:
    if not isinstance(payload, dict):
        raise JobSourceProviderError("Fake Greenhouse job fixture must be an object.")
    external_id = str(payload["external_id"])
    workplace_value = payload.get("workplace_type")
    return NormalizedJobPosting(
        provider=JobSourceProvider.GREENHOUSE,
        company_name=str(payload.get("company_name") or source.company_name),
        title=str(payload["title"]),
        location_text=payload.get("location_text"),
        workplace_type=WorkplaceType(workplace_value) if workplace_value else None,
        description_raw=str(payload["description_raw"]),
        description_normalized=str(
            payload.get("description_normalized") or payload["description_raw"]
        ),
        compensation_text=payload.get("compensation_text"),
        source_url=payload.get("source_url"),
        external_id=external_id,
        internal_job_id=payload.get("internal_job_id"),
        source_updated_at=None,
        departments=list(payload.get("departments", [])),
        offices=list(payload.get("offices", [])),
        metadata=dict(payload.get("metadata", {})),
        raw_payload=payload,
    )


def _job_failure_from_fixture(payload: Any) -> JobSourceItemFailure:
    if not isinstance(payload, dict):
        raise JobSourceProviderError("Fake Greenhouse job failure fixture must be an object.")
    return JobSourceItemFailure(
        external_id=str(payload["external_id"]) if payload.get("external_id") else None,
        message=str(payload["message"]),
    )
