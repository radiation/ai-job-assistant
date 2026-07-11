from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ai_job_finder.domain.career_fact import transition_metadata
from ai_job_finder.domain.common import new_uuid, utc_now
from ai_job_finder.domain.enums import CareerFactLifecycle, PostingStatus
from ai_job_finder.domain.errors import (
    ArchivedCareerFactModificationError,
    EvaluationPreconditionError,
    NotFoundError,
    SingleCandidateViolationError,
)
from ai_job_finder.domain.job_lead import ensure_valid_status_transition
from ai_job_finder.domain.scoring import evaluate_job_fit
from ai_job_finder.infrastructure.database.models import (
    CandidateProfileModel,
    CareerFactModel,
    JobEvaluationModel,
    JobLeadModel,
)


def _normalize_list(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        item = value.strip()
        if item and item not in normalized:
            normalized.append(item)
    return normalized


def _normalize_optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _ensure_single_active_candidate(session: Session) -> None:
    existing = get_current_candidate_profile(session)
    if existing is not None:
        msg = "Only one active candidate profile is supported in this slice."
        raise SingleCandidateViolationError(msg)


def create_candidate_profile(
    session: Session,
    *,
    full_name: str,
    preferred_locations: list[str],
    remote_preference: str,
    target_levels: list[str],
    target_functions: list[str],
) -> CandidateProfileModel:
    _ensure_single_active_candidate(session)
    candidate = CandidateProfileModel(
        id=new_uuid(),
        full_name=full_name.strip(),
        preferred_locations=_normalize_list(preferred_locations),
        remote_preference=remote_preference,
        target_levels=_normalize_list(target_levels),
        target_functions=_normalize_list(target_functions),
        is_active=True,
    )
    session.add(candidate)
    session.commit()
    session.refresh(candidate)
    return candidate


def get_candidate_profile(session: Session, candidate_profile_id: UUID) -> CandidateProfileModel:
    candidate = session.get(CandidateProfileModel, candidate_profile_id)
    if candidate is None:
        msg = f"Candidate profile {candidate_profile_id} was not found."
        raise NotFoundError(msg)
    return candidate


def get_current_candidate_profile(session: Session) -> CandidateProfileModel | None:
    return session.scalar(
        select(CandidateProfileModel)
        .where(CandidateProfileModel.is_active.is_(True))
        .order_by(CandidateProfileModel.created_at.asc())
    )


def update_candidate_profile(
    session: Session,
    *,
    candidate_profile_id: UUID,
    full_name: str,
    preferred_locations: list[str],
    remote_preference: str,
    target_levels: list[str],
    target_functions: list[str],
) -> CandidateProfileModel:
    candidate = get_candidate_profile(session, candidate_profile_id)
    candidate.full_name = full_name.strip()
    candidate.preferred_locations = _normalize_list(preferred_locations)
    candidate.remote_preference = remote_preference
    candidate.target_levels = _normalize_list(target_levels)
    candidate.target_functions = _normalize_list(target_functions)
    session.add(candidate)
    session.commit()
    session.refresh(candidate)
    return candidate


def create_career_fact(
    session: Session,
    *,
    candidate_profile_id: UUID,
    category: str,
    source_organization: str | None,
    statement: str,
    metric: str | None,
    technologies: list[str],
    leadership_scope: str | None,
    business_outcome: str | None,
    approved_wording: str,
    evidence_tags: list[str],
    provenance_type: str,
    source_reference: str,
) -> CareerFactModel:
    get_candidate_profile(session, candidate_profile_id)
    fact = CareerFactModel(
        id=new_uuid(),
        candidate_profile_id=candidate_profile_id,
        category=category,
        source_organization=_normalize_optional_str(source_organization),
        statement=statement.strip(),
        metric=_normalize_optional_str(metric),
        technologies=_normalize_list(technologies),
        leadership_scope=_normalize_optional_str(leadership_scope),
        business_outcome=_normalize_optional_str(business_outcome),
        approved_wording=approved_wording.strip(),
        lifecycle_status=CareerFactLifecycle.DRAFT.value,
        evidence_tags=_normalize_list(evidence_tags),
        provenance_type=provenance_type,
        source_reference=source_reference.strip(),
        verified_at=None,
        archived_at=None,
    )
    session.add(fact)
    session.commit()
    session.refresh(fact)
    return fact


def list_career_facts(
    session: Session,
    candidate_profile_id: UUID,
    *,
    lifecycle_status: str | None = None,
    category: str | None = None,
    source_organization: str | None = None,
    evidence_tag: str | None = None,
    include_archived: bool = False,
) -> list[CareerFactModel]:
    get_candidate_profile(session, candidate_profile_id)
    query = select(CareerFactModel).where(
        CareerFactModel.candidate_profile_id == candidate_profile_id
    )
    if lifecycle_status is not None:
        query = query.where(CareerFactModel.lifecycle_status == lifecycle_status)
    elif not include_archived:
        query = query.where(CareerFactModel.lifecycle_status != CareerFactLifecycle.ARCHIVED.value)
    if category is not None:
        query = query.where(CareerFactModel.category == category)
    if source_organization is not None:
        query = query.where(CareerFactModel.source_organization == source_organization)

    facts = list(
        session.scalars(
            query.order_by(
                CareerFactModel.updated_at.desc(),
                CareerFactModel.created_at.desc(),
            )
        )
    )
    if evidence_tag is not None:
        facts = [fact for fact in facts if evidence_tag in fact.evidence_tags]
    return facts


def get_primary_candidate_profile(session: Session) -> CandidateProfileModel | None:
    return get_current_candidate_profile(session)


def get_career_fact(session: Session, fact_id: UUID) -> CareerFactModel:
    fact = session.get(CareerFactModel, fact_id)
    if fact is None:
        msg = f"Career fact {fact_id} was not found."
        raise NotFoundError(msg)
    return fact


def update_career_fact(
    session: Session,
    *,
    fact_id: UUID,
    category: str,
    source_organization: str | None,
    statement: str,
    metric: str | None,
    technologies: list[str],
    leadership_scope: str | None,
    business_outcome: str | None,
    approved_wording: str,
    evidence_tags: list[str],
    provenance_type: str,
    source_reference: str,
) -> CareerFactModel:
    fact = get_career_fact(session, fact_id)
    if fact.lifecycle_status == CareerFactLifecycle.ARCHIVED.value:
        msg = "Archived career facts must be restored to draft before editing."
        raise ArchivedCareerFactModificationError(msg)

    next_values = {
        "category": category,
        "source_organization": _normalize_optional_str(source_organization),
        "statement": statement.strip(),
        "metric": _normalize_optional_str(metric),
        "technologies": _normalize_list(technologies),
        "leadership_scope": _normalize_optional_str(leadership_scope),
        "business_outcome": _normalize_optional_str(business_outcome),
        "approved_wording": approved_wording.strip(),
        "evidence_tags": _normalize_list(evidence_tags),
        "provenance_type": provenance_type,
        "source_reference": source_reference.strip(),
    }
    current_values = {
        "category": fact.category,
        "source_organization": fact.source_organization,
        "statement": fact.statement,
        "metric": fact.metric,
        "technologies": list(fact.technologies),
        "leadership_scope": fact.leadership_scope,
        "business_outcome": fact.business_outcome,
        "approved_wording": fact.approved_wording,
        "evidence_tags": list(fact.evidence_tags),
        "provenance_type": fact.provenance_type,
        "source_reference": fact.source_reference,
    }
    material_change = current_values != next_values

    for field_name, field_value in next_values.items():
        setattr(fact, field_name, field_value)

    if material_change and fact.lifecycle_status == CareerFactLifecycle.VERIFIED.value:
        fact.lifecycle_status = CareerFactLifecycle.DRAFT.value
        fact.verified_at = None
        fact.archived_at = None

    session.add(fact)
    session.commit()
    session.refresh(fact)
    return fact


def transition_career_fact(
    session: Session,
    *,
    fact_id: UUID,
    lifecycle_status: str,
) -> CareerFactModel:
    fact = get_career_fact(session, fact_id)
    target_status = CareerFactLifecycle(lifecycle_status)
    verified_at, archived_at = transition_metadata(
        CareerFactLifecycle(fact.lifecycle_status),
        target_status,
        changed_at=utc_now(),
        existing_verified_at=fact.verified_at,
    )
    fact.lifecycle_status = target_status.value
    fact.verified_at = verified_at
    fact.archived_at = archived_at
    session.add(fact)
    session.commit()
    session.refresh(fact)
    return fact


def retrieve_verified_evidence(
    session: Session,
    *,
    candidate_profile_id: UUID,
) -> list[CareerFactModel]:
    return list_career_facts(
        session,
        candidate_profile_id,
        lifecycle_status=CareerFactLifecycle.VERIFIED.value,
        include_archived=False,
    )


def create_job_lead(
    session: Session,
    *,
    source: str,
    source_url: str | None,
    external_id: str | None,
    company_name: str,
    title: str,
    location_text: str | None,
    workplace_type: str | None,
    description_raw: str,
    description_normalized: str | None,
    compensation_text: str | None,
) -> JobLeadModel:
    normalized_description = (description_normalized or description_raw).strip()
    job_lead = JobLeadModel(
        id=new_uuid(),
        source=source,
        source_url=source_url,
        external_id=external_id,
        company_name=company_name,
        title=title,
        location_text=location_text,
        workplace_type=workplace_type,
        description_raw=description_raw,
        description_normalized=normalized_description,
        compensation_text=compensation_text,
        discovered_at=utc_now(),
        posting_status=PostingStatus.DISCOVERED.value,
    )
    session.add(job_lead)
    session.commit()
    session.refresh(job_lead)
    return job_lead


def list_job_leads(session: Session, *, posting_status: str | None = None) -> list[JobLeadModel]:
    query = (
        select(JobLeadModel)
        .options(selectinload(JobLeadModel.evaluations))
        .order_by(JobLeadModel.discovered_at.desc(), JobLeadModel.created_at.desc())
    )
    if posting_status is not None:
        query = query.where(JobLeadModel.posting_status == posting_status)
    return list(session.scalars(query))


def get_job_lead(session: Session, job_lead_id: UUID) -> JobLeadModel:
    job_lead = session.get(JobLeadModel, job_lead_id)
    if job_lead is None:
        msg = f"Job lead {job_lead_id} was not found."
        raise NotFoundError(msg)
    return job_lead


def update_job_lead_status(session: Session, job_lead_id: UUID, status: str) -> JobLeadModel:
    job_lead = get_job_lead(session, job_lead_id)
    ensure_valid_status_transition(PostingStatus(job_lead.posting_status), PostingStatus(status))
    job_lead.posting_status = status
    job_lead.updated_at = utc_now()
    session.add(job_lead)
    session.commit()
    session.refresh(job_lead)
    return job_lead


def create_job_evaluation(
    session: Session, *, job_lead_id: UUID, candidate_profile_id: UUID
) -> JobEvaluationModel:
    candidate = get_candidate_profile(session, candidate_profile_id)
    job_lead = get_job_lead(session, job_lead_id)
    facts = retrieve_verified_evidence(session, candidate_profile_id=candidate_profile_id)
    fact_snapshots = [fact.to_snapshot() for fact in facts]
    verified_facts = [fact for fact in fact_snapshots if fact.is_usable]
    if not verified_facts:
        msg = "At least one verified career fact is required before creating an evaluation."
        raise EvaluationPreconditionError(msg)

    evaluation = evaluate_job_fit(candidate.to_snapshot(), job_lead.to_snapshot(), verified_facts)
    evaluation_model = JobEvaluationModel(
        id=evaluation.id,
        candidate_profile_id=evaluation.candidate_profile_id,
        job_lead_id=evaluation.job_lead_id,
        scoring_version=evaluation.scoring_version,
        leadership_scope_score=evaluation.leadership_scope_score,
        technical_alignment_score=evaluation.technical_alignment_score,
        location_score=evaluation.location_score,
        level_score=evaluation.level_score,
        platform_ownership_score=evaluation.platform_ownership_score,
        referral_priority_score=evaluation.referral_priority_score,
        overall_score=evaluation.overall_score,
        recommendation=evaluation.recommendation.value,
        explanation=evaluation.explanation,
        evaluated_at=evaluation.evaluated_at,
    )
    session.add(evaluation_model)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise
    session.refresh(evaluation_model)
    return evaluation_model


def get_latest_job_evaluation(session: Session, job_lead_id: UUID) -> JobEvaluationModel:
    get_job_lead(session, job_lead_id)
    evaluation = session.scalar(
        select(JobEvaluationModel)
        .where(JobEvaluationModel.job_lead_id == job_lead_id)
        .order_by(JobEvaluationModel.evaluated_at.desc())
    )
    if evaluation is None:
        msg = f"No evaluation exists for job lead {job_lead_id}."
        raise NotFoundError(msg)
    return evaluation
