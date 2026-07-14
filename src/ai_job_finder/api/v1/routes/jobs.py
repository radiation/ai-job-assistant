from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from ai_job_finder.api.v1.routes.dependencies import DbSession
from ai_job_finder.api.v1.schemas import (
    JobEvaluationCreateRequest,
    JobEvaluationResponse,
    JobLeadCreateRequest,
    JobLeadResponse,
    JobLeadStatusPatchRequest,
    JobLeadUpdateRequest,
)
from ai_job_finder.application.services import (
    create_job_evaluation,
    create_job_lead,
    find_job_leads,
    get_job_lead,
    get_latest_job_evaluation,
    list_job_evaluations,
    update_job_lead,
    update_job_lead_status,
)

router = APIRouter()


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


@router.get("/job-leads", response_model=list[JobLeadResponse])
def get_job_leads(
    session: DbSession,
    posting_status: str | None = None,
    source: str | None = None,
    external_id: str | None = None,
) -> list[JobLeadResponse]:
    return [
        JobLeadResponse.model_validate(job_lead)
        for job_lead in find_job_leads(
            session,
            posting_status=posting_status,
            source=source,
            external_id=external_id,
        )
    ]


@router.get("/job-leads/{job_lead_id}", response_model=JobLeadResponse)
def get_job_lead_route(job_lead_id: UUID, session: DbSession) -> JobLeadResponse:
    return JobLeadResponse.model_validate(get_job_lead(session, job_lead_id))


@router.put("/job-leads/{job_lead_id}", response_model=JobLeadResponse)
def put_job_lead(
    job_lead_id: UUID,
    payload: JobLeadUpdateRequest,
    session: DbSession,
) -> JobLeadResponse:
    job_lead = update_job_lead(
        session,
        job_lead_id=job_lead_id,
        source_url=payload.source_url,
        company_name=payload.company_name,
        title=payload.title,
        location_text=payload.location_text,
        workplace_type=payload.workplace_type.value if payload.workplace_type else None,
        description_raw=payload.description_raw,
        description_normalized=payload.description_normalized,
        compensation_text=payload.compensation_text,
    )
    return JobLeadResponse.model_validate(job_lead)


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


@router.get(
    "/job-leads/{job_lead_id}/evaluations",
    response_model=list[JobEvaluationResponse],
)
def get_job_evaluations(job_lead_id: UUID, session: DbSession) -> list[JobEvaluationResponse]:
    return [
        JobEvaluationResponse.model_validate(evaluation)
        for evaluation in list_job_evaluations(session, job_lead_id)
    ]
