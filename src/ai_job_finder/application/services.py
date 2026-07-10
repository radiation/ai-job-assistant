from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ai_job_finder.domain.common import new_uuid, utc_now
from ai_job_finder.domain.enums import PostingStatus
from ai_job_finder.domain.errors import EvaluationPreconditionError, NotFoundError
from ai_job_finder.domain.job_lead import ensure_valid_status_transition
from ai_job_finder.domain.scoring import evaluate_job_fit
from ai_job_finder.infrastructure.database.models import (
    CandidateProfileModel,
    CareerFactModel,
    JobEvaluationModel,
    JobLeadModel,
)


def create_candidate_profile(
    session: Session,
    *,
    full_name: str,
    preferred_locations: list[str],
    remote_preference: str,
    target_levels: list[str],
    target_functions: list[str],
) -> CandidateProfileModel:
    candidate = CandidateProfileModel(
        id=new_uuid(),
        full_name=full_name,
        preferred_locations=preferred_locations,
        remote_preference=remote_preference,
        target_levels=target_levels,
        target_functions=target_functions,
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
    verification_status: str,
    source_reference: str,
) -> CareerFactModel:
    get_candidate_profile(session, candidate_profile_id)
    fact = CareerFactModel(
        id=new_uuid(),
        candidate_profile_id=candidate_profile_id,
        category=category,
        source_organization=source_organization,
        statement=statement,
        metric=metric,
        technologies=technologies,
        leadership_scope=leadership_scope,
        business_outcome=business_outcome,
        approved_wording=approved_wording,
        verification_status=verification_status,
        source_reference=source_reference,
    )
    session.add(fact)
    session.commit()
    session.refresh(fact)
    return fact


def list_career_facts(session: Session, candidate_profile_id: UUID) -> list[CareerFactModel]:
    get_candidate_profile(session, candidate_profile_id)
    return list(
        session.scalars(
            select(CareerFactModel)
            .where(CareerFactModel.candidate_profile_id == candidate_profile_id)
            .order_by(CareerFactModel.created_at.asc())
        )
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
    description_normalized: str,
    compensation_text: str | None,
) -> JobLeadModel:
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
        description_normalized=description_normalized,
        compensation_text=compensation_text,
        discovered_at=utc_now(),
        posting_status=PostingStatus.DISCOVERED.value,
    )
    session.add(job_lead)
    session.commit()
    session.refresh(job_lead)
    return job_lead


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
    facts = list_career_facts(session, candidate_profile_id)
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
