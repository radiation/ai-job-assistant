from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from ai_job_finder.application.job_discovery.ports import JobDiscoveryProvider
from ai_job_finder.application.job_discovery.query_generation import generate_job_discovery_queries
from ai_job_finder.application.job_searches import (
    get_job_search_definition,
    list_job_search_matches,
    run_job_search,
)
from ai_job_finder.application.job_sources import run_job_source_import
from ai_job_finder.application.services import get_current_candidate_profile
from ai_job_finder.application.source_detection import (
    SourceDetectionConfig,
    approve_source_detection_run,
    create_source_detection_run,
)
from ai_job_finder.domain.common import new_uuid, utc_now
from ai_job_finder.domain.enums import JobImportRunStatus, SourceDetectionRunStatus
from ai_job_finder.domain.errors import (
    JobSearchDefinitionDisabledError,
    MissingCandidateError,
    NotFoundError,
    OverlappingJobDiscoveryRunError,
)
from ai_job_finder.domain.job_discovery import (
    DiscoveredJobCandidate,
    JobDiscoveryObservationStatus,
    JobDiscoveryQuery,
    JobDiscoveryQueryStatus,
    JobDiscoveryRunStatus,
    normalize_job_discovery_url,
)
from ai_job_finder.domain.job_sources import JobSourceConnector
from ai_job_finder.domain.source_detection import GreenhouseBoardValidator, PublicPageFetcher
from ai_job_finder.infrastructure.database.models import (
    JobDiscoveryObservationModel,
    JobDiscoveryQueryModel,
    JobDiscoveryRunModel,
    JobLeadModel,
    JobSearchMatchModel,
    JobSourceObservationModel,
)

MAX_ERROR_SUMMARY_LENGTH = 1000


@dataclass(frozen=True, slots=True)
class JobDiscoveryConfig:
    max_queries_per_run: int
    result_limit: int
    max_total_candidates: int
    source_detection: SourceDetectionConfig
    retain_raw_payload: bool
    close_on_empty: bool
    stale_after_seconds: int


@dataclass(frozen=True, slots=True)
class JobDiscoveryObservationRecord:
    observation: JobDiscoveryObservationModel
    imported_job_lead: JobLeadModel | None
    saved_search_match: JobSearchMatchModel | None


@dataclass(frozen=True, slots=True)
class _ReusableResolution:
    source_configuration_id: UUID
    source_detection_run_id: UUID | None
    source_detection_outcome: str | None


@dataclass(slots=True)
class _RunCounters:
    generated_query_count: int
    provider_result_count: int = 0
    unique_url_count: int = 0
    duplicate_count: int = 0
    detected_count: int = 0
    unsupported_count: int = 0
    ambiguous_count: int = 0
    imported_lead_count: int = 0
    evaluated_count: int = 0
    final_matched_count: int = 0
    failure_count: int = 0
    errors: str | None = None


