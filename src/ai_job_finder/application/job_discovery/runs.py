from __future__ import annotations

from dataclasses import dataclass
from typing import cast
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
from ai_job_finder.application.job_sources import run_job_source_import_with_result
from ai_job_finder.application.job_sources.discovery import list_ranked_discovered_leads
from ai_job_finder.application.services import get_current_candidate_profile
from ai_job_finder.application.source_detection import (
    SourceDetectionConfig,
    approve_source_detection_run,
    create_source_detection_run,
)
from ai_job_finder.domain.common import new_uuid, utc_now
from ai_job_finder.domain.enums import (
    JobImportRunStatus,
    JobLocationEligibilityStatus,
    Recommendation,
    SourceDetectionRunStatus,
    WorkplaceType,
)
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
from ai_job_finder.domain.job_discovery.targeting import (
    discovery_excluded_aggregator_domain,
    parse_supported_ats_url,
)
from ai_job_finder.domain.job_sources import JobSourceConnector
from ai_job_finder.domain.location_eligibility import (
    JobLocationSignals,
    classify_job_location_eligibility,
)
from ai_job_finder.domain.source_detection import (
    JobSourceBoardValidator,
    PublicPageFetcher,
)
from ai_job_finder.infrastructure.database.models import (
    CandidateProfileModel,
    JobDiscoveryObservationModel,
    JobDiscoveryQueryModel,
    JobDiscoveryRunModel,
    JobEvaluationModel,
    JobImportRunModel,
    JobLeadModel,
    JobSearchMatchModel,
    JobSourceConfigurationModel,
    JobSourceObservationModel,
    SourceDetectionRunModel,
)

MAX_ERROR_SUMMARY_LENGTH = 1000
MAX_TOP_MATCHES = 10
ACTIONABLE_RECOMMENDATIONS = {
    Recommendation.STRONG_RECOMMEND.value,
    Recommendation.RECOMMEND.value,
}


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
    source_detection_run: SourceDetectionRunModel | None = None
    source_configuration: JobSourceConfigurationModel | None = None
    import_run: JobImportRunModel | None = None
    previously_seen: bool = False
    reused_prior_resolution: bool = False
    source_created_in_run: bool = False
    source_reused_in_run: bool = False


@dataclass(frozen=True, slots=True)
class JobDiscoveryImportRecord:
    source_configuration: JobSourceConfigurationModel
    import_run: JobImportRunModel | None
    imported_during_run: bool
    source_created_in_run: bool
    source_reused_in_run: bool
    observation_count: int
    import_status: str | None
    failure_message: str | None


@dataclass(frozen=True, slots=True)
class JobDiscoveryMatchingSummary:
    seed_linked_canonical_jobs_evaluated: int
    additional_board_import_jobs_evaluated: int
    total_canonical_jobs_evaluated: int
    location_eligible_count: int
    location_needs_review_count: int
    location_ineligible_count: int
    saved_search_match_count: int
    actionable_match_count: int
    surfaced_in_discover_count: int


@dataclass(frozen=True, slots=True)
class JobDiscoveryMatchedJobRecord:
    observation: JobDiscoveryObservationModel
    job_lead: JobLeadModel
    saved_search_match: JobSearchMatchModel
    evaluation: JobEvaluationModel | None
    location_eligibility_status: JobLocationEligibilityStatus
    location_eligibility_summary: str
    surfaced_in_discover: bool


@dataclass(frozen=True, slots=True)
class JobDiscoveryRunDetail:
    run: JobDiscoveryRunModel
    queries: list[JobDiscoveryQueryModel]
    observations: list[JobDiscoveryObservationRecord]
    imports: list[JobDiscoveryImportRecord]
    matching_summary: JobDiscoveryMatchingSummary
    top_matches: list[JobDiscoveryMatchedJobRecord]
    discover_jobs: list[JobDiscoveryMatchedJobRecord]


@dataclass(slots=True)
class _ImportAggregation:
    source: JobSourceConfigurationModel
    import_run: JobImportRunModel | None
    source_created_in_run: bool
    source_reused_in_run: bool
    observation_count: int
    failure_messages: set[str]


@dataclass(frozen=True, slots=True)
class _ReusableResolution:
    source_configuration_id: UUID
    source_detection_run_id: UUID | None
    source_detection_outcome: str | None


