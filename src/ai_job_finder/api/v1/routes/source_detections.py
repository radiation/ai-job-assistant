from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from ai_job_finder.api.v1.routes.dependencies import (
    DbSession,
    GreenhouseBoardValidatorDependency,
    JobSourceConnectorDependency,
    PublicPageFetcherDependency,
    SettingsDependency,
)
from ai_job_finder.api.v1.schemas import (
    JobImportRunResponse,
    JobSourceConfigurationResponse,
    ManualGreenhouseTokenValidationRequest,
    ManualGreenhouseTokenValidationResponse,
    SourceDetectionApprovalRequest,
    SourceDetectionApprovalResponse,
    SourceDetectionRunCreateRequest,
    SourceDetectionRunResponse,
)
from ai_job_finder.application.source_detection import (
    SourceDetectionConfig,
    approve_source_detection_run,
    create_source_detection_run,
    get_source_detection_run,
    list_source_detection_runs,
    validate_greenhouse_token,
)

router = APIRouter()


@router.post(
    "/source-detections",
    response_model=SourceDetectionRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_source_detection(
    payload: SourceDetectionRunCreateRequest,
    session: DbSession,
    fetcher: PublicPageFetcherDependency,
    validator: GreenhouseBoardValidatorDependency,
    settings: SettingsDependency,
) -> SourceDetectionRunResponse:
    run = create_source_detection_run(
        session,
        company_name=payload.company_name,
        input_url=payload.input_url,
        brand_alias=payload.brand_alias,
        fetcher=fetcher,
        validator=validator,
        config=SourceDetectionConfig(
            max_linked_scripts=settings.source_detection_max_linked_scripts,
            max_script_bytes=settings.source_detection_max_script_bytes,
            total_script_bytes=settings.source_detection_total_script_bytes,
        ),
    )
    return SourceDetectionRunResponse.model_validate(run)


@router.get("/source-detections", response_model=list[SourceDetectionRunResponse])
def get_source_detections(session: DbSession) -> list[SourceDetectionRunResponse]:
    return [
        SourceDetectionRunResponse.model_validate(run)
        for run in list_source_detection_runs(session)
    ]


@router.get("/source-detections/{run_id}", response_model=SourceDetectionRunResponse)
def get_source_detection_route(run_id: UUID, session: DbSession) -> SourceDetectionRunResponse:
    return SourceDetectionRunResponse.model_validate(get_source_detection_run(session, run_id))


@router.post(
    "/source-detections/validate-token",
    response_model=ManualGreenhouseTokenValidationResponse,
)
def post_source_detection_validate_token(
    payload: ManualGreenhouseTokenValidationRequest,
    session: DbSession,
    validator: GreenhouseBoardValidatorDependency,
) -> ManualGreenhouseTokenValidationResponse:
    return ManualGreenhouseTokenValidationResponse(
        candidate=validate_greenhouse_token(
            session,
            board_token=payload.board_token,
            validator=validator,
        )
    )


@router.post(
    "/source-detections/{run_id}/approve",
    response_model=SourceDetectionApprovalResponse,
)
def post_source_detection_approve(
    run_id: UUID,
    payload: SourceDetectionApprovalRequest,
    session: DbSession,
    connector: JobSourceConnectorDependency,
    settings: SettingsDependency,
) -> SourceDetectionApprovalResponse:
    result = approve_source_detection_run(
        session,
        run_id=run_id,
        selected_token=payload.selected_token,
        create_and_sync=payload.create_and_sync,
        connector=connector,
        retain_raw_payload=settings.greenhouse_retain_raw_payload,
        close_on_empty=settings.greenhouse_close_on_empty_result,
        stale_after_seconds=settings.job_source_stale_after_seconds,
    )
    return SourceDetectionApprovalResponse(
        run=SourceDetectionRunResponse.model_validate(result.run),
        source=JobSourceConfigurationResponse.model_validate(result.source),
        import_run=(
            JobImportRunResponse.model_validate(result.import_run) if result.import_run else None
        ),
        existing_source=result.existing_source,
    )
