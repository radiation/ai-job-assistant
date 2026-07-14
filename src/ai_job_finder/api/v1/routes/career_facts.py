from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from ai_job_finder.api.v1.routes.dependencies import DbSession
from ai_job_finder.api.v1.schemas import (
    CareerFactCreateRequest,
    CareerFactResponse,
    CareerFactTransitionRequest,
    CareerFactUpdateRequest,
)
from ai_job_finder.application.services import (
    create_career_fact,
    get_career_fact,
    get_current_candidate_profile,
    list_career_facts,
    transition_career_fact,
    update_career_fact,
)
from ai_job_finder.domain.enums import CareerFactCategory, CareerFactLifecycle, EvidenceTag
from ai_job_finder.domain.errors import NotFoundError

router = APIRouter()


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
