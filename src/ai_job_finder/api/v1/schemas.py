from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ai_job_finder.domain.enums import (
    CareerFactCategory,
    JobLeadSource,
    PostingStatus,
    Recommendation,
    RemotePreference,
    VerificationStatus,
    WorkplaceType,
)


class CandidateProfileCreateRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    preferred_locations: list[str] = Field(default_factory=list)
    remote_preference: RemotePreference
    target_levels: list[str] = Field(default_factory=list)
    target_functions: list[str] = Field(default_factory=list)


class CandidateProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    full_name: str
    preferred_locations: list[str]
    remote_preference: RemotePreference
    target_levels: list[str]
    target_functions: list[str]
    created_at: datetime
    updated_at: datetime


class CareerFactCreateRequest(BaseModel):
    category: CareerFactCategory
    source_organization: str | None = Field(default=None, max_length=200)
    statement: str = Field(min_length=1)
    metric: str | None = Field(default=None, max_length=200)
    technologies: list[str] = Field(default_factory=list)
    leadership_scope: str | None = Field(default=None, max_length=200)
    business_outcome: str | None = Field(default=None, max_length=500)
    approved_wording: str = Field(min_length=1)
    verification_status: VerificationStatus
    source_reference: str = Field(min_length=1, max_length=500)


class CareerFactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class JobLeadCreateRequest(BaseModel):
    source: JobLeadSource
    source_url: str | None = Field(default=None, max_length=500)
    external_id: str | None = Field(default=None, max_length=200)
    company_name: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    location_text: str | None = Field(default=None, max_length=200)
    workplace_type: WorkplaceType | None = None
    description_raw: str = Field(min_length=1)
    description_normalized: str = Field(min_length=1)
    compensation_text: str | None = Field(default=None, max_length=200)


class JobLeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source: JobLeadSource
    source_url: str | None
    external_id: str | None
    company_name: str
    title: str
    location_text: str | None
    workplace_type: WorkplaceType | None
    description_raw: str
    description_normalized: str
    compensation_text: str | None
    discovered_at: datetime
    posting_status: PostingStatus
    created_at: datetime
    updated_at: datetime


class JobLeadStatusPatchRequest(BaseModel):
    posting_status: PostingStatus


class JobEvaluationCreateRequest(BaseModel):
    candidate_profile_id: UUID


class JobEvaluationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class HealthResponse(BaseModel):
    status: str
