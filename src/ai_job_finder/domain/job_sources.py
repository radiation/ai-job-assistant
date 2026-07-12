from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from ai_job_finder.domain.enums import JobSourceProvider, WorkplaceType


@dataclass(frozen=True, slots=True)
class JobSourceConfigurationSnapshot:
    id: UUID
    provider: JobSourceProvider
    display_name: str
    company_name: str
    board_token: str
    source_url: str | None
    enabled: bool
    last_successful_sync_at: datetime | None
    last_sync_status: str | None
    last_sync_error: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class NormalizedJobPosting:
    provider: JobSourceProvider
    company_name: str
    title: str
    location_text: str | None
    workplace_type: WorkplaceType | None
    description_raw: str
    description_normalized: str
    compensation_text: str | None
    source_url: str | None
    external_id: str
    internal_job_id: str | None
    source_updated_at: datetime | None
    departments: list[str] = field(default_factory=list)
    offices: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    posting_status: str = "open"
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class JobSourceItemFailure:
    external_id: str | None
    message: str


@dataclass(frozen=True, slots=True)
class JobSourceFetchResult:
    jobs: list[NormalizedJobPosting]
    fetched_at: datetime
    connector_version: str
    suspicious_empty: bool = False
    job_failures: list[JobSourceItemFailure] = field(default_factory=list)


class JobSourceConnector(Protocol):
    def fetch_jobs(
        self,
        source: JobSourceConfigurationSnapshot,
    ) -> JobSourceFetchResult: ...
