from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from ai_job_finder.domain.enums import (
    CareerFactCategory,
    CareerFactLifecycle,
    EvidenceTag,
    ProvenanceType,
    RemotePreference,
)


@dataclass(frozen=True, slots=True)
class CandidateProfileSnapshot:
    id: UUID
    full_name: str
    preferred_locations: list[str]
    remote_preference: RemotePreference
    target_levels: list[str]
    target_functions: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    acceptable_remote_geographies: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CareerFactSnapshot:
    id: UUID
    candidate_profile_id: UUID
    category: CareerFactCategory
    source_organization: str | None
    statement: str
    metric: str | None
    technologies: list[str]
    leadership_scope: str | None
    business_outcome: str | None
    approved_wording: str
    lifecycle_status: CareerFactLifecycle
    evidence_tags: list[EvidenceTag]
    provenance_type: ProvenanceType
    source_reference: str
    verified_at: datetime | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @property
    def is_usable(self) -> bool:
        return self.lifecycle_status is CareerFactLifecycle.VERIFIED
