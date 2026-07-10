from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from ai_job_finder.domain.enums import Recommendation


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    id: UUID
    candidate_profile_id: UUID
    job_lead_id: UUID
    scoring_version: str
    leadership_scope_score: int
    technical_alignment_score: int
    location_score: int
    level_score: int
    platform_ownership_score: int
    referral_priority_score: int
    overall_score: float
    recommendation: Recommendation
    explanation: str
    evaluated_at: datetime