def run_job_discovery(
    session: Session,
    *,
    search_definition_id: UUID,
    provider_name: str,
    provider: JobDiscoveryProvider,
    fetcher: PublicPageFetcher,
    validator: GreenhouseBoardValidator,
    connector: JobSourceConnector,
    config: JobDiscoveryConfig,
) -> JobDiscoveryRunModel:
    definition = get_job_search_definition(session, search_definition_id)
    if not definition.enabled:
        raise JobSearchDefinitionDisabledError(
            f"Saved search {definition.name} is disabled and cannot run discovery."
        )
    if get_current_candidate_profile(session) is None:
        raise MissingCandidateError("Create a candidate profile before running job discovery.")

    discovery_run = _create_running_run(
        session,
        search_definition_id=definition.id,
        provider_name=provider_name,
    )
    counters = _RunCounters(generated_query_count=0)

    try:
        generated_queries = generate_job_discovery_queries(
            definition.to_snapshot(),
            max_queries=config.max_queries_per_run,
            result_limit=config.result_limit,
        )
        query_records = _persist_query_records(
            session,
            discovery_run_id=discovery_run.id,
            provider_name=provider_name,
            generated_queries=generated_queries,
        )
        counters.generated_query_count = len(query_records)

        remaining_candidates = config.max_total_candidates
        for query, query_record in zip(generated_queries, query_records, strict=True):
            if remaining_candidates <= 0:
                break
            try:
                candidates = list(provider.search(query))[
                    : min(query.result_limit, remaining_candidates)
                ]
                query_record.status = JobDiscoveryQueryStatus.COMPLETED.value
                query_record.returned_result_count = len(candidates)
                query_record.error_message = None
                session.add(query_record)
                session.commit()
            except Exception as exc:
                query_record.status = JobDiscoveryQueryStatus.FAILED.value
                query_record.error_message = _append_error(None, str(exc))
                session.add(query_record)
                session.commit()
                counters.failure_count += 1
                counters.errors = _append_error(
                    counters.errors, f"Query {query_record.ordinal} failed: {exc}"
                )
                continue

            counters.provider_result_count += len(candidates)
            remaining_candidates -= len(candidates)
            for candidate in candidates:
                try:
                    normalized_url = normalize_job_discovery_url(candidate.discovered_url)
                except Exception as exc:
                    counters.failure_count += 1
                    counters.errors = _append_error(
                        counters.errors,
                        f"Candidate URL normalization failed for {candidate.discovered_url}: {exc}",
                    )
                    continue
                _, created = _upsert_discovery_observation(
                    session,
                    discovery_run_id=discovery_run.id,
                    query_record=query_record,
                    normalized_url=normalized_url,
                    candidate=candidate,
                )
                if created:
                    counters.unique_url_count += 1
                else:
                    counters.duplicate_count += 1

        observations = list_job_discovery_observations(session, discovery_run_id=discovery_run.id)
        for record in observations:
            _process_observation(
                session,
                observation=record.observation,
                fetcher=fetcher,
                validator=validator,
                connector=connector,
                config=config,
                counters=counters,
            )

        saved_search_run = run_job_search(session, search_definition_id=definition.id)
        matches = {
            record.match.job_lead_id: record.match
            for record in list_job_search_matches(session, search_run_id=saved_search_run.id)
        }
        for record in list_job_discovery_observations(session, discovery_run_id=discovery_run.id):
            if record.observation.imported_job_lead_id is None:
                continue
            match = matches.get(record.observation.imported_job_lead_id)
            if match is None:
                continue
            if match.job_evaluation_id is not None:
                counters.evaluated_count += 1
            if match.matched:
                counters.final_matched_count += 1

        terminal_status = _terminal_status(
            counters=counters,
            saved_search_run_status=saved_search_run.status,
        )
        return _persist_terminal_run_state(
            session,
            run_id=discovery_run.id,
            status=terminal_status,
            saved_search_run_id=saved_search_run.id,
            counters=counters,
        )
    except Exception as exc:
        session.rollback()
        counters.failure_count += 1
        counters.errors = _append_error(counters.errors, f"Job discovery failed: {exc}")
        return _persist_terminal_run_state(
            session,
            run_id=discovery_run.id,
            status=JobDiscoveryRunStatus.FAILED,
            saved_search_run_id=None,
            counters=counters,
        )


def _process_observation(
    session: Session,
    *,
    observation: JobDiscoveryObservationModel,
    fetcher: PublicPageFetcher,
    validator: GreenhouseBoardValidator,
    connector: JobSourceConnector,
    config: JobDiscoveryConfig,
    counters: _RunCounters,
) -> None:
    try:
        reused_resolution = _reusable_resolution(session, observation=observation)
        if reused_resolution is not None:
            observation.source_detection_run_id = reused_resolution.source_detection_run_id
            observation.source_detection_outcome = reused_resolution.source_detection_outcome
            observation.source_configuration_id = reused_resolution.source_configuration_id
            counters.detected_count += 1
            _import_detected_source(
                session,
                observation=observation,
                source_configuration_id=reused_resolution.source_configuration_id,
                connector=connector,
                config=config,
                counters=counters,
            )
            session.add(observation)
            session.commit()
            return

        detection_run = create_source_detection_run(
            session,
            company_name=observation.company_hint,
            input_url=observation.normalized_url,
            brand_alias=None,
            fetcher=fetcher,
            validator=validator,
            config=config.source_detection,
        )
        observation.source_detection_run_id = detection_run.id
        observation.source_detection_outcome = detection_run.status
        if detection_run.status == SourceDetectionRunStatus.DETECTED.value:
            counters.detected_count += 1
            approval = approve_source_detection_run(
                session,
                run_id=detection_run.id,
                selected_token=None,
                create_and_sync=True,
                connector=connector,
                retain_raw_payload=config.retain_raw_payload,
                close_on_empty=config.close_on_empty,
                stale_after_seconds=config.stale_after_seconds,
            )
            observation.source_detection_run_id = approval.run.id
            observation.source_detection_outcome = approval.run.status
            observation.source_configuration_id = approval.source.id
            observation.import_run_id = approval.import_run.id if approval.import_run else None
            _finalize_imported_observation(
                session,
                observation=observation,
                source_configuration_id=approval.source.id,
                import_status=approval.import_run.status if approval.import_run else None,
                counters=counters,
            )
        elif detection_run.status == SourceDetectionRunStatus.AMBIGUOUS.value:
            counters.ambiguous_count += 1
            observation.processing_status = JobDiscoveryObservationStatus.AMBIGUOUS.value
            observation.exclusion_reason = (
                "Source detection returned multiple supported candidates."
            )
        elif detection_run.status == SourceDetectionRunStatus.NOT_DETECTED.value:
            counters.unsupported_count += 1
            observation.processing_status = JobDiscoveryObservationStatus.UNSUPPORTED.value
            observation.exclusion_reason = "Source detection did not find a supported import path."
        else:
            counters.failure_count += 1
            observation.processing_status = JobDiscoveryObservationStatus.FAILED.value
            observation.exclusion_reason = detection_run.error_message or "Source detection failed."
        session.add(observation)
        session.commit()
    except Exception as exc:
        session.rollback()
        observation = session.get(JobDiscoveryObservationModel, observation.id) or observation
        observation.processing_status = JobDiscoveryObservationStatus.FAILED.value
        observation.exclusion_reason = _append_error(None, str(exc))
        session.add(observation)
        session.commit()
        counters.failure_count += 1
        counters.errors = _append_error(
            counters.errors,
            f"Processing failed for {observation.normalized_url}: {exc}",
        )


