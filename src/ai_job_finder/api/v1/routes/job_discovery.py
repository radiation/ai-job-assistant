from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from ai_job_finder.api.v1.routes.dependencies import (
    DbSession,
    GreenhouseBoardValidatorDependency,
    JobDiscoveryProviderDependency,
    JobSourceConnectorDependency,
    PublicPageFetcherDependency,
    SettingsDependency,
)
from ai_job_finder.api.v1.schemas import (
    JobDiscoveryObservationResponse,
    JobDiscoveryQueryResponse,
    JobDiscoveryRunDetailResponse,
    JobDiscoveryRunResponse,
)
from ai_job_finder.application.job_discovery import (
    JobDiscoveryConfig,
    get_job_discovery_run,
    list_job_discovery_observations,
    list_job_discovery_queries,
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
    validator: GreenhouseBoardValidatorDependency,
    connector: JobSourceConnectorDependency,
    settings: SettingsDependency,
) -> JobDiscoveryRunResponse:
    run = run_job_discovery(
        session,
        search_definition_id=search_definition_id,
        provider_name=settings.job_discovery_provider,
        provider=provider,
        fetcher=fetcher,
        validator=validator,
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
    run = get_job_discovery_run(session, run_id)
    queries = list_job_discovery_queries(session, discovery_run_id=run_id)
    return JobDiscoveryRunDetailResponse(
        run=JobDiscoveryRunResponse.model_validate(run),
        queries=[JobDiscoveryQueryResponse.model_validate(query) for query in queries],
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
