from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC
from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ai_job_finder.domain.common import new_uuid, utc_now
from ai_job_finder.domain.enums import (
    JobImportRunStatus,
    JobLeadSource,
    JobLocationEligibilityStatus,
    JobSourceProvider,
    SourcePostingStatus,
    WorkplaceType,
)
from ai_job_finder.domain.errors import (
    DuplicateJobSourceError,
    InvalidJobSourceError,
    JobSourceDisabledError,
    JobSourceProviderError,
    MissingCandidateError,
    NotFoundError,
    OverlappingJobImportError,
    SuspiciousEmptyJobSourceResultError,
)
from ai_job_finder.domain.job_sources import (
    JobSourceConnector,
    JobSourceItemFailure,
    NormalizedJobPosting,
)
from ai_job_finder.domain.location_eligibility import (
    JobLocationEligibilityResult,
    JobLocationSignals,
    classify_job_location_eligibility,
)
from ai_job_finder.domain.scoring import evaluate_job_fit
from ai_job_finder.infrastructure.database.models import (
    CandidateProfileModel,
    CareerFactModel,
    JobEvaluationModel,
    JobImportRunModel,
    JobLeadModel,
    JobSourceConfigurationModel,
    JobSourceObservationModel,
)


@dataclass(frozen=True, slots=True)
class RankedDiscoveredLead:
    job: JobLeadModel
    observation: JobSourceObservationModel
    latest_evaluation: JobEvaluationModel | None
    location_eligibility: JobLocationEligibilityResult