def _create_running_run(
    session: Session,
    *,
    search_definition_id: UUID,
    provider_name: str,
) -> JobDiscoveryRunModel:
    run = JobDiscoveryRunModel(
        id=new_uuid(),
        search_definition_id=search_definition_id,
        provider=provider_name,
        status=JobDiscoveryRunStatus.RUNNING.value,
        started_at=utc_now(),
    )
    session.add(run)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise OverlappingJobDiscoveryRunError(
            "A discovery run is already in progress for this saved search."
        ) from exc
    session.refresh(run)
    return run


def _persist_query_records(
    session: Session,
    *,
    discovery_run_id: UUID,
    provider_name: str,
    generated_queries: list[JobDiscoveryQuery],
) -> list[JobDiscoveryQueryModel]:
    records = [
        JobDiscoveryQueryModel(
            id=new_uuid(),
            discovery_run_id=discovery_run_id,
            stable_query_id=query.stable_query_id,
            ordinal=query.ordinal,
            provider=provider_name,
            status=JobDiscoveryQueryStatus.PENDING.value,
            query_text=query.rendered_query,
            title_phrase=_bounded_optional(query.title_phrase, 200) or "",
            target_domain=_bounded_optional(query.target_domain, 200),
            location_or_workplace_term=_bounded_optional(query.location_or_workplace_term, 200),
            requested_result_limit=query.result_limit,
        )
        for query in generated_queries
    ]
    session.add_all(records)
    session.commit()
    return records


def _upsert_discovery_observation(
    session: Session,
    *,
    discovery_run_id: UUID,
    query_record: JobDiscoveryQueryModel,
    normalized_url: str,
    candidate: DiscoveredJobCandidate,
) -> tuple[JobDiscoveryObservationModel, bool]:
    observation = session.scalar(
        select(JobDiscoveryObservationModel).where(
            JobDiscoveryObservationModel.discovery_run_id == discovery_run_id,
            JobDiscoveryObservationModel.normalized_url == normalized_url,
        )
    )
    if observation is not None:
        query_ordinals = list(observation.query_ordinals)
        if query_record.ordinal not in query_ordinals:
            query_ordinals.append(query_record.ordinal)
            observation.query_ordinals = sorted(query_ordinals)
        observation.rank = min(observation.rank, candidate.rank)
        session.add(observation)
        session.commit()
        session.refresh(observation)
        return observation, False

    observation = JobDiscoveryObservationModel(
        id=new_uuid(),
        discovery_run_id=discovery_run_id,
        primary_query_id=query_record.id,
        query_ordinals=[query_record.ordinal],
        provider=_bounded_optional(candidate.provider_name, 50) or query_record.provider,
        provider_result_id=_bounded_optional(candidate.provider_result_identifier, 200),
        discovered_url=_bounded_required(candidate.discovered_url, 500),
        normalized_url=_bounded_required(normalized_url, 500),
        title_hint=_bounded_optional(candidate.title_hint, 200),
        company_hint=_bounded_optional(candidate.company_hint, 200),
        location_hint=_bounded_optional(candidate.location_hint, 200),
        evidence_snippet=_bounded_optional(candidate.evidence_snippet, 1000),
        rank=max(candidate.rank, 0),
        processing_status=JobDiscoveryObservationStatus.PENDING.value,
        discovered_at=candidate.discovered_at,
        raw_evidence=dict(candidate.raw_evidence),
    )
    session.add(observation)
    session.commit()
    session.refresh(observation)
    return observation, True


