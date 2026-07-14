from __future__ import annotations

from datetime import UTC
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ai_job_finder.application.job_sources.configurations import get_job_source_configuration
from ai_job_finder.application.job_sources.observations import (
    _active_observation_count,
    _close_missing_observations,
    _upsert_observed_job,
)
from ai_job_finder.domain.common import new_uuid, utc_now
from ai_job_finder.domain.enums import JobImportRunStatus
from ai_job_finder.domain.errors import (
    InvalidJobSourceError,
    JobSourceDisabledError,
    JobSourceProviderError,
    MissingCandidateError,
    NotFoundError,
    OverlappingJobImportError,
    SuspiciousEmptyJobSourceResultError,
)
from ai_job_finder.domain.job_sources import JobSourceConnector, JobSourceItemFailure
from ai_job_finder.domain.scoring import evaluate_job_fit
from ai_job_finder.infrastructure.database.models import (
    CandidateProfileModel,
    CareerFactModel,
    JobEvaluationModel,
    JobImportRunModel,
    JobLeadModel,
    JobSourceConfigurationModel,
)


def _running_import_for_source(session: Session, source_id: UUID) -> JobImportRunModel | None:
    return session.scalar(
        select(JobImportRunModel)
        .where(
            JobImportRunModel.source_configuration_id == source_id,
            JobImportRunModel.status == JobImportRunStatus.RUNNING.value,
        )
        .order_by(JobImportRunModel.started_at.desc())
    )


def _current_candidate(session: Session) -> CandidateProfileModel:
    candidate = session.scalar(
        select(CandidateProfileModel)
        .where(CandidateProfileModel.is_active.is_(True))
        .order_by(CandidateProfileModel.created_at.asc())
    )
    if candidate is None:
        raise MissingCandidateError("Create a candidate profile before importing job sources.")
    return candidate


def _verified_facts(session: Session, candidate_id: UUID) -> list[CareerFactModel]:
    return list(
        session.scalars(
            select(CareerFactModel).where(
                CareerFactModel.candidate_profile_id == candidate_id,
                CareerFactModel.lifecycle_status == "verified",
                CareerFactModel.archived_at.is_(None),
            )
        )
    )


