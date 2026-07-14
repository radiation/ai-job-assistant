from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from ai_job_finder.api.v1.routes.dependencies import DbSession
from ai_job_finder.api.v1.schemas import (
    CareerFactProposalMergeRequest,
    CareerFactProposalResponse,
    CareerFactProposalUpdateRequest,
)
from ai_job_finder.application.document_services import (
    accept_career_fact_proposal,
    edit_career_fact_proposal,
    get_career_fact_proposal,
    list_career_fact_proposals,
    merge_career_fact_proposal,
    reject_career_fact_proposal,
)
from ai_job_finder.application.services import get_current_candidate_profile
from ai_job_finder.domain.enums import (
    CareerFactCategory,
    CareerFactProposalReviewStatus,
    EvidenceTag,
)
from ai_job_finder.domain.errors import NotFoundError

router = APIRouter()


@router.get("/fact-proposals", response_model=list[CareerFactProposalResponse])
def get_fact_proposals(
    session: DbSession,
    review_status: CareerFactProposalReviewStatus | None = None,
    document_id: UUID | None = None,
    category: CareerFactCategory | None = None,
    source_organization: str | None = None,
    evidence_tag: EvidenceTag | None = None,
) -> list[CareerFactProposalResponse]:
    candidate = get_current_candidate_profile(session)
    if candidate is None:
        raise NotFoundError("No active candidate profile exists.")
    proposals = list_career_fact_proposals(
        session,
        candidate_profile_id=candidate.id,
        review_status=review_status.value if review_status else None,
        document_id=document_id,
        category=category.value if category else None,
        source_organization=source_organization,
        evidence_tag=evidence_tag.value if evidence_tag else None,
    )
    return [CareerFactProposalResponse.model_validate(proposal) for proposal in proposals]


@router.get("/fact-proposals/{proposal_id}", response_model=CareerFactProposalResponse)
def get_fact_proposal_route(proposal_id: UUID, session: DbSession) -> CareerFactProposalResponse:
    return CareerFactProposalResponse.model_validate(get_career_fact_proposal(session, proposal_id))


@router.put("/fact-proposals/{proposal_id}", response_model=CareerFactProposalResponse)
def put_fact_proposal(
    proposal_id: UUID,
    payload: CareerFactProposalUpdateRequest,
    session: DbSession,
) -> CareerFactProposalResponse:
    proposal = edit_career_fact_proposal(
        session,
        proposal_id=proposal_id,
        category=payload.proposed_category.value,
        source_organization=payload.proposed_source_organization,
        statement=payload.proposed_statement,
        metric=payload.proposed_metric,
        technologies=payload.proposed_technologies,
        leadership_scope=payload.proposed_leadership_scope,
        business_outcome=payload.proposed_business_outcome,
        approved_wording=payload.proposed_approved_wording,
        evidence_tags=[tag.value for tag in payload.proposed_evidence_tags],
        supporting_excerpt=payload.supporting_excerpt,
        source_location=payload.source_location,
        confidence=payload.confidence,
    )
    return CareerFactProposalResponse.model_validate(proposal)


@router.post("/fact-proposals/{proposal_id}/accept", response_model=CareerFactProposalResponse)
def post_fact_proposal_accept(
    proposal_id: UUID,
    session: DbSession,
) -> CareerFactProposalResponse:
    return CareerFactProposalResponse.model_validate(
        accept_career_fact_proposal(session, proposal_id=proposal_id)
    )


@router.post("/fact-proposals/{proposal_id}/reject", response_model=CareerFactProposalResponse)
def post_fact_proposal_reject(
    proposal_id: UUID,
    session: DbSession,
) -> CareerFactProposalResponse:
    return CareerFactProposalResponse.model_validate(
        reject_career_fact_proposal(session, proposal_id=proposal_id)
    )


@router.post("/fact-proposals/{proposal_id}/merge", response_model=CareerFactProposalResponse)
def post_fact_proposal_merge(
    proposal_id: UUID,
    payload: CareerFactProposalMergeRequest,
    session: DbSession,
) -> CareerFactProposalResponse:
    proposal = merge_career_fact_proposal(
        session,
        proposal_id=proposal_id,
        target_fact_id=payload.target_fact_id,
        replace_statement=payload.replace_statement,
        replace_approved_wording=payload.replace_approved_wording,
    )
    return CareerFactProposalResponse.model_validate(proposal)