def _reusable_resolution(
    session: Session,
    *,
    observation: JobDiscoveryObservationModel,
) -> _ReusableResolution | None:
    previous = session.scalar(
        select(JobDiscoveryObservationModel)
        .options(joinedload(JobDiscoveryObservationModel.source_detection_run))
        .where(
            JobDiscoveryObservationModel.normalized_url == observation.normalized_url,
            JobDiscoveryObservationModel.id != observation.id,
            JobDiscoveryObservationModel.source_configuration_id.is_not(None),
        )
        .order_by(JobDiscoveryObservationModel.created_at.desc())
    )
    if previous is None or previous.source_configuration_id is None:
        return None
    return _ReusableResolution(
        source_configuration_id=previous.source_configuration_id,
        source_detection_run_id=previous.source_detection_run_id,
        source_detection_outcome=previous.source_detection_outcome,
    )


def _import_detected_source(
    session: Session,
    *,
    observation: JobDiscoveryObservationModel,
    source_configuration_id: UUID,
    connector: JobSourceConnector,
    config: JobDiscoveryConfig,
    counters: _RunCounters,
) -> None:
    import_run = run_job_source_import(
        session,
        source_id=source_configuration_id,
        connector=connector,
        retain_raw_payload=config.retain_raw_payload,
        close_on_empty=config.close_on_empty,
        stale_after_seconds=config.stale_after_seconds,
    )
    observation.import_run_id = import_run.id
    _finalize_imported_observation(
        session,
        observation=observation,
        source_configuration_id=source_configuration_id,
        import_status=import_run.status,
        counters=counters,
    )


def _finalize_imported_observation(
    session: Session,
    *,
    observation: JobDiscoveryObservationModel,
    source_configuration_id: UUID,
    import_status: str | None,
    counters: _RunCounters,
) -> None:
    if import_status is not None and import_status != JobImportRunStatus.SUCCEEDED.value:
        counters.failure_count += 1
        counters.errors = _append_error(
            counters.errors,
            f"Import for {observation.normalized_url} finished with {import_status}.",
        )
    lead = _resolve_imported_job_lead(
        session,
        source_configuration_id=source_configuration_id,
        normalized_url=observation.normalized_url,
    )
    if lead is not None:
        observation.imported_job_lead_id = lead.id
        observation.processing_status = JobDiscoveryObservationStatus.IMPORTED.value
        observation.exclusion_reason = None
        counters.imported_lead_count += 1
        return
    observation.processing_status = JobDiscoveryObservationStatus.FAILED.value
    observation.exclusion_reason = (
        "Source import completed, but the discovered URL did not resolve "
        "to a specific imported lead."
    )
    counters.failure_count += 1


def _resolve_imported_job_lead(
    session: Session,
    *,
    source_configuration_id: UUID,
    normalized_url: str,
) -> JobLeadModel | None:
    observations = list(
        session.scalars(
            select(JobSourceObservationModel)
            .options(joinedload(JobSourceObservationModel.job_lead))
            .where(JobSourceObservationModel.source_configuration_id == source_configuration_id)
        )
    )
    for observation in observations:
        if observation.canonical_url is None:
            continue
        try:
            if normalize_job_discovery_url(observation.canonical_url) == normalized_url:
                return observation.job_lead
        except Exception:
            continue
    return None


def _terminal_status(
    *,
    counters: _RunCounters,
    saved_search_run_status: str,
) -> JobDiscoveryRunStatus:
    if saved_search_run_status == JobDiscoveryRunStatus.FAILED.value:
        return JobDiscoveryRunStatus.FAILED
    if counters.failure_count:
        return JobDiscoveryRunStatus.PARTIAL
    if counters.provider_result_count == 0 and counters.unique_url_count == 0:
        return JobDiscoveryRunStatus.FAILED
    return JobDiscoveryRunStatus.COMPLETED