@dataclass(frozen=True, slots=True)
class _CachedImportOutcome:
    import_run_id: UUID | None
    import_status: str | None
    created_job_lead_ids: tuple[UUID, ...] = ()
    surfaced_job_lead_ids: tuple[UUID, ...] = ()
    error_message: str | None = None


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
    board_validator: JobSourceBoardValidator,
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
    source_imports: dict[UUID, _CachedImportOutcome] = {}
    search_job_lead_ids: set[UUID] = set()

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
                board_validator=board_validator,
                connector=connector,
                config=config,
                counters=counters,
                source_imports=source_imports,
                search_job_lead_ids=search_job_lead_ids,
            )

        saved_search_run = run_job_search(
            session,
            search_definition_id=definition.id,
            job_lead_ids=search_job_lead_ids,
        )
        matches = {
            record.match.job_lead_id: record.match
            for record in list_job_search_matches(session, search_run_id=saved_search_run.id)
        }
        for match in matches.values():
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
    board_validator: JobSourceBoardValidator,
    connector: JobSourceConnector,
    config: JobDiscoveryConfig,
    counters: _RunCounters,
    source_imports: dict[UUID, _CachedImportOutcome],
    search_job_lead_ids: set[UUID],
) -> None:
    try:
        excluded_domain = discovery_excluded_aggregator_domain(observation.normalized_url)
        if excluded_domain is not None:
            counters.unsupported_count += 1
            observation.processing_status = JobDiscoveryObservationStatus.UNSUPPORTED.value
            observation.exclusion_reason = (
                f"Excluded known aggregator domain before source detection: {excluded_domain}."
            )
            session.add(observation)
            session.commit()
            return

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
                source_imports=source_imports,
                fanout_surfaced_jobs=False,
                search_job_lead_ids=search_job_lead_ids,
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
            board_validator=board_validator,
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
                create_and_sync=False,
                connector=connector,
                retain_raw_payload=config.retain_raw_payload,
                close_on_empty=config.close_on_empty,
                stale_after_seconds=config.stale_after_seconds,
            )
            observation.source_detection_run_id = approval.run.id
            observation.source_detection_outcome = approval.run.status
            observation.source_configuration_id = approval.source.id
            _import_detected_source(
                session,
                observation=observation,
                source_configuration_id=approval.source.id,
                connector=connector,
                config=config,
                counters=counters,
                source_imports=source_imports,
                fanout_surfaced_jobs=not approval.existing_source,
                search_job_lead_ids=search_job_lead_ids,
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
    source_imports: dict[UUID, _CachedImportOutcome],
    fanout_surfaced_jobs: bool,
    search_job_lead_ids: set[UUID],
) -> None:
    import_outcome = source_imports.get(source_configuration_id)
    if import_outcome is None:
        try:
            import_result = run_job_source_import_with_result(
                session,
                source_id=source_configuration_id,
                connector=connector,
                retain_raw_payload=config.retain_raw_payload,
                close_on_empty=config.close_on_empty,
                stale_after_seconds=config.stale_after_seconds,
            )
        except Exception as exc:
            counters.errors = _append_error(
                counters.errors,
                f"Import failed for {observation.normalized_url}: {exc}",
            )
            import_outcome = _CachedImportOutcome(
                import_run_id=None,
                import_status=None,
                error_message=str(exc),
            )
        else:
            import_outcome = _CachedImportOutcome(
                import_run_id=import_result.run.id,
                import_status=import_result.run.status,
                created_job_lead_ids=import_result.created_job_lead_ids,
                surfaced_job_lead_ids=import_result.surfaced_job_lead_ids,
            )
        source_imports[source_configuration_id] = import_outcome

    if fanout_surfaced_jobs:
        search_job_lead_ids.update(import_outcome.surfaced_job_lead_ids)
    else:
        search_job_lead_ids.update(import_outcome.created_job_lead_ids)

    observation.import_run_id = import_outcome.import_run_id
    if import_outcome.error_message is not None:
        observation.processing_status = JobDiscoveryObservationStatus.FAILED.value
        observation.exclusion_reason = _append_error(None, import_outcome.error_message)
        counters.failure_count += 1
        return

    _finalize_imported_observation(
        session,
        observation=observation,
        source_configuration_id=source_configuration_id,
        import_status=import_outcome.import_status,
        counters=counters,
        search_job_lead_ids=search_job_lead_ids,
    )


