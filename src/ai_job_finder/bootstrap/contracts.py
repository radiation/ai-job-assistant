from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class HarnessError(Exception):
    def __init__(
        self,
        phase: str,
        assertion: str,
        *,
        endpoint: str,
        expected: Any,
        actual: Any,
        response_body: Any | None = None,
    ) -> None:
        super().__init__(assertion)
        self.phase = phase
        self.assertion = assertion
        self.endpoint = endpoint
        self.expected = expected
        self.actual = actual
        self.response_body = response_body


class RemotePreference(StrEnum):
    REMOTE_ONLY = "remote_only"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    FLEXIBLE = "flexible"


class CareerFactLifecycle(StrEnum):
    DRAFT = "draft"
    VERIFIED = "verified"
    ARCHIVED = "archived"


class CareerFactCategory(StrEnum):
    LEADERSHIP = "leadership"
    PLATFORM = "platform"
    DELIVERY = "delivery"
    OPERATIONS = "operations"
    TRANSFORMATION = "transformation"


class ProvenanceType(StrEnum):
    PROJECT_NOTES = "project_notes"
    PERSONAL_RECOLLECTION = "personal_recollection"


class JobLeadSource(StrEnum):
    MANUAL = "manual"
    GREENHOUSE = "greenhouse"


class WorkplaceType(StrEnum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"


class CandidatePayload(BaseModel):
    full_name: str
    preferred_locations: list[str]
    remote_preference: RemotePreference
    target_levels: list[str]
    target_functions: list[str]


class CandidateResponse(CandidatePayload):
    model_config = ConfigDict(extra="ignore")

    id: str
    created_at: str
    updated_at: str


class CareerFactPayload(BaseModel):
    category: CareerFactCategory
    source_organization: str | None
    statement: str
    metric: str | None
    technologies: list[str]
    leadership_scope: str | None
    business_outcome: str | None
    approved_wording: str
    evidence_tags: list[str]
    provenance_type: ProvenanceType
    source_reference: str


class CareerFactResponse(CareerFactPayload):
    model_config = ConfigDict(extra="ignore")

    id: str
    candidate_profile_id: str
    lifecycle_status: CareerFactLifecycle
    verified_at: str | None
    archived_at: str | None
    created_at: str
    updated_at: str


class JobLeadPayload(BaseModel):
    source: JobLeadSource
    source_url: str | None
    external_id: str
    company_name: str
    title: str
    location_text: str | None
    workplace_type: WorkplaceType | None
    description_raw: str
    description_normalized: str
    compensation_text: str | None


class JobLeadResponse(JobLeadPayload):
    model_config = ConfigDict(extra="ignore")

    id: str
    discovered_at: str
    posting_status: str
    created_at: str
    updated_at: str


class JobEvaluationResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    candidate_profile_id: str
    job_lead_id: str
    scoring_version: str
    leadership_scope_score: int
    technical_alignment_score: int
    location_score: int
    level_score: int
    platform_ownership_score: int
    referral_priority_score: int
    overall_score: float
    recommendation: str
    explanation: str
    evaluated_at: str


class JobSourceConfigurationPayload(BaseModel):
    provider: str = "greenhouse"
    display_name: str
    company_name: str
    board_token: str
    source_url: str | None
    enabled: bool = True


class JobSourceConfigurationResponse(JobSourceConfigurationPayload):
    model_config = ConfigDict(extra="ignore")

    id: str
    last_successful_sync_at: str | None = None
    last_sync_status: str | None = None
    last_sync_error: str | None = None


class JobImportRunResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    source_configuration_id: str
    status: str
    jobs_fetched: int
    jobs_created: int
    jobs_updated: int
    jobs_unchanged: int
    jobs_closed: int
    jobs_failed: int
    evaluations_created: int
    evaluation_failures: int
    error_message: str | None = None


class SourceDetectionRunPayload(BaseModel):
    company_name: str | None = None
    input_url: str | None = None
    brand_alias: str | None = None


class SourceDetectionRunResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    company_name: str | None = None
    input_url: str | None = None
    final_url: str | None = None
    status: str
    detected_provider: str | None = None
    candidate_tokens: list[dict[str, Any]] = []
    validated_token: str | None = None
    validated_job_count: int | None = None
    evidence: list[dict[str, Any]] = []
    error_message: str | None = None
    created_source_configuration_id: str | None = None


class SourceDetectionApprovalResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run: SourceDetectionRunResponse
    source: JobSourceConfigurationResponse
    import_run: JobImportRunResponse | None = None
    existing_source: bool


class DiscoveredLeadResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    job: JobLeadResponse
    latest_evaluation: JobEvaluationResponse | None
    external_post_id: str


class SourceDocumentResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    original_filename: str
    checksum_sha256: str
    source_type: str
    extraction_status: str


class ExtractionRunResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    source_document_id: str
    provider: str
    model_id: str
    prompt_version: str
    schema_version: str
    status: str
    input_token_count: int | None = None
    output_token_count: int | None = None


class CareerFactProposalResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    source_document_id: str
    proposed_statement: str
    review_status: str
    accepted_career_fact_id: str | None = None


class HealthResponse(BaseModel):
    status: str


class ResetResponse(BaseModel):
    candidate_deleted: bool


@dataclass(slots=True)
class AssertionResult:
    phase: str
    summary: str
    passed: bool = True


@dataclass(slots=True)
class RunMetadata:
    base_url: str
    reset_requested: bool
    created_ids: dict[str, str] = field(default_factory=dict)
    reused_ids: dict[str, str] = field(default_factory=dict)
    phases: list[dict[str, Any]] = field(default_factory=list)
    passed: int = 0
    failed: int = 0


def _metadata_to_dict(metadata: RunMetadata | Any) -> dict[str, Any]:
    if hasattr(metadata, "__dataclass_fields__"):
        return asdict(metadata)
    return {
        "base_url": getattr(metadata, "base_url", ""),
        "reset_requested": getattr(metadata, "reset_requested", False),
        "created_ids": getattr(metadata, "created_ids", {}),
        "reused_ids": getattr(metadata, "reused_ids", {}),
        "phases": getattr(metadata, "phases", []),
        "passed": getattr(metadata, "passed", 0),
        "failed": getattr(metadata, "failed", 0),
    }