def _create_evaluation(
    session: Session,
    *,
    candidate: CandidateProfileModel,
    job_lead: JobLeadModel,
) -> JobEvaluationModel:
    facts = _verified_facts(session, candidate.id)
    evaluation = evaluate_job_fit(
        candidate.to_snapshot(),
        job_lead.to_snapshot(),
        [fact.to_snapshot() for fact in facts if fact.to_snapshot().is_usable],
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
    return evaluation_model


def _append_error(existing: str | None, message: str) -> str:
    suffix = "... [truncated]"
    if not existing:
        return message if len(message) <= 1000 else f"{message[: 1000 - len(suffix)]}{suffix}"
    combined = f"{existing}\n{message}"
    if len(combined) <= 1000:
        return combined
    return f"{combined[: 1000 - len(suffix)]}{suffix}"


def _safe_error_message(exc: Exception, *, context: str) -> str:
    if isinstance(
        exc,
        (InvalidJobSourceError, JobSourceDisabledError, JobSourceProviderError, NotFoundError),
    ):
        return _append_error(None, f"{context}: {exc}")
    if isinstance(exc, MissingCandidateError):
        return _append_error(None, f"{context}: {exc}")
    if isinstance(exc, IntegrityError):
        return _append_error(None, f"{context}: database constraint violation")
    return _append_error(None, context)


def _create_running_import_run(
    session: Session,
    *,
    source: JobSourceConfigurationModel,
) -> JobImportRunModel:
    run = JobImportRunModel(
        id=new_uuid(),
        source_configuration_id=source.id,
        provider=source.provider,
        status=JobImportRunStatus.RUNNING.value,
        started_at=utc_now(),
        connector_version="unknown",
    )
    session.add(run)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise OverlappingJobImportError("An import is already running for this source.") from exc
    return run


def _overlap_message(run: JobImportRunModel, *, stale_after_seconds: int) -> str:
    message = "An import is already running for this source."
    if stale_after_seconds > 0:
        started_at = run.started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        age_seconds = max(int((utc_now() - started_at).total_seconds()), 0)
        if age_seconds >= stale_after_seconds:
            return (
                f"{message} The existing run started at {run.started_at.isoformat()} "
                f"and appears stale."
            )
    return message


def _record_item_failures(
    run: JobImportRunModel,
    *,
    failures: list[JobSourceItemFailure],
) -> None:
    for failure in failures:
        run.jobs_failed += 1
        identifier = failure.external_id or "unknown"
        run.error_message = _append_error(
            run.error_message,
            f"Import failed for source posting {identifier}: {failure.message}",
        )


def _persist_terminal_run_state(
    session: Session,
    *,
    run_id: UUID,
    source_id: UUID,
    status: JobImportRunStatus,
    error_message: str | None,
) -> JobImportRunModel:
    run = get_job_import_run(session, run_id)
    source = get_job_source_configuration(session, source_id)
    run.status = status.value
    run.completed_at = utc_now()
    run.error_message = error_message.strip() if error_message else None
    source.last_sync_status = run.status
    source.last_sync_error = run.error_message
    if status is JobImportRunStatus.SUCCEEDED:
        source.last_successful_sync_at = run.completed_at
    session.add_all([run, source])
    session.commit()
    session.refresh(run)
    return run


def _finalize_after_exception(
    session: Session,
    *,
    run_id: UUID,
    source_id: UUID,
    status: JobImportRunStatus,
    error_message: str,
    original_exc: Exception,
) -> JobImportRunModel:
    try:
        return _persist_terminal_run_state(
            session,
            run_id=run_id,
            source_id=source_id,
            status=status,
            error_message=error_message,
        )
    except Exception as persist_exc:
        session.rollback()
        original_exc.add_note(
            f"Failed to persist terminal import state: {persist_exc.__class__.__name__}"
        )
        raise original_exc from persist_exc


def run_job_source_import(
    session: Session,
    *,
    source_id: UUID,
    connector: JobSourceConnector,
    retain_raw_payload: bool = True,
    close_on_empty: bool = False,
    stale_after_seconds: int = 3600,
) -> JobImportRunModel:
    source = get_job_source_configuration(session, source_id)
    if not source.enabled:
        raise JobSourceDisabledError("Enable the job source before syncing it.")
    if (existing_run := _running_import_for_source(session, source_id)) is not None:
        raise OverlappingJobImportError(
            _overlap_message(existing_run, stale_after_seconds=stale_after_seconds)
        )

    candidate = _current_candidate(session)
    run = _create_running_import_run(session, source=source)

    seen_external_ids: set[str] = set()
    try:
        result = connector.fetch_jobs(source.to_snapshot())
        run.connector_version = result.connector_version
        run.jobs_fetched = len(result.jobs)
        _record_item_failures(run, failures=result.job_failures)
        active_count = _active_observation_count(session, source.id)
        empty_active_source = not result.jobs and active_count > 0
        if result.suspicious_empty or empty_active_source:
            raise SuspiciousEmptyJobSourceResultError(
                "Greenhouse returned an empty result for a source with active observations."
            )

        for posting in result.jobs:
            seen_external_ids.add(posting.external_id)
            try:
                with session.begin_nested():
                    observation, created, changed, scoring_change = _upsert_observed_job(
                        session,
                        source=source,
                        posting=posting,
                        observed_at=result.fetched_at,
                        retain_raw_payload=retain_raw_payload,
                    )
                if created:
                    run.jobs_created += 1
                elif changed:
                    run.jobs_updated += 1
                else:
                    run.jobs_unchanged += 1
                if created or scoring_change:
                    try:
                        with session.begin_nested():
                            _create_evaluation(
                                session,
                                candidate=candidate,
                                job_lead=observation.job_lead,
                            )
                            session.flush()
                        run.evaluations_created += 1
                    except Exception as exc:
                        run.evaluation_failures += 1
                        run.error_message = _append_error(
                            run.error_message,
                            _safe_error_message(
                                exc,
                                context=(
                                    f"Evaluation failed for source posting {posting.external_id}"
                                ),
                            ),
                        )
            except Exception as exc:
                run.jobs_failed += 1
                run.error_message = _append_error(
                    run.error_message,
                    _safe_error_message(
                        exc,
                        context=f"Import failed for source posting {posting.external_id}",
                    ),
                )

        terminal_status = (
            JobImportRunStatus.PARTIAL
            if run.jobs_failed or run.evaluation_failures
            else JobImportRunStatus.SUCCEEDED
        )
        if terminal_status is JobImportRunStatus.SUCCEEDED:
            run.jobs_closed = _close_missing_observations(
                session,
                source_id=source.id,
                seen_external_ids=seen_external_ids,
                removed_at=result.fetched_at,
            )
        return _persist_terminal_run_state(
            session,
            run_id=run.id,
            source_id=source.id,
            status=terminal_status,
            error_message=run.error_message,
        )
    except (JobSourceProviderError, SuspiciousEmptyJobSourceResultError) as exc:
        session.rollback()
        return _finalize_after_exception(
            session,
            run_id=run.id,
            source_id=source_id,
            status=(
                JobImportRunStatus.PARTIAL
                if isinstance(exc, SuspiciousEmptyJobSourceResultError)
                else JobImportRunStatus.FAILED
            ),
            error_message=_safe_error_message(exc, context="Source import failed"),
            original_exc=exc,
        )
    except Exception as exc:
        session.rollback()
        return _finalize_after_exception(
            session,
            run_id=run.id,
            source_id=source_id,
            status=JobImportRunStatus.FAILED,
            error_message=_safe_error_message(exc, context="Unexpected source import failure"),
            original_exc=exc,
        )


def get_job_import_run(session: Session, run_id: UUID) -> JobImportRunModel:
    run = session.get(JobImportRunModel, run_id)
    if run is None:
        raise NotFoundError(f"Job import run {run_id} was not found.")
    return run


def list_job_import_runs(
    session: Session,
    *,
    source_id: UUID | None = None,
) -> list[JobImportRunModel]:
    query = select(JobImportRunModel).order_by(JobImportRunModel.started_at.desc())
    if source_id is not None:
        query = query.where(JobImportRunModel.source_configuration_id == source_id)
    return list(session.scalars(query))
