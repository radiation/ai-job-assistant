from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ai_job_finder.application.documents._common import (
    _normalize_list,
    _normalize_optional_str,
    _source_type_to_provenance,
)
from ai_job_finder.application.extraction import (
    ExtractedCareerFactProposal,
    normalize_text_for_matching,
)
from ai_job_finder.domain.common import new_uuid, utc_now
from ai_job_finder.domain.document_ingestion import ensure_valid_proposal_transition
from ai_job_finder.domain.enums import CareerFactLifecycle, CareerFactProposalReviewStatus
from ai_job_finder.domain.errors import (
    InvalidProposalEditError,
    InvalidProposalTransitionError,
    MergeTargetMismatchError,
    NotFoundError,
)
from ai_job_finder.infrastructure.database.models import (
    CareerFactModel,
    CareerFactProposalModel,
    ExtractionRunModel,
    SourceDocumentModel,
)


def _token_set(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", normalize_text_for_matching(value)))


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _find_duplicate_fact(
    session: Session,
    *,
    candidate_profile_id: UUID,
    proposal: ExtractedCareerFactProposal,
) -> UUID | None:
    facts = list(
        session.scalars(
            select(CareerFactModel).where(
                CareerFactModel.candidate_profile_id == candidate_profile_id
            )
        )
    )
    proposal_statement_tokens = _token_set(proposal.statement)
    proposal_technologies = {normalize_text_for_matching(item) for item in proposal.technologies}
    proposal_tags = {tag.value for tag in proposal.evidence_tags}
    proposal_metric = normalize_text_for_matching(proposal.metric or "")
    proposal_organization = normalize_text_for_matching(proposal.source_organization or "")
    for fact in facts:
        statement_similarity = _jaccard(proposal_statement_tokens, _token_set(fact.statement))
        same_category = fact.category == proposal.category.value
        fact_organization = normalize_text_for_matching(fact.source_organization or "")
        same_organization = (
            bool(proposal_organization) and proposal_organization == fact_organization
        )
        metric_overlap = bool(proposal_metric) and proposal_metric == normalize_text_for_matching(
            fact.metric or ""
        )
        fact_technologies = {normalize_text_for_matching(item) for item in fact.technologies}
        technology_overlap = bool(proposal_technologies & fact_technologies)
        tag_overlap = bool(proposal_tags & set(fact.evidence_tags))
        score = sum(
            [
                statement_similarity >= 0.72,
                same_category,
                same_organization,
                metric_overlap,
                technology_overlap,
                tag_overlap,
            ]
        )
        if score >= 4 or (statement_similarity >= 0.88 and same_category):
            return fact.id
    return None


def _create_proposal_model(
    *,
    document: SourceDocumentModel,
    run: ExtractionRunModel,
    proposal: ExtractedCareerFactProposal,
    duplicate_fact_id: UUID | None,
) -> CareerFactProposalModel:
    now = utc_now()
    return CareerFactProposalModel(
        id=new_uuid(),
        source_document_id=document.id,
        extraction_run_id=run.id,
        candidate_profile_id=document.candidate_profile_id,
        proposed_category=proposal.category.value,
        proposed_source_organization=_normalize_optional_str(proposal.source_organization),
        proposed_statement=proposal.statement.strip(),
        proposed_metric=_normalize_optional_str(proposal.metric),
        proposed_technologies=_normalize_list(proposal.technologies),
        proposed_leadership_scope=_normalize_optional_str(proposal.leadership_scope),
        proposed_business_outcome=_normalize_optional_str(proposal.business_outcome),
        proposed_approved_wording=_normalize_optional_str(proposal.approved_wording),
        proposed_evidence_tags=_normalize_list([tag.value for tag in proposal.evidence_tags]),
        supporting_excerpt=proposal.supporting_excerpt.strip(),
        source_location=_normalize_optional_str(proposal.source_location),
        confidence=proposal.confidence,
        review_status=CareerFactProposalReviewStatus.PENDING.value,
        duplicate_candidate_fact_id=duplicate_fact_id,
        created_at=now,
        updated_at=now,
    )


def list_career_fact_proposals(
    session: Session,
    *,
    candidate_profile_id: UUID,
    review_status: str | None = None,
    document_id: UUID | None = None,
    category: str | None = None,
    source_organization: str | None = None,
    evidence_tag: str | None = None,
) -> list[CareerFactProposalModel]:
    query = select(CareerFactProposalModel).where(
        CareerFactProposalModel.candidate_profile_id == candidate_profile_id
    )
    if review_status is not None:
        query = query.where(CareerFactProposalModel.review_status == review_status)
    if document_id is not None:
        query = query.where(CareerFactProposalModel.source_document_id == document_id)
    if category is not None:
        query = query.where(CareerFactProposalModel.proposed_category == category)
    if source_organization is not None:
        query = query.where(
            CareerFactProposalModel.proposed_source_organization == source_organization
        )
    proposals = list(
        session.scalars(
            query.options(selectinload(CareerFactProposalModel.source_document)).order_by(
                CareerFactProposalModel.review_status.asc(),
                CareerFactProposalModel.created_at.desc(),
            )
        )
    )
    if evidence_tag is not None:
        proposals = [
            proposal for proposal in proposals if evidence_tag in proposal.proposed_evidence_tags
        ]
    return proposals


def get_career_fact_proposal(session: Session, proposal_id: UUID) -> CareerFactProposalModel:
    proposal = session.scalar(
        select(CareerFactProposalModel)
        .where(CareerFactProposalModel.id == proposal_id)
        .options(selectinload(CareerFactProposalModel.source_document))
    )
    if proposal is None:
        msg = f"Career fact proposal {proposal_id} was not found."
        raise NotFoundError(msg)
    return proposal


def edit_career_fact_proposal(
    session: Session,
    *,
    proposal_id: UUID,
    category: str,
    source_organization: str | None,
    statement: str,
    metric: str | None,
    technologies: list[str],
    leadership_scope: str | None,
    business_outcome: str | None,
    approved_wording: str | None,
    evidence_tags: list[str],
    supporting_excerpt: str,
    source_location: str | None,
    confidence: float,
) -> CareerFactProposalModel:
    proposal = get_career_fact_proposal(session, proposal_id)
    if proposal.review_status != CareerFactProposalReviewStatus.PENDING.value:
        msg = "Reviewed proposals are immutable except for audit metadata."
        raise InvalidProposalTransitionError(msg)
    if proposal.supporting_excerpt != supporting_excerpt.strip():
        msg = "Supporting excerpt is immutable after extraction."
        raise InvalidProposalEditError(msg)
    proposal.proposed_category = category
    proposal.proposed_source_organization = _normalize_optional_str(source_organization)
    proposal.proposed_statement = statement.strip()
    proposal.proposed_metric = _normalize_optional_str(metric)
    proposal.proposed_technologies = _normalize_list(technologies)
    proposal.proposed_leadership_scope = _normalize_optional_str(leadership_scope)
    proposal.proposed_business_outcome = _normalize_optional_str(business_outcome)
    proposal.proposed_approved_wording = _normalize_optional_str(approved_wording)
    proposal.proposed_evidence_tags = _normalize_list(evidence_tags)
    proposal.source_location = _normalize_optional_str(source_location)
    proposal.confidence = confidence
    proposal.updated_at = utc_now()
    session.add(proposal)
    session.commit()
    session.refresh(proposal)
    return proposal


def accept_career_fact_proposal(session: Session, *, proposal_id: UUID) -> CareerFactProposalModel:
    proposal = get_career_fact_proposal(session, proposal_id)
    ensure_valid_proposal_transition(
        CareerFactProposalReviewStatus(proposal.review_status),
        CareerFactProposalReviewStatus.ACCEPTED,
    )
    fact = CareerFactModel(
        id=new_uuid(),
        candidate_profile_id=proposal.candidate_profile_id,
        category=proposal.proposed_category,
        source_organization=proposal.proposed_source_organization,
        statement=proposal.proposed_statement,
        metric=proposal.proposed_metric,
        technologies=list(proposal.proposed_technologies),
        leadership_scope=proposal.proposed_leadership_scope,
        business_outcome=proposal.proposed_business_outcome,
        approved_wording=proposal.proposed_approved_wording or proposal.proposed_statement,
        lifecycle_status=CareerFactLifecycle.DRAFT.value,
        evidence_tags=list(proposal.proposed_evidence_tags),
        provenance_type=_source_type_to_provenance(proposal.source_document.source_type),
        source_reference=f"source_document:{proposal.source_document_id} proposal:{proposal.id}",
        verified_at=None,
        archived_at=None,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    proposal.review_status = CareerFactProposalReviewStatus.ACCEPTED.value
    proposal.accepted_career_fact_id = fact.id
    proposal.reviewed_at = utc_now()
    session.add_all([fact, proposal])
    session.commit()
    session.refresh(proposal)
    return proposal


def reject_career_fact_proposal(session: Session, *, proposal_id: UUID) -> CareerFactProposalModel:
    proposal = get_career_fact_proposal(session, proposal_id)
    ensure_valid_proposal_transition(
        CareerFactProposalReviewStatus(proposal.review_status),
        CareerFactProposalReviewStatus.REJECTED,
    )
    proposal.review_status = CareerFactProposalReviewStatus.REJECTED.value
    proposal.reviewed_at = utc_now()
    session.add(proposal)
    session.commit()
    session.refresh(proposal)
    return proposal


def merge_career_fact_proposal(
    session: Session,
    *,
    proposal_id: UUID,
    target_fact_id: UUID,
    replace_statement: bool = False,
    replace_approved_wording: bool = False,
) -> CareerFactProposalModel:
    proposal = get_career_fact_proposal(session, proposal_id)
    ensure_valid_proposal_transition(
        CareerFactProposalReviewStatus(proposal.review_status),
        CareerFactProposalReviewStatus.MERGED,
    )
    fact = session.get(CareerFactModel, target_fact_id)
    if fact is None:
        msg = f"Career fact {target_fact_id} was not found."
        raise NotFoundError(msg)
    if fact.candidate_profile_id != proposal.candidate_profile_id:
        msg = "Merge target belongs to a different candidate profile."
        raise MergeTargetMismatchError(msg)
    fact.technologies = _normalize_list([*fact.technologies, *proposal.proposed_technologies])
    fact.evidence_tags = _normalize_list([*fact.evidence_tags, *proposal.proposed_evidence_tags])
    if fact.metric is None:
        fact.metric = proposal.proposed_metric
    if fact.leadership_scope is None:
        fact.leadership_scope = proposal.proposed_leadership_scope
    if fact.business_outcome is None:
        fact.business_outcome = proposal.proposed_business_outcome
    if replace_statement:
        fact.statement = proposal.proposed_statement
    if replace_approved_wording and proposal.proposed_approved_wording:
        fact.approved_wording = proposal.proposed_approved_wording
    if fact.lifecycle_status == CareerFactLifecycle.VERIFIED.value:
        fact.lifecycle_status = CareerFactLifecycle.DRAFT.value
        fact.verified_at = None
        fact.archived_at = None
    fact.updated_at = utc_now()
    proposal.review_status = CareerFactProposalReviewStatus.MERGED.value
    proposal.accepted_career_fact_id = fact.id
    proposal.reviewed_at = utc_now()
    session.add_all([fact, proposal])
    session.commit()
    session.refresh(proposal)
    return proposal
