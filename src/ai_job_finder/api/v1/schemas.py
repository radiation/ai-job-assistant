from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ai_job_finder.domain.enums import (
    CareerFactCategory,
    CareerFactLifecycle,
    CareerFactProposalReviewStatus,
    EvidenceTag,
    ExtractionRunStatus,
    JobImportRunStatus,
    JobLeadSource,
    JobLocationEligibilityReason,
    JobLocationEligibilityStatus,
    JobSourceProvider,
    PostingStatus,
    ProvenanceType,
    Recommendation,
    RemotePreference,
    SourceDetectionRunStatus,
    SourceDocumentExtractionStatus,
    SourceDocumentType,
    SourcePostingStatus,
    WorkplaceType,
)
from ai_job_finder.domain.job_searches import (
    JobSearchDomain,
    JobSearchRunStatus,
    JobSearchSeniority,
)


class CandidateProfileCreateRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    preferred_locations: list[str] = Field(default_factory=list)
    acceptable_remote_geographies: list[str] = Field(default_factory=list)
    remote_preference: RemotePreference
    target_levels: list[str] = Field(default_factory=list)
    target_functions: list[str] = Field(default_factory=list)


class CandidateProfileUpdateRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    preferred_locations: list[str] = Field(default_factory=list)
    acceptable_remote_geographies: list[str] = Field(default_factory=list)
    remote_preference: RemotePreference
    target_levels: list[str] = Field(default_factory=list)
    target_functions: list[str] = Field(default_factory=list)


class CandidateProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    full_name: str
    preferred_locations: list[str]
    acceptable_remote_geographies: list[str]
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
    evidence_tags: list[EvidenceTag] = Field(default_factory=list)
    provenance_type: ProvenanceType
    source_reference: str = Field(min_length=1, max_length=500)


class CareerFactUpdateRequest(BaseModel):
    category: CareerFactCategory
    source_organization: str | None = Field(default=None, max_length=200)
    statement: str = Field(min_length=1)
    metric: str | None = Field(default=None, max_length=200)
    technologies: list[str] = Field(default_factory=list)
    leadership_scope: str | None = Field(default=None, max_length=200)
    business_outcome: str | None = Field(default=None, max_length=500)
    approved_wording: str = Field(min_length=1)
    evidence_tags: list[EvidenceTag] = Field(default_factory=list)
    provenance_type: ProvenanceType
    source_reference: str = Field(min_length=1, max_length=500)


class CareerFactTransitionRequest(BaseModel):
    lifecycle_status: CareerFactLifecycle


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
    lifecycle_status: CareerFactLifecycle
    evidence_tags: list[EvidenceTag]
    provenance_type: ProvenanceType
    source_reference: str
    verified_at: datetime | None
    archived_at: datetime | None
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


class JobLeadUpdateRequest(BaseModel):
    source_url: str | None = Field(default=None, max_length=500)
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
    source_posting_status: SourcePostingStatus
    posting_status: PostingStatus
    created_at: datetime
    updated_at: datetime


class JobSourceConfigurationCreateRequest(BaseModel):
    provider: JobSourceProvider = JobSourceProvider.GREENHOUSE
    display_name: str = Field(min_length=1, max_length=200)
    company_name: str = Field(min_length=1, max_length=200)
    board_token: str = Field(min_length=1, max_length=200)
    source_url: str | None = Field(default=None, max_length=500)
    enabled: bool = True


class JobSourceConfigurationUpdateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    company_name: str = Field(min_length=1, max_length=200)
    board_token: str = Field(min_length=1, max_length=200)
    source_url: str | None = Field(default=None, max_length=500)


class JobSourceConfigurationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider: JobSourceProvider
    display_name: str
    company_name: str
    board_token: str
    source_url: str | None
    enabled: bool
    last_successful_sync_at: datetime | None
    last_sync_status: JobImportRunStatus | None
    last_sync_error: str | None
    created_at: datetime
    updated_at: datetime


class JobImportRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_configuration_id: UUID
    provider: JobSourceProvider
    status: JobImportRunStatus
    started_at: datetime
    completed_at: datetime | None
    jobs_fetched: int
    jobs_created: int
    jobs_updated: int
    jobs_unchanged: int
    jobs_closed: int
    jobs_failed: int
    evaluations_created: int
    evaluation_failures: int
    error_message: str | None
    connector_version: str


class SourceDetectionRunCreateRequest(BaseModel):
    company_name: str | None = Field(default=None, max_length=200)
    input_url: str | None = Field(default=None, max_length=500)
    brand_alias: str | None = Field(default=None, max_length=200)


class ManualGreenhouseTokenValidationRequest(BaseModel):
    board_token: str = Field(min_length=1, max_length=200)


class SourceDetectionApprovalRequest(BaseModel):
    selected_token: str | None = Field(default=None, max_length=200)
    create_and_sync: bool = False


class SourceDetectionRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_name: str | None
    input_url: str | None
    normalized_url: str | None
    final_url: str | None
    status: SourceDetectionRunStatus
    detected_provider: JobSourceProvider | None
    candidate_tokens: list[dict[str, object]]
    validated_token: str | None
    validated_company_name: str | None
    validated_job_count: int | None
    evidence: list[dict[str, object]]
    error_message: str | None
    created_source_configuration_id: UUID | None
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ManualGreenhouseTokenValidationResponse(BaseModel):
    candidate: dict[str, object]


class SourceDetectionApprovalResponse(BaseModel):
    run: SourceDetectionRunResponse
    source: JobSourceConfigurationResponse
    import_run: JobImportRunResponse | None = None
    existing_source: bool


class JobLocationEligibilityResponse(BaseModel):
    status: JobLocationEligibilityStatus
    reasons: list[JobLocationEligibilityReason]
    summary: str


class JobSearchDefinitionCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    title_include_patterns: list[str] = Field(default_factory=list)
    title_exclude_patterns: list[str] = Field(default_factory=list)
    target_domains: list[JobSearchDomain] = Field(default_factory=list)
    target_seniority_levels: list[JobSearchSeniority] = Field(default_factory=list)
    allowed_locations: list[str] = Field(default_factory=list)
    allowed_remote_geographies: list[str] = Field(default_factory=list)
    allowed_workplace_types: list[WorkplaceType] = Field(default_factory=list)
    minimum_score_threshold: float = Field(ge=0.0, le=100.0)


class JobSearchDefinitionUpdateRequest(JobSearchDefinitionCreateRequest):
    pass


class JobSearchDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    enabled: bool
    title_include_patterns: list[str]
    title_exclude_patterns: list[str]
    target_domains: list[JobSearchDomain]
    target_seniority_levels: list[JobSearchSeniority]
    allowed_locations: list[str]
    allowed_remote_geographies: list[str]
    allowed_workplace_types: list[WorkplaceType]
    minimum_score_threshold: float
    last_run_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class JobSearchRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    search_definition_id: UUID
    status: JobSearchRunStatus
    started_at: datetime
    completed_at: datetime | None
    candidates_considered: Annotated[
        int, Field(description="Number of candidate leads considered during this run.")
    ]
    matched_by_criteria: Annotated[
        int,
        Field(
            description=(
                "Number of candidate leads that matched the saved-search title, domain, "
                "seniority, and location/workplace criteria before score threshold checks."
            )
        ),
    ]
    evaluated_count: Annotated[
        int,
        Field(
            description=(
                "Number of candidate leads for which a current evaluation was successfully "
                "used during this run, whether reused or newly created."
            )
        ),
    ]
    above_threshold_count: Annotated[
        int,
        Field(
            description=(
                "Number of candidate leads whose current evaluation met or exceeded "
                "the saved-search minimum score threshold."
            )
        ),
    ]
    excluded_count: Annotated[
        int,
        Field(
            description=(
                "Number of considered leads that did not end this run as final "
                "saved-search matches, including criteria misses, threshold misses, "
                "and per-lead failures."
            )
        ),
    ]
    failures_count: Annotated[
        int, Field(description="Number of per-lead processing failures recorded during this run.")
    ]
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class JobSearchMatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    search_definition_id: UUID
    search_run_id: UUID
    job_lead_id: UUID
    job_evaluation_id: UUID | None
    scoring_version: str | None
    score_at_match_time: float | None
    recommendation_at_match_time: Recommendation | None
    criteria_matched: bool
    above_threshold: bool
    matched: bool
    matched_criteria: dict[str, list[str]]
    exclusion_reasons: list[str]
    inferred_domains: list[JobSearchDomain]
    inferred_seniority_levels: list[JobSearchSeniority]
    created_at: datetime


