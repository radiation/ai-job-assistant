from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import Select, and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from ai_job_finder.application.job_searches.definitions import get_job_search_definition
from ai_job_finder.application.services import (
    get_current_candidate_profile,
    retrieve_verified_evidence,
)
from ai_job_finder.domain.candidate import CareerFactSnapshot
from ai_job_finder.domain.common import new_uuid, utc_now
from ai_job_finder.domain.errors import (
    JobSearchDefinitionDisabledError,
    MissingCandidateError,
    NotFoundError,
)
from ai_job_finder.domain.evaluation import EvaluationResult
from ai_job_finder.domain.job_searches import (
    JobSearchLocationContext,
    JobSearchMatchResult,
    JobSearchRunStatus,
    evaluate_job_search_match,
)
from ai_job_finder.domain.scoring import DEFAULT_SCORING_VERSION, evaluate_job_fit
from ai_job_finder.infrastructure.database.models import (
    CandidateProfileModel,
    JobEvaluationModel,
    JobLeadModel,
    JobSearchDefinitionModel,
    JobSearchMatchModel,
    JobSearchRunModel,
    JobSourceObservationModel,
)


@dataclass(frozen=True, slots=True)
class JobSearchRunMatchRecord:
    match: JobSearchMatchModel
    job_lead: JobLeadModel
    evaluation: JobEvaluationModel | None


@dataclass(frozen=True, slots=True)
class RunEvidenceSnapshot:
    verified_facts: tuple[CareerFactSnapshot, ...]
    latest_fact_updated_at: datetime | None


def _latest_evaluation_subquery() -> Select[tuple[UUID, datetime]]:
    return select(
        JobEvaluationModel.job_lead_id,
        func.max(JobEvaluationModel.evaluated_at).label("latest_evaluated_at"),
    ).group_by(JobEvaluationModel.job_lead_id)


def _candidate_leads_query() -> Select[
    tuple[JobSourceObservationModel, JobLeadModel, JobEvaluationModel | None]
]:
    latest = _latest_evaluation_subquery().subquery()
    return cast(
        Select[tuple[JobSourceObservationModel, JobLeadModel, JobEvaluationModel | None]],
        select(JobSourceObservationModel, JobLeadModel, JobEvaluationModel)
        .join(JobLeadModel, JobLeadModel.id == JobSourceObservationModel.job_lead_id)
        .outerjoin(latest, latest.c.job_lead_id == JobLeadModel.id)
        .outerjoin(
            JobEvaluationModel,
            and_(
                JobEvaluationModel.job_lead_id == JobLeadModel.id,
                JobEvaluationModel.evaluated_at == latest.c.latest_evaluated_at,
            ),
        )
        .where(JobSourceObservationModel.active.is_(True))
        .order_by(JobLeadModel.created_at.asc(), JobLeadModel.id.asc()),
    )


def _create_running_run(
    session: Session,
    *,
    definition: JobSearchDefinitionModel,
) -> JobSearchRunModel:
    run = JobSearchRunModel(
        id=new_uuid(),
        search_definition_id=definition.id,
        status=JobSearchRunStatus.RUNNING.value,
        started_at=utc_now(),
    )
    session.add(run)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise IntegrityError(
            "A saved-search run is already in progress.",
            params=None,
            orig=exc,
        ) from exc
    return run


def _get_latest_evaluation(session: Session, job_lead_id: UUID) -> JobEvaluationModel | None:
    return session.scalar(
        select(JobEvaluationModel)
        .where(JobEvaluationModel.job_lead_id == job_lead_id)
        .order_by(JobEvaluationModel.evaluated_at.desc(), JobEvaluationModel.created_at.desc())
    )


def _should_create_new_evaluation(
    *,
    candidate_updated_at: datetime,
    job_updated_at: datetime,
    fact_updated_at: datetime | None,
    latest_evaluation: JobEvaluationModel | None,
) -> bool:
    if latest_evaluation is None:
        return True
    if latest_evaluation.scoring_version != DEFAULT_SCORING_VERSION:
        return True
    if latest_evaluation.evaluated_at < candidate_updated_at:
        return True
    if latest_evaluation.evaluated_at < job_updated_at:
        return True
    if fact_updated_at is not None and latest_evaluation.evaluated_at < fact_updated_at:
        return True
    return False


