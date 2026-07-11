from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ai_job_finder.api.dependencies import db_session_dependency
from ai_job_finder.api.v1.schemas import (
    CandidateProfileCreateRequest,
    CandidateProfileResponse,
    CandidateProfileUpdateRequest,
    CareerFactCreateRequest,
    CareerFactResponse,
    CareerFactTransitionRequest,
    CareerFactUpdateRequest,
    HealthResponse,
    JobEvaluationCreateRequest,
    JobEvaluationResponse,
    JobLeadCreateRequest,
    JobLeadResponse,
    JobLeadStatusPatchRequest,
)
from ai_job_finder.application.services import (
    create_candidate_profile,
    create_career_fact,
    create_job_evaluation,
    create_job_lead,
    get_career_fact,
    get_current_candidate_profile,
    get_job_lead,
    get_latest_job_evaluation,
    list_career_facts,
    transition_career_fact,
    update_candidate_profile,
    update_career_fact,
    update_job_lead_status,
)
from ai_job_finder.domain.enums import CareerFactCategory, CareerFactLifecycle, EvidenceTag
from ai_job_finder.domain.errors import NotFoundError

router = APIRouter(prefix="/api/v1")
DbSession = Annotated[Session, Depends(db_session_dependency)]


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.post(
    "/candidate-profile",
    response_model=CandidateProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_candidate_profile(
    payload: CandidateProfileCreateRequest, session: DbSession
) -> CandidateProfileResponse:
    candidate = create_candidate_profile(
        session,
        full_name=payload.full_name,
        preferred_locations=payload.preferred_locations,
        remote_preference=payload.remote_preference.value,
        target_levels=payload.target_levels,
        target_functions=payload.target_functions,
    )
    return CandidateProfileResponse.model_validate(candidate)


@router.get("/candidate-profile", response_model=CandidateProfileResponse)
def get_current_candidate_profile_route(session: DbSession) -> CandidateProfileResponse:
    candidate = get_current_candidate_profile(session)
    if candidate is None:
        raise NotFoundError("No active candidate profile exists.")
    return CandidateProfileResponse.model_validate(candidate)


@router.put("/candidate-profile", response_model=CandidateProfileResponse)
def put_candidate_profile(
    payload: CandidateProfileUpdateRequest,
    session: DbSession,
) -> CandidateProfileResponse:
    candidate = get_current_candidate_profile(session)
    if candidate is None:
        raise NotFoundError("No active candidate profile exists.")
    candidate = update_candidate_profile(
        session,
        candidate_profile_id=candidate.id,
        full_name=payload.full_name,
        preferred_locations=payload.preferred_locations,
        remote_preference=payload.remote_preference.value,
        target_levels=payload.target_levels,
        target_functions=payload.target_functions,
    )
    return CandidateProfileResponse.model_validate(candidate)


@router.post(
    "/career-facts",
    response_model=CareerFactResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_career_fact(
    payload: CareerFactCreateRequest,
    session: DbSession,
) -> CareerFactResponse:
    candidate = get_current_candidate_profile(session)
    if candidate is None:
        raise NotFoundError("No active candidate profile exists.")
    fact = create_career_fact(
        session,
        candidate_profile_id=candidate.id,
        category=payload.category.value,
        source_organization=payload.source_organization,
        statement=payload.statement,
        metric=payload.metric,
        technologies=payload.technologies,
        leadership_scope=payload.leadership_scope,
        business_outcome=payload.business_outcome,
        approved_wording=payload.approved_wording,
        evidence_tags=[tag.value for tag in payload.evidence_tags],
        provenance_type=payload.provenance_type.value,
        source_reference=payload.source_reference,
    )
    return CareerFactResponse.model_validate(fact)


@router.get(
    "/career-facts",
    response_model=list[CareerFactResponse],
)
def get_career_facts(
    session: DbSession,
    lifecycle_status: CareerFactLifecycle | None = None,
    category: CareerFactCategory | None = None,
    source_organization: str | None = None,
    evidence_tag: EvidenceTag | None = None,
    include_archived: bool = False,
) -> list[CareerFactResponse]:
    candidate = get_current_candidate_profile(session)
    if candidate is None:
        raise NotFoundError("No active candidate profile exists.")
    return [
        CareerFactResponse.model_validate(fact)
        for fact in list_career_facts(
            session,
            candidate.id,
            lifecycle_status=lifecycle_status.value if lifecycle_status else None,
            category=category.value if category else None,
            source_organization=source_organization,
            evidence_tag=evidence_tag.value if evidence_tag else None,
            include_archived=include_archived,
        )
    ]


@router.get("/career-facts/{fact_id}", response_model=CareerFactResponse)
def get_career_fact_route(fact_id: UUID, session: DbSession) -> CareerFactResponse:
    return CareerFactResponse.model_validate(get_career_fact(session, fact_id))


@router.put("/career-facts/{fact_id}", response_model=CareerFactResponse)
def put_career_fact(
    fact_id: UUID,
    payload: CareerFactUpdateRequest,
    session: DbSession,
) -> CareerFactResponse:
    fact = update_career_fact(
        session,
        fact_id=fact_id,
        category=payload.category.value,
        source_organization=payload.source_organization,
        statement=payload.statement,
        metric=payload.metric,
        technologies=payload.technologies,
        leadership_scope=payload.leadership_scope,
        business_outcome=payload.business_outcome,
        approved_wording=payload.approved_wording,
        evidence_tags=[tag.value for tag in payload.evidence_tags],
        provenance_type=payload.provenance_type.value,
        source_reference=payload.source_reference,
    )
    return CareerFactResponse.model_validate(fact)


@router.post("/career-facts/{fact_id}/transitions", response_model=CareerFactResponse)
def post_career_fact_transition(
    fact_id: UUID,
    payload: CareerFactTransitionRequest,
    session: DbSession,
) -> CareerFactResponse:
    fact = transition_career_fact(
        session,
        fact_id=fact_id,
        lifecycle_status=payload.lifecycle_status.value,
    )
    return CareerFactResponse.model_validate(fact)


@router.post("/job-leads", response_model=JobLeadResponse, status_code=status.HTTP_201_CREATED)
def post_job_lead(payload: JobLeadCreateRequest, session: DbSession) -> JobLeadResponse:
    job_lead = create_job_lead(
        session,
        source=payload.source.value,
        source_url=payload.source_url,
        external_id=payload.external_id,
        company_name=payload.company_name,
        title=payload.title,
        location_text=payload.location_text,
        workplace_type=payload.workplace_type.value if payload.workplace_type else None,
        description_raw=payload.description_raw,
        description_normalized=payload.description_normalized,
        compensation_text=payload.compensation_text,
    )
    return JobLeadResponse.model_validate(job_lead)


@router.get("/job-leads/{job_lead_id}", response_model=JobLeadResponse)
def get_job_lead_route(job_lead_id: UUID, session: DbSession) -> JobLeadResponse:
    return JobLeadResponse.model_validate(get_job_lead(session, job_lead_id))


@router.patch("/job-leads/{job_lead_id}/status", response_model=JobLeadResponse)
def patch_job_lead_status(
    job_lead_id: UUID,
    payload: JobLeadStatusPatchRequest,
    session: DbSession,
) -> JobLeadResponse:
    job_lead = update_job_lead_status(session, job_lead_id, payload.posting_status.value)
    return JobLeadResponse.model_validate(job_lead)


@router.post(
    "/job-leads/{job_lead_id}/evaluations",
    response_model=JobEvaluationResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_job_evaluation(
    job_lead_id: UUID,
    payload: JobEvaluationCreateRequest,
    session: DbSession,
) -> JobEvaluationResponse:
    evaluation = create_job_evaluation(
        session,
        job_lead_id=job_lead_id,
        candidate_profile_id=payload.candidate_profile_id,
    )
    return JobEvaluationResponse.model_validate(evaluation)


@router.get("/job-leads/{job_lead_id}/evaluations/latest", response_model=JobEvaluationResponse)
def get_latest_evaluation(job_lead_id: UUID, session: DbSession) -> JobEvaluationResponse:
    return JobEvaluationResponse.model_validate(get_latest_job_evaluation(session, job_lead_id))
