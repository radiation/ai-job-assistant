from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from ai_job_finder.api.v1.routes.dependencies import DbSession
from ai_job_finder.api.v1.schemas import (
    JobSearchDefinitionCreateRequest,
    JobSearchDefinitionResponse,
    JobSearchDefinitionUpdateRequest,
    JobSearchMatchResponse,
    JobSearchRunDetailResponse,
    JobSearchRunResponse,
)
from ai_job_finder.application.job_searches import (
    create_job_search_definition,
    get_job_search_definition,
    get_job_search_run,
    list_job_search_definitions,
    list_job_search_matches,
    list_job_search_runs,
    run_job_search,
    set_job_search_definition_enabled,
    update_job_search_definition,
)

router = APIRouter()


@router.post(
    "/job-searches",
    response_model=JobSearchDefinitionResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_job_search(
    payload: JobSearchDefinitionCreateRequest,
    session: DbSession,
) -> JobSearchDefinitionResponse:
    search = create_job_search_definition(
        session,
        name=payload.name,
        enabled=payload.enabled,
        title_include_patterns=payload.title_include_patterns,
        title_exclude_patterns=payload.title_exclude_patterns,
        target_domains=[value.value for value in payload.target_domains],
        target_seniority_levels=[value.value for value in payload.target_seniority_levels],
        allowed_locations=payload.allowed_locations,
        allowed_remote_geographies=payload.allowed_remote_geographies,
        allowed_workplace_types=[value.value for value in payload.allowed_workplace_types],
        minimum_score_threshold=payload.minimum_score_threshold,
    )
    return JobSearchDefinitionResponse.model_validate(search)


@router.get("/job-searches", response_model=list[JobSearchDefinitionResponse])
def get_job_searches(session: DbSession) -> list[JobSearchDefinitionResponse]:
    return [
        JobSearchDefinitionResponse.model_validate(item)
        for item in list_job_search_definitions(session)
    ]


@router.get("/job-searches/{search_definition_id}", response_model=JobSearchDefinitionResponse)
def get_job_search_route(
    search_definition_id: UUID,
    session: DbSession,
) -> JobSearchDefinitionResponse:
    return JobSearchDefinitionResponse.model_validate(
        get_job_search_definition(session, search_definition_id)
    )


@router.put("/job-searches/{search_definition_id}", response_model=JobSearchDefinitionResponse)
def put_job_search(
    search_definition_id: UUID,
    payload: JobSearchDefinitionUpdateRequest,
    session: DbSession,
) -> JobSearchDefinitionResponse:
    search = update_job_search_definition(
        session,
        search_definition_id=search_definition_id,
        name=payload.name,
        title_include_patterns=payload.title_include_patterns,
        title_exclude_patterns=payload.title_exclude_patterns,
        target_domains=[value.value for value in payload.target_domains],
        target_seniority_levels=[value.value for value in payload.target_seniority_levels],
        allowed_locations=payload.allowed_locations,
        allowed_remote_geographies=payload.allowed_remote_geographies,
        allowed_workplace_types=[value.value for value in payload.allowed_workplace_types],
        minimum_score_threshold=payload.minimum_score_threshold,
    )
    return JobSearchDefinitionResponse.model_validate(search)


@router.post(
    "/job-searches/{search_definition_id}/enable",
    response_model=JobSearchDefinitionResponse,
)
def post_job_search_enable(
    search_definition_id: UUID,
    session: DbSession,
) -> JobSearchDefinitionResponse:
    return JobSearchDefinitionResponse.model_validate(
        set_job_search_definition_enabled(
            session,
            search_definition_id=search_definition_id,
            enabled=True,
        )
    )


@router.post(
    "/job-searches/{search_definition_id}/disable",
    response_model=JobSearchDefinitionResponse,
)
def post_job_search_disable(
    search_definition_id: UUID,
    session: DbSession,
) -> JobSearchDefinitionResponse:
    return JobSearchDefinitionResponse.model_validate(
        set_job_search_definition_enabled(
            session,
            search_definition_id=search_definition_id,
            enabled=False,
        )
    )


@router.post(
    "/job-searches/{search_definition_id}/runs",
    response_model=JobSearchRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_job_search_run(search_definition_id: UUID, session: DbSession) -> JobSearchRunResponse:
    return JobSearchRunResponse.model_validate(
        run_job_search(session, search_definition_id=search_definition_id)
    )


@router.get("/job-search-runs", response_model=list[JobSearchRunResponse])
def get_job_search_runs(
    session: DbSession,
    search_definition_id: UUID | None = None,
) -> list[JobSearchRunResponse]:
    return [
        JobSearchRunResponse.model_validate(run)
        for run in list_job_search_runs(session, search_definition_id=search_definition_id)
    ]


@router.get("/job-search-runs/{run_id}", response_model=JobSearchRunResponse)
def get_job_search_run_route(run_id: UUID, session: DbSession) -> JobSearchRunResponse:
    return JobSearchRunResponse.model_validate(get_job_search_run(session, run_id))


@router.get(
    "/job-search-runs/{run_id}/matches",
    response_model=JobSearchRunDetailResponse,
)
def get_job_search_matches_route(run_id: UUID, session: DbSession) -> JobSearchRunDetailResponse:
    run = get_job_search_run(session, run_id)
    matches = list_job_search_matches(session, search_run_id=run_id)
    return JobSearchRunDetailResponse(
        run=JobSearchRunResponse.model_validate(run),
        matches=[JobSearchMatchResponse.model_validate(item.match) for item in matches],
    )