def _materialize_evaluation(
    session: Session,
    *,
    candidate: CandidateProfileModel,
    job_lead: JobLeadModel,
    verified_facts: tuple[CareerFactSnapshot, ...],
) -> JobEvaluationModel:
    evaluation: EvaluationResult = evaluate_job_fit(
        candidate.to_snapshot(),
        job_lead.to_snapshot(),
        list(verified_facts),
    )
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
    session.flush()
    return evaluation_model


def _ensure_current_evaluation(
    session: Session,
    *,
    candidate: CandidateProfileModel,
    job_lead: JobLeadModel,
    evidence_snapshot: RunEvidenceSnapshot,
    latest_evaluation: JobEvaluationModel | None,
) -> tuple[JobEvaluationModel | None, bool]:
    if not _should_create_new_evaluation(
        candidate_updated_at=candidate.updated_at,
        job_updated_at=job_lead.updated_at,
        fact_updated_at=evidence_snapshot.latest_fact_updated_at,
        latest_evaluation=latest_evaluation,
    ):
        return latest_evaluation, False
    return (
        _materialize_evaluation(
            session,
            candidate=candidate,
            job_lead=job_lead,
            verified_facts=evidence_snapshot.verified_facts,
        ),
        True,
    )


def _load_run_evidence_snapshot(
    session: Session,
    *,
    candidate_profile_id: UUID,
) -> RunEvidenceSnapshot:
    facts = retrieve_verified_evidence(session, candidate_profile_id=candidate_profile_id)
    verified_facts = tuple(fact.to_snapshot() for fact in facts if fact.to_snapshot().is_usable)
    latest_fact_updated_at = max((fact.updated_at for fact in facts), default=None)
    return RunEvidenceSnapshot(
        verified_facts=verified_facts,
        latest_fact_updated_at=latest_fact_updated_at,
    )


def _location_context(
    observation: JobSourceObservationModel,
    job_lead: JobLeadModel,
) -> JobSearchLocationContext:
    payload = observation.normalized_payload or {}
    offices = payload.get("offices")
    metadata = payload.get("metadata")
    return JobSearchLocationContext(
        location_text=job_lead.location_text,
        workplace_type=(job_lead.to_snapshot().workplace_type if job_lead.workplace_type else None),
        offices=(
            [str(value) for value in offices if isinstance(value, str)]
            if isinstance(offices, list)
            else []
        ),
        metadata=metadata if isinstance(metadata, dict) else {},
    )


def _persist_match(
    session: Session,
    *,
    definition: JobSearchDefinitionModel,
    run: JobSearchRunModel,
    job_lead: JobLeadModel,
    evaluation: JobEvaluationModel | None,
    result: JobSearchMatchResult,
) -> None:
    session.add(
        JobSearchMatchModel(
            id=new_uuid(),
            search_definition_id=definition.id,
            search_run_id=run.id,
            job_lead_id=job_lead.id,
            job_evaluation_id=evaluation.id if evaluation else None,
            scoring_version=evaluation.scoring_version if evaluation else None,
            score_at_match_time=evaluation.overall_score if evaluation else None,
            recommendation_at_match_time=evaluation.recommendation if evaluation else None,
            criteria_matched=result.criteria_matched,
            above_threshold=result.above_threshold,
            matched=result.matched,
            matched_criteria=result.matched_criteria,
            exclusion_reasons=result.exclusion_reasons,
            inferred_domains=[domain.value for domain in result.inferred_domains],
            inferred_seniority_levels=[level.value for level in result.inferred_seniority_levels],
        )
    )


def _persist_terminal_run_state(
    session: Session,
    *,
    run_id: UUID,
    definition_id: UUID,
    status: JobSearchRunStatus,
    error_message: str | None,
) -> JobSearchRunModel:
    run = get_job_search_run(session, run_id)
    definition = get_job_search_definition(session, definition_id)
    run.status = status.value
    run.completed_at = utc_now()
    run.error_message = error_message.strip() if error_message else None
    definition.last_run_at = run.completed_at
    session.add_all([run, definition])
    session.commit()
    session.refresh(run)
    return run