def _persist_terminal_run_state(
    session: Session,
    *,
    run_id: UUID,
    status: JobDiscoveryRunStatus,
    saved_search_run_id: UUID | None,
    counters: _RunCounters,
) -> JobDiscoveryRunModel:
    run = get_job_discovery_run(session, run_id)
    run.status = status.value
    run.completed_at = utc_now()
    run.generated_query_count = counters.generated_query_count
    run.provider_result_count = counters.provider_result_count
    run.unique_url_count = counters.unique_url_count
    run.duplicate_count = counters.duplicate_count
    run.detected_count = counters.detected_count
    run.unsupported_count = counters.unsupported_count
    run.ambiguous_count = counters.ambiguous_count
    run.imported_lead_count = counters.imported_lead_count
    run.evaluated_count = counters.evaluated_count
    run.final_matched_count = counters.final_matched_count
    run.failure_count = counters.failure_count
    run.error_summary = counters.errors
    run.saved_search_run_id = saved_search_run_id
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def get_job_discovery_run(session: Session, run_id: UUID) -> JobDiscoveryRunModel:
    run = session.scalar(
        select(JobDiscoveryRunModel)
        .options(selectinload(JobDiscoveryRunModel.search_definition))
        .where(JobDiscoveryRunModel.id == run_id)
    )
    if run is None:
        raise NotFoundError(f"Job discovery run {run_id} was not found.")
    return run


def list_job_discovery_runs(
    session: Session,
    *,
    search_definition_id: UUID | None = None,
) -> list[JobDiscoveryRunModel]:
    query = (
        select(JobDiscoveryRunModel)
        .options(selectinload(JobDiscoveryRunModel.search_definition))
        .order_by(JobDiscoveryRunModel.started_at.desc())
    )
    if search_definition_id is not None:
        query = query.where(JobDiscoveryRunModel.search_definition_id == search_definition_id)
    return list(session.scalars(query))


def list_job_discovery_queries(
    session: Session,
    *,
    discovery_run_id: UUID,
) -> list[JobDiscoveryQueryModel]:
    get_job_discovery_run(session, discovery_run_id)
    return list(
        session.scalars(
            select(JobDiscoveryQueryModel)
            .where(JobDiscoveryQueryModel.discovery_run_id == discovery_run_id)
            .order_by(JobDiscoveryQueryModel.ordinal.asc())
        )
    )


def list_job_discovery_observations(
    session: Session,
    *,
    discovery_run_id: UUID,
) -> list[JobDiscoveryObservationRecord]:
    run = get_job_discovery_run(session, discovery_run_id)
    rows = list(
        session.scalars(
            select(JobDiscoveryObservationModel)
            .options(joinedload(JobDiscoveryObservationModel.imported_job_lead))
            .where(JobDiscoveryObservationModel.discovery_run_id == discovery_run_id)
        )
    )
    matches_by_job_lead_id: dict[UUID, JobSearchMatchModel] = {}
    if run.saved_search_run_id is not None:
        matches_by_job_lead_id = {
            record.match.job_lead_id: record.match
            for record in list_job_search_matches(session, search_run_id=run.saved_search_run_id)
        }
    records = [
        JobDiscoveryObservationRecord(
            observation=row,
            imported_job_lead=row.imported_job_lead,
            saved_search_match=(
                matches_by_job_lead_id.get(row.imported_job_lead_id)
                if row.imported_job_lead_id is not None
                else None
            ),
        )
        for row in rows
    ]
    return sorted(
        records,
        key=lambda item: (
            1 if item.saved_search_match and item.saved_search_match.matched else 0,
            item.saved_search_match.score_at_match_time if item.saved_search_match else -1.0,
            -item.observation.rank,
        ),
        reverse=True,
    )


def _bounded_required(value: str, limit: int) -> str:
    return value.strip()[:limit]


def _bounded_optional(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized[:limit] if normalized else None


def _append_error(existing: str | None, message: str) -> str:
    suffix = "... [truncated]"
    if not existing:
        return (
            message
            if len(message) <= MAX_ERROR_SUMMARY_LENGTH
            else message[: MAX_ERROR_SUMMARY_LENGTH - len(suffix)] + suffix
        )
    combined = f"{existing}\n{message}"
    if len(combined) <= MAX_ERROR_SUMMARY_LENGTH:
        return combined
    return combined[: MAX_ERROR_SUMMARY_LENGTH - len(suffix)] + suffix