def _finalize_imported_observation(
    session: Session,
    *,
    observation: JobDiscoveryObservationModel,
    source_configuration_id: UUID,
    import_status: str | None,
    counters: _RunCounters,
    search_job_lead_ids: set[UUID],
) -> None:
    if import_status is not None and import_status != JobImportRunStatus.SUCCEEDED.value:
        counters.failure_count += 1
        counters.errors = _append_error(
            counters.errors,
            f"Import for {observation.normalized_url} finished with {import_status}.",
        )
        observation.processing_status = JobDiscoveryObservationStatus.FAILED.value
        observation.exclusion_reason = f"Source import finished with {import_status}."
        return
    lead = _resolve_imported_job_lead(
        session,
        source_configuration_id=source_configuration_id,
        normalized_url=observation.normalized_url,
        source_detection_run_id=observation.source_detection_run_id,
    )
    if lead is not None:
        observation.imported_job_lead_id = lead.id
        search_job_lead_ids.add(lead.id)
        observation.processing_status = JobDiscoveryObservationStatus.IMPORTED.value
        observation.exclusion_reason = None
        counters.imported_lead_count += 1
        return
    observation.processing_status = JobDiscoveryObservationStatus.DETECTED_SUPPORTED.value
    observation.exclusion_reason = (
        "Source import completed, but the seed did not reconcile to a currently imported lead."
    )


