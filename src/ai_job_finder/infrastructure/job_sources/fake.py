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
from ai_job_finder.domain.source_detection import GreenhouseBoardValidation


@dataclass(slots=True)
class FakeJobSourceConnector:
    jobs: list[NormalizedJobPosting] = field(default_factory=list)
    job_failures: list[JobSourceItemFailure] = field(default_factory=list)
    connector_version: str = "fake-greenhouse-v1"
    suspicious_empty: bool = False
    error: Exception | None = None
    valid_tokens: set[str] = field(default_factory=set)

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

    def validate_board_token(self, board_token: str) -> GreenhouseBoardValidation:
        token = board_token.strip().lower()
        valid_tokens = self.valid_tokens or {"acme"}
        if token not in valid_tokens:
            return GreenhouseBoardValidation(token=token, status="invalid", valid=False)
        titles = [job.title for job in self.jobs[:5]]
        return GreenhouseBoardValidation(
            token=token,
            status="valid_empty" if not self.jobs else "valid",
            valid=True,
            job_count=len(self.jobs),
            sample_titles=titles,
            company_name=self.jobs[0].company_name if self.jobs else None,
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

    def validate_board_token(self, board_token: str) -> GreenhouseBoardValidation:
        payload = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise JobSourceProviderError("Fake Greenhouse fixture must be a JSON object.")
        token = board_token.strip().lower()
        valid_tokens_payload = payload.get("valid_tokens")
        if isinstance(valid_tokens_payload, dict):
            token_payload = valid_tokens_payload.get(token)
            if not isinstance(token_payload, dict):
                return GreenhouseBoardValidation(token=token, status="invalid", valid=False)
            jobs_payload = token_payload.get("jobs", [])
            if not isinstance(jobs_payload, list):
                raise JobSourceProviderError("Fake Greenhouse fixture jobs must be a list.")
            titles = [str(item["title"]) for item in jobs_payload[:5] if isinstance(item, dict)]
            company_name = token_payload.get("company_name")
            return GreenhouseBoardValidation(
                token=token,
                status="valid_empty" if not jobs_payload else "valid",
                valid=True,
                job_count=len(jobs_payload),
                sample_titles=titles,
                company_name=company_name if isinstance(company_name, str) else None,
            )
        source_token = str(payload.get("board_token") or "acme").lower()
        if token != source_token:
            return GreenhouseBoardValidation(token=token, status="invalid", valid=False)
        jobs_payload = payload.get("jobs", [])
        if not isinstance(jobs_payload, list):
            raise JobSourceProviderError("Fake Greenhouse fixture jobs must be a list.")
        titles = [str(item["title"]) for item in jobs_payload[:5] if isinstance(item, dict)]
        company_name = payload.get("company_name")
        return GreenhouseBoardValidation(
            token=token,
            status="valid_empty" if not jobs_payload else "valid",
            valid=True,
            job_count=len(jobs_payload),
            sample_titles=titles,
            company_name=company_name if isinstance(company_name, str) else None,
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
