from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from ai_job_finder.domain.enums import CareerFactCategory, RemotePreference, VerificationStatus


@dataclass(frozen=True, slots=True)
class CandidateProfileSnapshot:
    id: UUID
    full_name: str
    preferred_locations: list[str]
    remote_preference: RemotePreference
    target_levels: list[str]
    target_functions: list[str]
    created_at: datetime
    updated_at: datetime


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
    verification_status: VerificationStatus
    source_reference: str
    created_at: datetime
    updated_at: datetime

    @property
    def is_usable(self) -> bool:
        return self.verification_status is VerificationStatus.VERIFIED