def _resolve_imported_job_lead(
    session: Session,
    *,
    source_configuration_id: UUID,
    normalized_url: str,
    source_detection_run_id: UUID | None = None,
) -> JobLeadModel | None:
    parsed_url = parse_supported_ats_url(normalized_url)
    source = session.get(JobSourceConfigurationModel, source_configuration_id)
    external_posting_id = parsed_url.external_posting_id if parsed_url is not None else None
    provider = parsed_url.provider.value if parsed_url is not None else None
    if source_detection_run_id is not None and source is not None:
        detection_run = session.get(SourceDetectionRunModel, source_detection_run_id)
        if detection_run is not None:
            for candidate in detection_run.candidate_tokens:
                if (
                    isinstance(candidate, dict)
                    and candidate.get("provider") == source.provider
                    and candidate.get("token") == source.board_token
                    and isinstance(candidate.get("selected_external_posting_id"), str)
                ):
                    external_posting_id = candidate["selected_external_posting_id"]
                    provider = source.provider
                    break
    if source is not None and provider == source.provider and external_posting_id is not None:
        observation = session.scalar(
            select(JobSourceObservationModel)
            .options(joinedload(JobSourceObservationModel.job_lead))
            .where(
                JobSourceObservationModel.source_configuration_id == source_configuration_id,
                JobSourceObservationModel.provider == provider,
                JobSourceObservationModel.external_post_id == external_posting_id,
            )
        )
        if observation is not None:
            return observation.job_lead
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
            .options(
                joinedload(JobDiscoveryObservationModel.imported_job_lead),
                joinedload(JobDiscoveryObservationModel.source_detection_run),
                joinedload(JobDiscoveryObservationModel.source_configuration),
                joinedload(JobDiscoveryObservationModel.import_run),
            )
            .where(JobDiscoveryObservationModel.discovery_run_id == discovery_run_id)
        )
    )
    previously_seen_urls = _previously_seen_urls(session, run_id=run.id, rows=rows)
    first_observation_ids_by_source = _first_observation_ids_by_source(rows)
    matches_by_job_lead_id: dict[UUID, JobSearchMatchModel] = {}
    if run.saved_search_run_id is not None:
        matches_by_job_lead_id = {
            record.match.job_lead_id: record.match
            for record in list_job_search_matches(session, search_run_id=run.saved_search_run_id)
        }
    records = [
        JobDiscoveryObservationRecord(
            observation=row,
            imported_job_lead=(
                row.imported_job_lead
                or (
                    session.get(JobLeadModel, row.imported_job_lead_id)
                    if row.imported_job_lead_id is not None
                    else None
                )
            ),
            saved_search_match=(
                matches_by_job_lead_id.get(row.imported_job_lead_id)
                if row.imported_job_lead_id is not None
                else None
            ),
            source_detection_run=(
                row.source_detection_run
                or (
                    session.get(SourceDetectionRunModel, row.source_detection_run_id)
                    if row.source_detection_run_id is not None
                    else None
                )
            ),
            source_configuration=(
                row.source_configuration
                or (
                    session.get(JobSourceConfigurationModel, row.source_configuration_id)
                    if row.source_configuration_id is not None
                    else None
                )
            ),
            import_run=(
                row.import_run
                or (
                    session.get(JobImportRunModel, row.import_run_id)
                    if row.import_run_id is not None
                    else None
                )
            ),
            previously_seen=row.normalized_url in previously_seen_urls,
            reused_prior_resolution=(
                row.source_detection_run is not None
                and row.source_detection_run.created_at < row.created_at
            ),
            source_created_in_run=_source_created_in_run(run=run, source=row.source_configuration),
            source_reused_in_run=(
                row.source_configuration_id is not None
                and first_observation_ids_by_source.get(row.source_configuration_id) != row.id
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


def get_job_discovery_run_detail(session: Session, run_id: UUID) -> JobDiscoveryRunDetail:
    run = get_job_discovery_run(session, run_id)
    queries = list_job_discovery_queries(session, discovery_run_id=run_id)
    observations = list_job_discovery_observations(session, discovery_run_id=run_id)
    imports = _summarize_imports(run=run, observations=observations)
    matching_summary, top_matches, discover_jobs = _build_matching_detail(
        session,
        run=run,
        observations=observations,
    )
    return JobDiscoveryRunDetail(
        run=run,
        queries=queries,
        observations=observations,
        imports=imports,
        matching_summary=matching_summary,
        top_matches=top_matches,
        discover_jobs=discover_jobs,
    )


def _previously_seen_urls(
    session: Session,
    *,
    run_id: UUID,
    rows: list[JobDiscoveryObservationModel],
) -> set[str]:
    urls = sorted({row.normalized_url for row in rows})
    if not urls:
        return set()
    return set(
        session.scalars(
            select(JobDiscoveryObservationModel.normalized_url)
            .where(
                JobDiscoveryObservationModel.discovery_run_id != run_id,
                JobDiscoveryObservationModel.normalized_url.in_(urls),
            )
            .distinct()
        )
    )


def _first_observation_ids_by_source(
    rows: list[JobDiscoveryObservationModel],
) -> dict[UUID, UUID]:
    first_ids: dict[UUID, UUID] = {}
    ordered_rows = sorted(rows, key=lambda row: (row.created_at, str(row.id)))
    for row in ordered_rows:
        if row.source_configuration_id is None:
            continue
        first_ids.setdefault(row.source_configuration_id, row.id)
    return first_ids


def _source_created_in_run(
    *,
    run: JobDiscoveryRunModel,
    source: JobSourceConfigurationModel | None,
) -> bool:
    if source is None:
        return False
    completed_at = run.completed_at or utc_now()
    return run.started_at <= source.created_at <= completed_at


def _summarize_imports(
    *,
    run: JobDiscoveryRunModel,
    observations: list[JobDiscoveryObservationRecord],
) -> list[JobDiscoveryImportRecord]:
    grouped: dict[UUID, _ImportAggregation] = {}
    for record in observations:
        source = record.source_configuration
        if source is None:
            continue
        grouped_record = grouped.setdefault(
            source.id,
            _ImportAggregation(
                source=source,
                import_run=record.import_run,
                source_created_in_run=record.source_created_in_run,
                source_reused_in_run=record.source_reused_in_run,
                observation_count=0,
                failure_messages=set(),
            ),
        )
        grouped_record.observation_count += 1
        grouped_record.source_created_in_run = (
            grouped_record.source_created_in_run or record.source_created_in_run
        )
        grouped_record.source_reused_in_run = (
            grouped_record.source_reused_in_run or record.source_reused_in_run
        )
        if grouped_record.import_run is None and record.import_run is not None:
            grouped_record.import_run = record.import_run
        if record.observation.exclusion_reason:
            grouped_record.failure_messages.add(record.observation.exclusion_reason)

    summaries = [
        _build_import_record(
            run=run,
            source=grouped_record.source,
            import_run=grouped_record.import_run,
            source_created_in_run=grouped_record.source_created_in_run,
            source_reused_in_run=grouped_record.source_reused_in_run,
            observation_count=grouped_record.observation_count,
            failure_messages=grouped_record.failure_messages,
        )
        for grouped_record in grouped.values()
    ]
    return sorted(
        summaries,
        key=lambda record: (
            record.source_configuration.company_name.casefold(),
            record.source_configuration.board_token.casefold(),
        ),
    )


def _build_import_record(
    *,
    run: JobDiscoveryRunModel,
    source: JobSourceConfigurationModel,
    import_run: JobImportRunModel | None,
    source_created_in_run: bool,
    source_reused_in_run: bool,
    observation_count: int,
    failure_messages: set[str],
) -> JobDiscoveryImportRecord:
    failure_message = import_run.error_message if import_run else None
    if failure_message is None and failure_messages:
        failure_message = "\n".join(sorted(failure_messages))
    import_status = import_run.status if import_run is not None else None
    if import_status is None and failure_message is not None:
        import_status = JobImportRunStatus.FAILED.value
    imported_during_run = import_run is not None or import_status == JobImportRunStatus.FAILED.value
    return JobDiscoveryImportRecord(
        source_configuration=source,
        import_run=import_run,
        imported_during_run=imported_during_run,
        source_created_in_run=source_created_in_run,
        source_reused_in_run=source_reused_in_run,
        observation_count=observation_count,
        import_status=import_status,
        failure_message=failure_message,
    )


def _build_matching_detail(
    session: Session,
    *,
    run: JobDiscoveryRunModel,
    observations: list[JobDiscoveryObservationRecord],
) -> tuple[
    JobDiscoveryMatchingSummary,
    list[JobDiscoveryMatchedJobRecord],
    list[JobDiscoveryMatchedJobRecord],
]:
    imported_records = [record for record in observations if record.imported_job_lead is not None]
    matches_by_job_id: dict[UUID, JobSearchMatchModel] = {}
    evaluations_by_job_id: dict[UUID, JobEvaluationModel | None] = {}
    if run.saved_search_run_id is not None:
        for match_record in list_job_search_matches(session, search_run_id=run.saved_search_run_id):
            matches_by_job_id[match_record.job_lead.id] = match_record.match
            evaluations_by_job_id[match_record.job_lead.id] = match_record.evaluation

    evaluated_job_ids = {
        match.job_lead_id
        for match in matches_by_job_id.values()
        if match.job_evaluation_id is not None
    }
    seed_linked_job_ids = {
        record.imported_job_lead.id
        for record in imported_records
        if record.imported_job_lead is not None and record.imported_job_lead.id in evaluated_job_ids
    }
    additional_board_import_job_ids = evaluated_job_ids - seed_linked_job_ids

    if not imported_records:
        empty_summary = JobDiscoveryMatchingSummary(
            seed_linked_canonical_jobs_evaluated=len(seed_linked_job_ids),
            additional_board_import_jobs_evaluated=len(additional_board_import_job_ids),
            total_canonical_jobs_evaluated=len(evaluated_job_ids),
            location_eligible_count=0,
            location_needs_review_count=0,
            location_ineligible_count=0,
            saved_search_match_count=0,
            actionable_match_count=0,
            surfaced_in_discover_count=0,
        )
        return empty_summary, [], []

    candidate = get_current_candidate_profile(session)
    source_observations_by_job_id = _source_observations_by_job_id(
        session,
        job_lead_ids=[
            record.imported_job_lead.id
            for record in imported_records
            if record.imported_job_lead is not None
        ],
    )
    location_summary_by_job_id: dict[UUID, tuple[JobLocationEligibilityStatus, str]] = {}
    eligible_count = 0
    needs_review_count = 0
    ineligible_count = 0
    for record in imported_records:
        job_lead = record.imported_job_lead
        if job_lead is None or job_lead.id in location_summary_by_job_id:
            continue
        status, summary = _location_summary_for_observation(
            candidate=candidate,
            source_observation=source_observations_by_job_id.get(job_lead.id),
            job_lead=job_lead,
        )
        location_summary_by_job_id[job_lead.id] = (status, summary)
        if status is JobLocationEligibilityStatus.ELIGIBLE:
            eligible_count += 1
        elif status is JobLocationEligibilityStatus.NEEDS_REVIEW:
            needs_review_count += 1
        else:
            ineligible_count += 1

    surfaced_job_ids: set[UUID] = set()
    surfaced_rows: dict[UUID, JobDiscoveryMatchedJobRecord] = {}
    if run.saved_search_run_id is not None and candidate is not None:
        for item in list_ranked_discovered_leads(
            session,
            search_definition_id=run.search_definition_id,
        ):
            if item.job.id not in location_summary_by_job_id:
                continue
            match = matches_by_job_id.get(item.job.id)
            if match is None or not match.matched:
                continue
            surfaced_job_ids.add(item.job.id)
            status, summary = location_summary_by_job_id[item.job.id]
            surfaced_rows[item.job.id] = JobDiscoveryMatchedJobRecord(
                observation=next(
                    record.observation
                    for record in imported_records
                    if record.imported_job_lead is not None
                    and record.imported_job_lead.id == item.job.id
                ),
                job_lead=item.job,
                saved_search_match=match,
                evaluation=evaluations_by_job_id.get(item.job.id),
                location_eligibility_status=status,
                location_eligibility_summary=summary,
                surfaced_in_discover=True,
            )

    matched_records: list[JobDiscoveryMatchedJobRecord] = []
    for record in imported_records:
        job_lead = record.imported_job_lead
        match = record.saved_search_match
        if job_lead is None or match is None or not match.matched:
            continue
        status, summary = location_summary_by_job_id[job_lead.id]
        matched_records.append(
            JobDiscoveryMatchedJobRecord(
                observation=record.observation,
                job_lead=job_lead,
                saved_search_match=match,
                evaluation=evaluations_by_job_id.get(job_lead.id),
                location_eligibility_status=status,
                location_eligibility_summary=summary,
                surfaced_in_discover=job_lead.id in surfaced_job_ids,
            )
        )

    matched_records.sort(
        key=lambda record: (
            record.saved_search_match.score_at_match_time or -1.0,
            record.job_lead.created_at,
        ),
        reverse=True,
    )
    discover_jobs = [
        surfaced_rows[job_id]
        for job_id in sorted(
            surfaced_rows,
            key=lambda job_id: (
                surfaced_rows[job_id].saved_search_match.score_at_match_time or -1.0,
                surfaced_rows[job_id].job_lead.created_at,
            ),
            reverse=True,
        )
    ]
    actionable_match_count = sum(
        1
        for record in matched_records
        if record.location_eligibility_status is not JobLocationEligibilityStatus.INELIGIBLE
        and record.saved_search_match.recommendation_at_match_time in ACTIONABLE_RECOMMENDATIONS
    )
    matching_summary = JobDiscoveryMatchingSummary(
        seed_linked_canonical_jobs_evaluated=len(seed_linked_job_ids),
        additional_board_import_jobs_evaluated=len(additional_board_import_job_ids),
        total_canonical_jobs_evaluated=len(evaluated_job_ids),
        location_eligible_count=eligible_count,
        location_needs_review_count=needs_review_count,
        location_ineligible_count=ineligible_count,
        saved_search_match_count=len(matched_records),
        actionable_match_count=actionable_match_count,
        surfaced_in_discover_count=len(discover_jobs),
    )
    return matching_summary, matched_records[:MAX_TOP_MATCHES], discover_jobs


def _source_observations_by_job_id(
    session: Session,
    *,
    job_lead_ids: list[UUID],
) -> dict[UUID, JobSourceObservationModel]:
    if not job_lead_ids:
        return {}
    rows = list(
        session.scalars(
            select(JobSourceObservationModel)
            .where(JobSourceObservationModel.job_lead_id.in_(job_lead_ids))
            .order_by(
                JobSourceObservationModel.active.desc(),
                JobSourceObservationModel.last_seen_at.desc(),
                JobSourceObservationModel.created_at.desc(),
            )
        )
    )
    by_job_id: dict[UUID, JobSourceObservationModel] = {}
    for row in rows:
        by_job_id.setdefault(row.job_lead_id, row)
    return by_job_id


def _location_summary_for_observation(
    *,
    candidate: CandidateProfileModel | None,
    source_observation: JobSourceObservationModel | None,
    job_lead: JobLeadModel,
) -> tuple[JobLocationEligibilityStatus, str]:
    if candidate is None:
        return JobLocationEligibilityStatus.NEEDS_REVIEW, "Candidate profile is unavailable."
    payload = source_observation.normalized_payload if source_observation is not None else {}
    offices = payload.get("offices") if isinstance(payload, dict) else None
    metadata = payload.get("metadata") if isinstance(payload, dict) else None
    result = classify_job_location_eligibility(
        candidate.to_snapshot(),
        JobLocationSignals(
            location_text=job_lead.location_text,
            workplace_type=(
                WorkplaceType(job_lead.workplace_type) if job_lead.workplace_type else None
            ),
            offices=[str(value) for value in offices if isinstance(value, str)]
            if isinstance(offices, list)
            else [],
            metadata=cast(dict[str, object], metadata) if isinstance(metadata, dict) else {},
        ),
    )
    return result.status, result.summary


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
