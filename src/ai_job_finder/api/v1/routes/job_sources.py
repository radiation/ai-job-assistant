from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from ai_job_finder.api.v1.routes.dependencies import (
    DbSession,
    JobSourceConnectorDependency,
    SettingsDependency,
)
from ai_job_finder.api.v1.schemas import (
    DiscoveredLeadResponse,
    JobEvaluationResponse,
    JobImportRunResponse,
    JobLeadResponse,
    JobLocationEligibilityResponse,
    JobSourceConfigurationCreateRequest,
    JobSourceConfigurationResponse,
    JobSourceConfigurationUpdateRequest,
)
from ai_job_finder.application.job_sources import (
    create_job_source_configuration,
    get_job_import_run,
    get_job_source_configuration,
    list_job_import_runs,
    list_job_source_configurations,
    list_ranked_discovered_leads,
    run_job_source_import,
    set_job_source_enabled,
    update_job_source_configuration,
)
from ai_job_finder.domain.enums import JobLocationEligibilityStatus

router = APIRouter()


@router.post(
    "/job-sources",
    response_model=JobSourceConfigurationResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_job_source(
    payload: JobSourceConfigurationCreateRequest,
    session: DbSession,
) -> JobSourceConfigurationResponse:
    source = create_job_source_configuration(
        session,
        provider=payload.provider.value,
        display_name=payload.display_name,
        company_name=payload.company_name,
        board_token=payload.board_token,
        source_url=payload.source_url,
        enabled=payload.enabled,
    )
    return JobSourceConfigurationResponse.model_validate(source)


@router.get("/job-sources", response_model=list[JobSourceConfigurationResponse])
def get_job_sources(session: DbSession) -> list[JobSourceConfigurationResponse]:
    return [
        JobSourceConfigurationResponse.model_validate(source)
        for source in list_job_source_configurations(session)
    ]


@router.get("/job-sources/{source_id}", response_model=JobSourceConfigurationResponse)
def get_job_source_route(source_id: UUID, session: DbSession) -> JobSourceConfigurationResponse:
    source = get_job_source_configuration(session, source_id)
    return JobSourceConfigurationResponse.model_validate(source)


@router.put("/job-sources/{source_id}", response_model=JobSourceConfigurationResponse)
def put_job_source(
    source_id: UUID,
    payload: JobSourceConfigurationUpdateRequest,
    session: DbSession,
) -> JobSourceConfigurationResponse:
    source = update_job_source_configuration(
        session,
        source_id=source_id,
        display_name=payload.display_name,
        company_name=payload.company_name,
        board_token=payload.board_token,
        source_url=payload.source_url,
    )
    return JobSourceConfigurationResponse.model_validate(source)


@router.post("/job-sources/{source_id}/enable", response_model=JobSourceConfigurationResponse)
def post_job_source_enable(source_id: UUID, session: DbSession) -> JobSourceConfigurationResponse:
    return JobSourceConfigurationResponse.model_validate(
        set_job_source_enabled(session, source_id=source_id, enabled=True)
    )


@router.post("/job-sources/{source_id}/disable", response_model=JobSourceConfigurationResponse)
def post_job_source_disable(source_id: UUID, session: DbSession) -> JobSourceConfigurationResponse:
    return JobSourceConfigurationResponse.model_validate(
        set_job_source_enabled(session, source_id=source_id, enabled=False)
    )


@router.post(
    "/job-sources/{source_id}/imports",
    response_model=JobImportRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_job_source_import(
    source_id: UUID,
    session: DbSession,
    connector: JobSourceConnectorDependency,
    settings: SettingsDependency,
) -> JobImportRunResponse:
    run = run_job_source_import(
        session,
        source_id=source_id,
        connector=connector,
        retain_raw_payload=settings.greenhouse_retain_raw_payload,
        close_on_empty=settings.greenhouse_close_on_empty_result,
        stale_after_seconds=settings.job_source_stale_after_seconds,
    )
    return JobImportRunResponse.model_validate(run)


@router.get("/job-import-runs", response_model=list[JobImportRunResponse])
def get_job_import_runs(
    session: DbSession,
    source_id: UUID | None = None,
) -> list[JobImportRunResponse]:
    return [
        JobImportRunResponse.model_validate(run)
        for run in list_job_import_runs(session, source_id=source_id)
    ]


@router.get("/job-import-runs/{run_id}", response_model=JobImportRunResponse)
def get_job_import_run_route(run_id: UUID, session: DbSession) -> JobImportRunResponse:
    return JobImportRunResponse.model_validate(get_job_import_run(session, run_id))


@router.get("/discovered-leads", response_model=list[DiscoveredLeadResponse])
def get_discovered_leads(
    session: DbSession,
    search_definition_id: UUID | None = None,
    source_id: UUID | None = None,
    company: str | None = None,
    source_posting_status: str | None = None,
    workflow_status: str | None = None,
    recommendation: str | None = None,
    minimum_score: float | None = None,
    location: str | None = None,
    workplace_type: str | None = None,
    location_eligibility: JobLocationEligibilityStatus | None = None,
) -> list[DiscoveredLeadResponse]:
    items = list_ranked_discovered_leads(
        session,
        search_definition_id=search_definition_id,
        source_id=source_id,
        company=company,
        source_posting_status=source_posting_status,
        workflow_status=workflow_status,
        recommendation=recommendation,
        minimum_score=minimum_score,
        location=location,
        workplace_type=workplace_type,
        location_eligibility=location_eligibility,
    )
    return [
        DiscoveredLeadResponse(
            job=JobLeadResponse.model_validate(item.job),
            latest_evaluation=(
                JobEvaluationResponse.model_validate(item.latest_evaluation)
                if item.latest_evaluation
                else None
            ),
            location_eligibility=JobLocationEligibilityResponse(
                status=item.location_eligibility.status,
                reasons=item.location_eligibility.reasons,
                summary=item.location_eligibility.summary,
            ),
            source_configuration_id=item.observation.source_configuration_id,
            observation_id=item.observation.id,
            external_post_id=item.observation.external_post_id,
            external_internal_job_id=item.observation.external_internal_job_id,
            canonical_url=item.observation.canonical_url,
            first_seen_at=item.observation.first_seen_at,
            last_seen_at=item.observation.last_seen_at,
            source_updated_at=item.observation.source_updated_at,
            duplicate_hint_key=item.observation.duplicate_hint_key,
        )
        for item in items
    ]
