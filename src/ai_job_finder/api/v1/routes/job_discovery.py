from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from ai_job_finder.api.v1.routes.dependencies import (
    DbSession,
    JobDiscoveryProviderDependency,
    JobSourceBoardValidatorDependency,
    JobSourceConnectorDependency,
    PublicPageFetcherDependency,
    SettingsDependency,
)
from ai_job_finder.api.v1.schemas import (
    JobDiscoveryDetailObservationResponse,
    JobDiscoveryImportResponse,
    JobDiscoveryMatchedJobResponse,
    JobDiscoveryMatchingSummaryResponse,
    JobDiscoveryObservationResponse,
    JobDiscoveryQueryResponse,
    JobDiscoveryRunDetailResponse,
    JobDiscoveryRunResponse,
)
from ai_job_finder.application.job_discovery import (
    JobDiscoveryConfig,
    get_job_discovery_run_detail,
    list_job_discovery_observations,
    list_job_discovery_runs,
    run_job_discovery,
)
from ai_job_finder.application.source_detection import SourceDetectionConfig

router = APIRouter()


@router.post(
    "/job-searches/{search_definition_id}/discovery-runs",
    response_model=JobDiscoveryRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_job_discovery_run(
    search_definition_id: UUID,
    session: DbSession,
    provider: JobDiscoveryProviderDependency,
    fetcher: PublicPageFetcherDependency,
    board_validator: JobSourceBoardValidatorDependency,
    connector: JobSourceConnectorDependency,
    settings: SettingsDependency,
) -> JobDiscoveryRunResponse:
    run = run_job_discovery(
        session,
        search_definition_id=search_definition_id,
        provider_name=settings.job_discovery_provider,
        provider=provider,
        fetcher=fetcher,
        board_validator=board_validator,
        connector=connector,
        config=JobDiscoveryConfig(
            max_queries_per_run=settings.job_discovery_max_queries_per_run,
            result_limit=settings.job_discovery_result_limit,
            max_total_candidates=settings.job_discovery_max_total_candidates,
            source_detection=SourceDetectionConfig(
                max_linked_scripts=settings.source_detection_max_linked_scripts,
                max_script_bytes=settings.source_detection_max_script_bytes,
                total_script_bytes=settings.source_detection_total_script_bytes,
            ),
            retain_raw_payload=settings.greenhouse_retain_raw_payload,
            close_on_empty=settings.greenhouse_close_on_empty_result,
            stale_after_seconds=settings.job_source_stale_after_seconds,
        ),
    )
    return JobDiscoveryRunResponse.model_validate(run)


@router.get(
    "/job-searches/{search_definition_id}/discovery-runs",
    response_model=list[JobDiscoveryRunResponse],
)
def get_job_discovery_runs_for_search(
    search_definition_id: UUID,
    session: DbSession,
) -> list[JobDiscoveryRunResponse]:
    return [
        JobDiscoveryRunResponse.model_validate(run)
        for run in list_job_discovery_runs(session, search_definition_id=search_definition_id)
    ]


@router.get(
    "/job-discovery-runs/{run_id}",
    response_model=JobDiscoveryRunDetailResponse,
)
def get_job_discovery_run_route(
    run_id: UUID,
    session: DbSession,
) -> JobDiscoveryRunDetailResponse:
    detail = get_job_discovery_run_detail(session, run_id)
    return JobDiscoveryRunDetailResponse(
        run=JobDiscoveryRunResponse.model_validate(detail.run),
        queries=[JobDiscoveryQueryResponse.model_validate(query) for query in detail.queries],
        observations=[
            JobDiscoveryDetailObservationResponse(
                id=record.observation.id,
                query_ordinals=list(record.observation.query_ordinals),
                provider=record.observation.provider,
                discovered_url=record.observation.discovered_url,
                normalized_url=record.observation.normalized_url,
                title_hint=record.observation.title_hint,
                company_hint=record.observation.company_hint,
                location_hint=record.observation.location_hint,
                source_detection_status=record.observation.source_detection_outcome,
                source_detection_run_id=record.observation.source_detection_run_id,
                detected_provider=(
                    record.source_detection_run.detected_provider
                    if record.source_detection_run is not None
                    else None
                ),
                previously_seen=record.previously_seen,
                reused_prior_resolution=record.reused_prior_resolution,
                source_configuration_id=record.observation.source_configuration_id,
                source_display_name=(
                    record.source_configuration.display_name
                    if record.source_configuration is not None
                    else None
                ),
                source_company_name=(
                    record.source_configuration.company_name
                    if record.source_configuration is not None
                    else None
                ),
                source_board_token=(
                    record.source_configuration.board_token
                    if record.source_configuration is not None
                    else None
                ),
                source_created_in_run=record.source_created_in_run,
                source_reused_in_run=record.source_reused_in_run,
                import_run_id=record.observation.import_run_id,
                imported_job_lead_id=record.observation.imported_job_lead_id,
                processing_status=record.observation.processing_status,
                exclusion_reason=record.observation.exclusion_reason,
                matched=(record.saved_search_match.matched if record.saved_search_match else None),
                score_at_match_time=(
                    record.saved_search_match.score_at_match_time
                    if record.saved_search_match
                    else None
                ),
            )
            for record in detail.observations
        ],
        imports=[
            JobDiscoveryImportResponse(
                source_configuration_id=record.source_configuration.id,
                provider=record.source_configuration.provider,
                display_name=record.source_configuration.display_name,
                company_name=record.source_configuration.company_name,
                board_token=record.source_configuration.board_token,
                imported_during_run=record.imported_during_run,
                source_created_in_run=record.source_created_in_run,
                source_reused_in_run=record.source_reused_in_run,
                observation_count=record.observation_count,
                import_run_id=record.import_run.id if record.import_run is not None else None,
                import_status=record.import_status,
                jobs_created=record.import_run.jobs_created if record.import_run is not None else 0,
                jobs_updated=record.import_run.jobs_updated if record.import_run is not None else 0,
                jobs_unchanged=record.import_run.jobs_unchanged
                if record.import_run is not None
                else 0,
                jobs_failed=record.import_run.jobs_failed if record.import_run is not None else 0,
                failure_message=record.failure_message,
            )
            for record in detail.imports
        ],
        matching_summary=JobDiscoveryMatchingSummaryResponse(
            canonical_jobs_evaluated=detail.matching_summary.canonical_jobs_evaluated,
            location_eligible_count=detail.matching_summary.location_eligible_count,
            location_needs_review_count=detail.matching_summary.location_needs_review_count,
            location_ineligible_count=detail.matching_summary.location_ineligible_count,
            saved_search_match_count=detail.matching_summary.saved_search_match_count,
            actionable_match_count=detail.matching_summary.actionable_match_count,
            surfaced_in_discover_count=detail.matching_summary.surfaced_in_discover_count,
        ),
        top_matches=[
            JobDiscoveryMatchedJobResponse(
                observation_id=record.observation.id,
                job_lead_id=record.job_lead.id,
                title=record.job_lead.title,
                company_name=record.job_lead.company_name,
                location_text=record.job_lead.location_text,
                score=record.saved_search_match.score_at_match_time,
                recommendation=record.saved_search_match.recommendation_at_match_time,
                explanation=record.evaluation.explanation
                if record.evaluation is not None
                else None,
                location_eligibility_status=record.location_eligibility_status,
                location_eligibility_summary=record.location_eligibility_summary,
                surfaced_in_discover=record.surfaced_in_discover,
            )
            for record in detail.top_matches
        ],
        discover_jobs=[
            JobDiscoveryMatchedJobResponse(
                observation_id=record.observation.id,
                job_lead_id=record.job_lead.id,
                title=record.job_lead.title,
                company_name=record.job_lead.company_name,
                location_text=record.job_lead.location_text,
                score=record.saved_search_match.score_at_match_time,
                recommendation=record.saved_search_match.recommendation_at_match_time,
                explanation=record.evaluation.explanation
                if record.evaluation is not None
                else None,
                location_eligibility_status=record.location_eligibility_status,
                location_eligibility_summary=record.location_eligibility_summary,
                surfaced_in_discover=record.surfaced_in_discover,
            )
            for record in detail.discover_jobs
        ],
    )


@router.get(
    "/job-discovery-runs/{run_id}/observations",
    response_model=list[JobDiscoveryObservationResponse],
)
def get_job_discovery_observations_route(
    run_id: UUID,
    session: DbSession,
) -> list[JobDiscoveryObservationResponse]:
    records = list_job_discovery_observations(session, discovery_run_id=run_id)
    return [
        JobDiscoveryObservationResponse(
            id=record.observation.id,
            discovery_run_id=record.observation.discovery_run_id,
            primary_query_id=record.observation.primary_query_id,
            query_ordinals=list(record.observation.query_ordinals),
            provider=record.observation.provider,
            provider_result_id=record.observation.provider_result_id,
            discovered_url=record.observation.discovered_url,
            normalized_url=record.observation.normalized_url,
            title_hint=record.observation.title_hint,
            company_hint=record.observation.company_hint,
            location_hint=record.observation.location_hint,
            evidence_snippet=record.observation.evidence_snippet,
            rank=record.observation.rank,
            source_detection_outcome=record.observation.source_detection_outcome,
            source_detection_run_id=record.observation.source_detection_run_id,
            source_configuration_id=record.observation.source_configuration_id,
            import_run_id=record.observation.import_run_id,
            imported_job_lead_id=record.observation.imported_job_lead_id,
            processing_status=record.observation.processing_status,
            exclusion_reason=record.observation.exclusion_reason,
            discovered_at=record.observation.discovered_at,
            created_at=record.observation.created_at,
            updated_at=record.observation.updated_at,
            saved_search_match_id=(
                record.saved_search_match.id if record.saved_search_match else None
            ),
            matched=(record.saved_search_match.matched if record.saved_search_match else None),
            score_at_match_time=(
                record.saved_search_match.score_at_match_time if record.saved_search_match else None
            ),
            job_evaluation_id=(
                record.saved_search_match.job_evaluation_id if record.saved_search_match else None
            ),
        )
        for record in records
    ]