def run_job_search(session: Session, *, search_definition_id: UUID) -> JobSearchRunModel:
    definition = get_job_search_definition(session, search_definition_id)
    if not definition.enabled:
        raise JobSearchDefinitionDisabledError(
            f"Saved search {definition.name} is disabled and cannot be run."
        )
    candidate = get_current_candidate_profile(session)
    if candidate is None:
        raise MissingCandidateError("Create a candidate profile before running saved searches.")
    evidence_snapshot = _load_run_evidence_snapshot(session, candidate_profile_id=candidate.id)
    run = _create_running_run(session, definition=definition)
    run_error: str | None = None
    try:
        rows = session.execute(_candidate_leads_query()).all()
        for observation, job_lead, latest_evaluation in rows:
            run.candidates_considered += 1
            try:
                with session.begin_nested():
                    evaluation = latest_evaluation
                    created = False
                    if evaluation is None or _should_create_new_evaluation(
                        candidate_updated_at=candidate.updated_at,
                        job_updated_at=job_lead.updated_at,
                        fact_updated_at=evidence_snapshot.latest_fact_updated_at,
                        latest_evaluation=evaluation,
                    ):
                        evaluation, created = _ensure_current_evaluation(
                            session,
                            candidate=candidate,
                            job_lead=job_lead,
                            evidence_snapshot=evidence_snapshot,
                            latest_evaluation=evaluation,
                        )
                    if evaluation is not None:
                        run.evaluated_count += 1
                    result = evaluate_job_search_match(
                        definition.to_snapshot(),
                        job_lead.to_snapshot(),
                        evaluation.to_snapshot() if evaluation is not None else None,
                        location_context=_location_context(observation, job_lead),
                    )
                    if result.criteria_matched:
                        run.matched_by_criteria += 1
                    if result.above_threshold:
                        run.above_threshold_count += 1
                    if not result.matched:
                        run.excluded_count += 1
                    _persist_match(
                        session,
                        definition=definition,
                        run=run,
                        job_lead=job_lead,
                        evaluation=evaluation,
                        result=result,
                    )
                    if created:
                        session.flush()
            except Exception as exc:
                run.failures_count += 1
                run.excluded_count += 1
                run_error = _append_error(
                    run_error,
                    f"Saved-search evaluation failed for {job_lead.id}: {exc}",
                )

        terminal_status = (
            JobSearchRunStatus.PARTIAL if run.failures_count else JobSearchRunStatus.COMPLETED
        )
        return _persist_terminal_run_state(
            session,
            run_id=run.id,
            definition_id=definition.id,
            status=terminal_status,
            error_message=run_error,
        )
    except Exception as exc:
        session.rollback()
        return _persist_terminal_run_state(
            session,
            run_id=run.id,
            definition_id=definition.id,
            status=JobSearchRunStatus.FAILED,
            error_message=_append_error(run_error, f"Saved-search run failed: {exc}"),
        )


def _append_error(existing: str | None, message: str) -> str:
    suffix = "... [truncated]"
    if not existing:
        return message if len(message) <= 1000 else f"{message[: 1000 - len(suffix)]}{suffix}"
    combined = f"{existing}\n{message}"
    if len(combined) <= 1000:
        return combined
    return f"{combined[: 1000 - len(suffix)]}{suffix}"


def get_job_search_run(session: Session, run_id: UUID) -> JobSearchRunModel:
    run = session.scalar(
        select(JobSearchRunModel)
        .options(selectinload(JobSearchRunModel.search_definition))
        .where(JobSearchRunModel.id == run_id)
    )
    if run is None:
        raise NotFoundError(f"Job search run {run_id} was not found.")
    return run


def list_job_search_runs(
    session: Session,
    *,
    search_definition_id: UUID | None = None,
) -> list[JobSearchRunModel]:
    query = (
        select(JobSearchRunModel)
        .options(selectinload(JobSearchRunModel.search_definition))
        .order_by(JobSearchRunModel.started_at.desc())
    )
    if search_definition_id is not None:
        query = query.where(JobSearchRunModel.search_definition_id == search_definition_id)
    return list(session.scalars(query))


def list_job_search_matches(
    session: Session,
    *,
    search_run_id: UUID,
    matched_only: bool = False,
) -> list[JobSearchRunMatchRecord]:
    get_job_search_run(session, search_run_id)
    query = (
        select(JobSearchMatchModel)
        .options(
            joinedload(JobSearchMatchModel.job_lead),
            joinedload(JobSearchMatchModel.job_evaluation),
        )
        .where(JobSearchMatchModel.search_run_id == search_run_id)
        .order_by(
            JobSearchMatchModel.matched.desc(),
            JobSearchMatchModel.score_at_match_time.desc().nullslast(),
            JobSearchMatchModel.created_at.asc(),
        )
    )
    if matched_only:
        query = query.where(JobSearchMatchModel.matched.is_(True))
    rows = list(session.scalars(query))
    return [
        JobSearchRunMatchRecord(
            match=row,
            job_lead=row.job_lead,
            evaluation=row.job_evaluation,
        )
        for row in rows
    ]
