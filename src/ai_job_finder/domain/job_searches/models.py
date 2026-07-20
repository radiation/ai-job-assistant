from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from ai_job_finder.domain.enums import WorkplaceType
from ai_job_finder.domain.job_searches.enums import JobSearchDomain, JobSearchSeniority


@dataclass(frozen=True, slots=True)
class JobSearchDefinitionSnapshot:
    id: UUID
    name: str
    enabled: bool
    title_include_patterns: list[str] = field(default_factory=list)
    title_exclude_patterns: list[str] = field(default_factory=list)
    target_domains: list[JobSearchDomain] = field(default_factory=list)
    target_seniority_levels: list[JobSearchSeniority] = field(default_factory=list)
    allowed_locations: list[str] = field(default_factory=list)
    allowed_remote_geographies: list[str] = field(default_factory=list)
    allowed_workplace_types: list[WorkplaceType] = field(default_factory=list)
    minimum_score_threshold: float = 0.0
    created_at: datetime | None = None
    updated_at: datetime | None = None
