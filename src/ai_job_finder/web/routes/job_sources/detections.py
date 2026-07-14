from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from ai_job_finder.api.dependencies import (
    greenhouse_board_validator_dependency,
    job_source_connector_dependency,
    public_page_fetcher_dependency,
    settings_dependency,
)
from ai_job_finder.application.source_detection import (
    SourceDetectionConfig,
    approve_source_detection_run,
    create_source_detection_run,
    get_source_detection_run,
    list_source_detection_runs,
    validate_greenhouse_token,
)
from ai_job_finder.domain.errors import DomainError
from ai_job_finder.domain.job_sources import JobSourceConnector
from ai_job_finder.domain.source_detection import GreenhouseBoardValidator, PublicPageFetcher
from ai_job_finder.settings import Settings
from ai_job_finder.web.dependencies import DbSession, optional_str, render_template

router = APIRouter(tags=["web"])
SettingsDependency = Annotated[Settings, Depends(settings_dependency)]
JobSourceConnectorDependency = Annotated[
    JobSourceConnector, Depends(job_source_connector_dependency)
]
PublicPageFetcherDependency = Annotated[PublicPageFetcher, Depends(public_page_fetcher_dependency)]
GreenhouseBoardValidatorDependency = Annotated[
    GreenhouseBoardValidator, Depends(greenhouse_board_validator_dependency)
]


def _detection_form_defaults() -> dict[str, str]:
    return {
        "company_name": "",
        "input_url": "",
        "brand_alias": "",
    }


def _validation_errors(exc: ValidationError) -> dict[str, str]:
    field_errors: dict[str, str] = {}
    for error in exc.errors():
        location = error.get("loc", [])
        if location:
            field_errors.setdefault(str(location[-1]), str(error["msg"]))
    return field_errors


@router.get("/job-sources/detect")
def job_sources_detect(request: Request) -> Response:
    return render_template(
        request,
        "job_sources/detect.html",
        {
            "page_title": "Detect Job Source",
            "form_values": _detection_form_defaults(),
            "form_errors": {},
        },
    )


@router.post("/job-sources/detect")
async def job_sources_detect_create(
    request: Request,
    session: DbSession,
    fetcher: PublicPageFetcherDependency,
    validator: GreenhouseBoardValidatorDependency,
    settings: SettingsDependency,
) -> Response:
    form = await request.form()
    values = {field: str(form.get(field, "")) for field in _detection_form_defaults()}
    if not optional_str(values["company_name"]) and not optional_str(values["input_url"]):
        return render_template(
            request,
            "job_sources/detect.html",
            {
                "page_title": "Detect Job Source",
                "form_values": values,
                "form_errors": {"company_name": "Provide a company name or careers URL."},
            },
            status_code=422,
        )
    run = create_source_detection_run(
        session,
        company_name=optional_str(values["company_name"]),
        input_url=optional_str(values["input_url"]),
        brand_alias=optional_str(values["brand_alias"]),
        fetcher=fetcher,
        validator=validator,
        config=SourceDetectionConfig(
            max_linked_scripts=settings.source_detection_max_linked_scripts,
            max_script_bytes=settings.source_detection_max_script_bytes,
            total_script_bytes=settings.source_detection_total_script_bytes,
        ),
    )
    return RedirectResponse(
        url=f"/job-source-detections/{run.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/job-source-detections")
def job_source_detection_list(request: Request, session: DbSession) -> Response:
    return render_template(
        request,
        "job_sources/detections.html",
        {
            "page_title": "Source Detections",
            "runs": list_source_detection_runs(session),
        },
    )


@router.get("/job-source-detections/{run_id}")
def job_source_detection_detail(
    request: Request,
    run_id: UUID,
    session: DbSession,
    flash: str | None = None,
) -> Response:
    run = get_source_detection_run(session, run_id)
    flashes = []
    if flash == "source-created":
        flashes.append({"level": "success", "message": "Job source created."})
    if flash == "source-created-and-synced":
        flashes.append({"level": "success", "message": "Job source created and synced."})
    return render_template(
        request,
        "job_sources/detection_detail.html",
        {
            "page_title": "Source Detection",
            "run": run,
            "manual_candidate": None,
            "manual_error": None,
            "flash_messages": flashes,
        },
    )


@router.post("/job-source-detections/{run_id}/validate-token")
async def job_source_detection_manual_token(
    request: Request,
    run_id: UUID,
    session: DbSession,
    validator: GreenhouseBoardValidatorDependency,
) -> Response:
    form = await request.form()
    run = get_source_detection_run(session, run_id)
    token = str(form.get("board_token", ""))
    manual_candidate = None
    manual_error = None
    try:
        manual_candidate = validate_greenhouse_token(
            session,
            board_token=token,
            validator=validator,
        )
    except DomainError as exc:
        manual_error = str(exc)
    return render_template(
        request,
        "job_sources/detection_detail.html",
        {
            "page_title": "Source Detection",
            "run": run,
            "manual_candidate": manual_candidate,
            "manual_error": manual_error,
            "flash_messages": [],
        },
        status_code=422 if manual_error else 200,
    )


@router.post("/job-source-detections/{run_id}/approve")
async def job_source_detection_approve(
    request: Request,
    run_id: UUID,
    session: DbSession,
    connector: JobSourceConnectorDependency,
    settings: SettingsDependency,
) -> Response:
    form = await request.form()
    action = str(form.get("action", "create"))
    try:
        result = approve_source_detection_run(
            session,
            run_id=run_id,
            selected_token=optional_str(str(form.get("selected_token", ""))),
            create_and_sync=action == "create_and_sync",
            connector=connector,
            retain_raw_payload=settings.greenhouse_retain_raw_payload,
            close_on_empty=settings.greenhouse_close_on_empty_result,
            stale_after_seconds=settings.job_source_stale_after_seconds,
        )
    except DomainError as exc:
        run = get_source_detection_run(session, run_id)
        return render_template(
            request,
            "job_sources/detection_detail.html",
            {
                "page_title": "Source Detection",
                "run": run,
                "manual_candidate": None,
                "manual_error": str(exc),
                "flash_messages": [],
            },
            status_code=409,
        )
    flash = "source-created-and-synced" if result.import_run else "source-created"
    return RedirectResponse(
        url=f"/job-source-detections/{result.run.id}?flash={flash}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