def _normalize_optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _sha256_json(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalize_for_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def _normalized_payload(job: NormalizedJobPosting) -> dict[str, Any]:
    return {
        "provider": job.provider.value,
        "company_name": job.company_name.strip(),
        "title": job.title.strip(),
        "location_text": _normalize_optional_str(job.location_text),
        "workplace_type": job.workplace_type.value if job.workplace_type else None,
        "description_raw": job.description_raw.strip(),
        "description_normalized": job.description_normalized.strip(),
        "compensation_text": _normalize_optional_str(job.compensation_text),
        "source_url": _normalize_optional_str(job.source_url),
        "external_id": job.external_id.strip(),
        "internal_job_id": _normalize_optional_str(job.internal_job_id),
        "source_updated_at": job.source_updated_at.isoformat() if job.source_updated_at else None,
        "departments": sorted(job.departments),
        "offices": sorted(job.offices),
        "metadata": job.metadata,
        "posting_status": job.posting_status,
    }


def _stored_normalized_payload(job: NormalizedJobPosting) -> dict[str, Any]:
    payload = _normalized_payload(job)
    description_normalized = payload.pop("description_normalized")
    payload.pop("description_raw")
    payload["description_normalized_sha256"] = hashlib.sha256(
        description_normalized.encode("utf-8")
    ).hexdigest()
    payload["description_normalized_length"] = len(description_normalized)
    return payload


def _scoring_payload(job: NormalizedJobPosting) -> dict[str, Any]:
    return {
        "company_name": job.company_name.strip(),
        "title": job.title.strip(),
        "location_text": _normalize_optional_str(job.location_text),
        "workplace_type": job.workplace_type.value if job.workplace_type else None,
        "description_normalized": job.description_normalized.strip(),
        "compensation_text": _normalize_optional_str(job.compensation_text),
    }


def duplicate_hint_key(job: NormalizedJobPosting) -> str:
    payload = {
        "company": _normalize_for_key(job.company_name),
        "title": _normalize_for_key(job.title),
        "location": _normalize_for_key(job.location_text),
        "url": _normalize_for_key(job.source_url),
        "description": hashlib.sha256(
            _normalize_for_key(job.description_normalized).encode("utf-8")
        ).hexdigest(),
        "internal_job_id": _normalize_for_key(job.internal_job_id),
    }
    return _sha256_json(payload)


def create_job_source_configuration(
    session: Session,
    *,
    provider: str,
    display_name: str,
    company_name: str,
    board_token: str,
    source_url: str | None,
    enabled: bool = True,
) -> JobSourceConfigurationModel:
    source = JobSourceConfigurationModel(
        id=new_uuid(),
        provider=JobSourceProvider(provider).value,
        display_name=display_name.strip(),
        company_name=company_name.strip(),
        board_token=board_token.strip(),
        source_url=_normalize_optional_str(source_url),
        enabled=enabled,
    )
    session.add(source)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateJobSourceError(
            "A source with this provider and board token already exists."
        ) from exc
    session.refresh(source)
    return source


def list_job_source_configurations(session: Session) -> list[JobSourceConfigurationModel]:
    return list(
        session.scalars(
            select(JobSourceConfigurationModel).order_by(
                JobSourceConfigurationModel.created_at.desc()
            )
        )
    )


def get_job_source_configuration(session: Session, source_id: UUID) -> JobSourceConfigurationModel:
    source = session.get(JobSourceConfigurationModel, source_id)
    if source is None:
        raise NotFoundError(f"Job source {source_id} was not found.")
    return source


def update_job_source_configuration(
    session: Session,
    *,
    source_id: UUID,
    display_name: str,
    company_name: str,
    board_token: str,
    source_url: str | None,
) -> JobSourceConfigurationModel:
    source = get_job_source_configuration(session, source_id)
    source.display_name = display_name.strip()
    source.company_name = company_name.strip()
    source.board_token = board_token.strip()
    source.source_url = _normalize_optional_str(source_url)
    session.add(source)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateJobSourceError(
            "A source with this provider and board token already exists."
        ) from exc
    session.refresh(source)
    return source


def set_job_source_enabled(
    session: Session,
    *,
    source_id: UUID,
    enabled: bool,
) -> JobSourceConfigurationModel:
    source = get_job_source_configuration(session, source_id)
    source.enabled = enabled
    session.add(source)
    session.commit()
    session.refresh(source)
    return source


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


def _location_signals_for_observation(
    job: JobLeadModel,
    observation: JobSourceObservationModel,
) -> JobLocationSignals:
    payload = observation.normalized_payload or {}
    offices = payload.get("offices")
    metadata = payload.get("metadata")
    return JobLocationSignals(
        location_text=job.location_text,
        workplace_type=WorkplaceType(job.workplace_type) if job.workplace_type else None,
        offices=[str(value) for value in offices if isinstance(value, str)]
        if isinstance(offices, list)
        else [],
        metadata=metadata if isinstance(metadata, dict) else {},
    )


def _latest_evaluation_subquery() -> Select[tuple[UUID, Any]]:
    return select(
        JobEvaluationModel.job_lead_id,
        func.max(JobEvaluationModel.evaluated_at).label("latest_evaluated_at"),
    ).group_by(JobEvaluationModel.job_lead_id)


def _apply_job_fields(job_lead: JobLeadModel, posting: NormalizedJobPosting) -> None:
    job_lead.source_url = _normalize_optional_str(posting.source_url)
    job_lead.company_name = posting.company_name.strip()
    job_lead.title = posting.title.strip()
    job_lead.location_text = _normalize_optional_str(posting.location_text)
    job_lead.workplace_type = posting.workplace_type.value if posting.workplace_type else None
    job_lead.description_raw = posting.description_raw.strip()
    job_lead.description_normalized = posting.description_normalized.strip()
    job_lead.compensation_text = _normalize_optional_str(posting.compensation_text)
    job_lead.source_posting_status = SourcePostingStatus.OPEN.value


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
    run.error_message = _normalize_optional_str(error_message)
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


def _upsert_observed_job(
    session: Session,
    *,
    source: JobSourceConfigurationModel,
    posting: NormalizedJobPosting,
    observed_at: Any,
    retain_raw_payload: bool,
) -> tuple[JobSourceObservationModel, bool, bool, bool]:
    normalized_payload = _normalized_payload(posting)
    payload_checksum = _sha256_json(normalized_payload)
    scoring_checksum = _sha256_json(_scoring_payload(posting))
    stored_payload = _stored_normalized_payload(posting)
    observation = session.scalar(
        select(JobSourceObservationModel)
        .options(selectinload(JobSourceObservationModel.job_lead))
        .where(
            JobSourceObservationModel.source_configuration_id == source.id,
            JobSourceObservationModel.provider == source.provider,
            JobSourceObservationModel.external_post_id == posting.external_id,
        )
    )
    created = observation is None
    scoring_change = created

    if observation is None:
        job_lead = JobLeadModel(
            id=new_uuid(),
            source=JobLeadSource.GREENHOUSE.value,
            source_url=_normalize_optional_str(posting.source_url),
            external_id=f"{source.id}:{posting.external_id}",
            company_name=posting.company_name.strip(),
            title=posting.title.strip(),
            location_text=_normalize_optional_str(posting.location_text),
            workplace_type=posting.workplace_type.value if posting.workplace_type else None,
            description_raw=posting.description_raw.strip(),
            description_normalized=posting.description_normalized.strip(),
            compensation_text=_normalize_optional_str(posting.compensation_text),
            discovered_at=observed_at,
            source_posting_status=SourcePostingStatus.OPEN.value,
        )
        session.add(job_lead)
        session.flush()
        observation = JobSourceObservationModel(
            id=new_uuid(),
            source_configuration_id=source.id,
            job_lead_id=job_lead.id,
            provider=source.provider,
            external_post_id=posting.external_id,
            external_internal_job_id=_normalize_optional_str(posting.internal_job_id),
            canonical_url=_normalize_optional_str(posting.source_url),
            first_seen_at=observed_at,
            last_seen_at=observed_at,
            source_updated_at=posting.source_updated_at,
            active=True,
            removed_at=None,
            payload_checksum=payload_checksum,
            scoring_checksum=scoring_checksum,
            duplicate_hint_key=duplicate_hint_key(posting),
            normalized_payload=stored_payload,
            raw_payload=posting.raw_payload if retain_raw_payload else None,
        )
        session.add(observation)
        session.flush()
        return observation, created, True, True

    scoring_change = observation.scoring_checksum != scoring_checksum
    payload_changed = observation.payload_checksum != payload_checksum
    reactivated = not observation.active
    observation.last_seen_at = observed_at
    observation.source_updated_at = posting.source_updated_at
    observation.active = True
    observation.removed_at = None
    observation.external_internal_job_id = _normalize_optional_str(posting.internal_job_id)
    observation.canonical_url = _normalize_optional_str(posting.source_url)
    observation.payload_checksum = payload_checksum
    observation.scoring_checksum = scoring_checksum
    observation.duplicate_hint_key = duplicate_hint_key(posting)
    observation.normalized_payload = stored_payload
    observation.raw_payload = posting.raw_payload if retain_raw_payload else None
    _apply_job_fields(observation.job_lead, posting)
    session.add(observation)
    session.add(observation.job_lead)
    return observation, created, payload_changed or reactivated, scoring_change


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


def _append_error(existing: str | None, message: str) -> str:
    suffix = "... [truncated]"
    if not existing:
        return message if len(message) <= 1000 else f"{message[: 1000 - len(suffix)]}{suffix}"
    combined = f"{existing}\n{message}"
    if len(combined) <= 1000:
        return combined
    return f"{combined[: 1000 - len(suffix)]}{suffix}"


def _active_observation_count(session: Session, source_id: UUID) -> int:
    return (
        session.scalar(
            select(func.count(JobSourceObservationModel.id)).where(
                JobSourceObservationModel.source_configuration_id == source_id,
                JobSourceObservationModel.active.is_(True),
            )
        )
        or 0
    )


def _close_missing_observations(
    session: Session,
    *,
    source_id: UUID,
    seen_external_ids: set[str],
    removed_at: Any,
) -> int:
    observations = list(
        session.scalars(
            select(JobSourceObservationModel)
            .options(selectinload(JobSourceObservationModel.job_lead))
            .where(
                JobSourceObservationModel.source_configuration_id == source_id,
                JobSourceObservationModel.active.is_(True),
                JobSourceObservationModel.external_post_id.not_in(seen_external_ids),
            )
        )
    )
    for observation in observations:
        observation.active = False
        observation.removed_at = removed_at
        observation.job_lead.source_posting_status = SourcePostingStatus.CLOSED.value
        session.add(observation)
        session.add(observation.job_lead)
    return len(observations)


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


def list_ranked_discovered_leads(
    session: Session,
    *,
    source_id: UUID | None = None,
    company: str | None = None,
    source_posting_status: str | None = None,
    workflow_status: str | None = None,
    recommendation: str | None = None,
    minimum_score: float | None = None,
    location: str | None = None,
    workplace_type: str | None = None,
    location_eligibility: JobLocationEligibilityStatus | None = None,
    include_ineligible: bool = False,
) -> list[RankedDiscoveredLead]:
    candidate = _current_candidate(session)
    latest = _latest_evaluation_subquery().subquery()
    query = (
        select(JobSourceObservationModel, JobLeadModel, JobEvaluationModel)
        .join(JobLeadModel, JobLeadModel.id == JobSourceObservationModel.job_lead_id)
        .outerjoin(
            latest,
            latest.c.job_lead_id == JobLeadModel.id,
        )
        .outerjoin(
            JobEvaluationModel,
            and_(
                JobEvaluationModel.job_lead_id == JobLeadModel.id,
                JobEvaluationModel.evaluated_at == latest.c.latest_evaluated_at,
            ),
        )
        .where(JobSourceObservationModel.active.is_(True))
    )
    if source_id is not None:
        query = query.where(JobSourceObservationModel.source_configuration_id == source_id)
    if company:
        query = query.where(JobLeadModel.company_name.ilike(f"%{company}%"))
    if source_posting_status:
        query = query.where(JobLeadModel.source_posting_status == source_posting_status)
    if workflow_status:
        query = query.where(JobLeadModel.posting_status == workflow_status)
    if recommendation:
        query = query.where(JobEvaluationModel.recommendation == recommendation)
    if minimum_score is not None:
        query = query.where(JobEvaluationModel.overall_score >= minimum_score)
    if location:
        query = query.where(JobLeadModel.location_text.ilike(f"%{location}%"))
    if workplace_type:
        query = query.where(JobLeadModel.workplace_type == workplace_type)

    rows = session.execute(query).all()
    items: list[RankedDiscoveredLead] = []
    for observation, job, evaluation in rows:
        eligibility = classify_job_location_eligibility(
            candidate.to_snapshot(),
            _location_signals_for_observation(job, observation),
        )
        if location_eligibility is not None and eligibility.status is not location_eligibility:
            continue
        if (
            location_eligibility is None
            and not include_ineligible
            and eligibility.status is JobLocationEligibilityStatus.INELIGIBLE
        ):
            continue
        items.append(
            RankedDiscoveredLead(
                job=job,
                observation=observation,
                latest_evaluation=evaluation,
                location_eligibility=eligibility,
            )
        )
    return sorted(
        items,
        key=lambda item: (
            item.job.posting_status not in {"rejected", "closed"},
            item.latest_evaluation.overall_score if item.latest_evaluation else -1,
            item.observation.source_updated_at or item.observation.last_seen_at,
            item.observation.first_seen_at,
            str(item.job.id),
        ),
        reverse=True,
    )