class JobSearchRunDetailResponse(BaseModel):
    run: JobSearchRunResponse
    matches: list[JobSearchMatchResponse]


class DiscoveredLeadResponse(BaseModel):
    job: JobLeadResponse
    latest_evaluation: JobEvaluationResponse | None
    location_eligibility: JobLocationEligibilityResponse
    source_configuration_id: UUID
    observation_id: UUID
    external_post_id: str
    external_internal_job_id: str | None
    canonical_url: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    source_updated_at: datetime | None
    duplicate_hint_key: str


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


class CandidateSliceResetResponse(BaseModel):
    candidate_deleted: bool


class SourceDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    candidate_profile_id: UUID
    original_filename: str
    content_type: str
    byte_size: int
    checksum_sha256: str
    source_type: SourceDocumentType
    extraction_status: SourceDocumentExtractionStatus
    extracted_text: str | None
    extraction_error: str | None
    upload_note: str | None
    uploaded_at: datetime
    processed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ExtractionRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_document_id: UUID
    provider: str
    model_id: str
    prompt_version: str
    schema_version: str
    status: ExtractionRunStatus
    started_at: datetime
    completed_at: datetime | None
    input_character_count: int
    input_token_count: int | None
    output_token_count: int | None
    chunk_count: int
    temperature: float | None
    error_message: str | None
    created_at: datetime


class CareerFactProposalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_document_id: UUID
    extraction_run_id: UUID
    candidate_profile_id: UUID
    proposed_category: CareerFactCategory
    proposed_source_organization: str | None
    proposed_statement: str
    proposed_metric: str | None
    proposed_technologies: list[str]
    proposed_leadership_scope: str | None
    proposed_business_outcome: str | None
    proposed_approved_wording: str | None
    proposed_evidence_tags: list[EvidenceTag]
    supporting_excerpt: str
    source_location: str | None
    confidence: float
    review_status: CareerFactProposalReviewStatus
    duplicate_candidate_fact_id: UUID | None
    accepted_career_fact_id: UUID | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CareerFactProposalUpdateRequest(BaseModel):
    proposed_category: CareerFactCategory
    proposed_source_organization: str | None = Field(default=None, max_length=200)
    proposed_statement: str = Field(min_length=1)
    proposed_metric: str | None = Field(default=None, max_length=200)
    proposed_technologies: list[str] = Field(default_factory=list)
    proposed_leadership_scope: str | None = Field(default=None, max_length=200)
    proposed_business_outcome: str | None = Field(default=None, max_length=500)
    proposed_approved_wording: str | None = None
    proposed_evidence_tags: list[EvidenceTag] = Field(default_factory=list)
    supporting_excerpt: str = Field(min_length=1)
    source_location: str | None = Field(default=None, max_length=200)
    confidence: float = Field(ge=0.0, le=1.0)


class CareerFactProposalMergeRequest(BaseModel):
    target_fact_id: UUID
    replace_statement: bool = False
    replace_approved_wording: bool = False
