from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any
from urllib.parse import urlencode, urlsplit
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
from ai_job_finder.api.v1.schemas import JobSourceConfigurationCreateRequest
from ai_job_finder.application.job_imports import (
    create_job_source_configuration,
    get_job_import_run,
    get_job_source_configuration,
    list_job_import_runs,
    list_job_source_configurations,
    list_ranked_discovered_leads,
    run_job_source_import,
    set_job_source_enabled,
)
from ai_job_finder.application.services import update_job_lead_status
from ai_job_finder.application.source_detection import (
    SourceDetectionConfig,
    approve_source_detection_run,
    create_source_detection_run,
    get_source_detection_run,
    list_source_detection_runs,
    validate_greenhouse_token,
)
from ai_job_finder.domain.enums import (
    JobLocationEligibilityStatus,
    JobSourceProvider,
    PostingStatus,
    Recommendation,
    SourcePostingStatus,
    WorkplaceType,
)
from ai_job_finder.domain.errors import DomainError, NotFoundError
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


@dataclass(slots=True)
class SourceListItem:
    source: Any
    active_imported_count: int


@dataclass(slots=True)
class DiscoveryQueueStats:
    total_discovered: int
    currently_shown: int
    actionable: int
    needs_review: int
    ineligible: int


def _source_form_defaults() -> dict[str, str]:
    return {
        "display_name": "",
        "company_name": "",
        "board_token": "",
        "source_url": "",
    }


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


def _render_filter_error(request: Request, message: str) -> Response:
    return render_template(
        request,
        "errors/error.html",
        {
            "page_title": "Invalid Filter",
            "title": "Invalid filter",
            "message": message,
        },
        status_code=422,
    )


@router.get("/job-sources")
def job_sources_list(request: Request, session: DbSession, flash: str | None = None) -> Response:
    items = [
        SourceListItem(
            source=source,
            active_imported_count=len(
                list_ranked_discovered_leads(
                    session,
                    source_id=source.id,
                    include_ineligible=True,
                )
            ),
        )
        for source in list_job_source_configurations(session)
    ]
    flashes = []
    if flash == "source-created":
        flashes.append({"level": "success", "message": "Job source created."})
    if flash == "sync-started":
        flashes.append({"level": "success", "message": "Source sync completed."})
    return render_template(
        request,
        "job_sources/list.html",
        {"page_title": "Job Sources", "source_items": items, "flash_messages": flashes},
    )


@router.get("/job-sources/new")
def job_sources_new(request: Request) -> Response:
    return render_template(
        request,
        "job_sources/new.html",
        {
            "page_title": "New Job Source",
            "form_values": _source_form_defaults(),
            "form_errors": {},
        },
    )


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


@router.post("/job-sources")
async def job_sources_create(request: Request, session: DbSession) -> Response:
    form = await request.form()
    values = {field: str(form.get(field, "")) for field in _source_form_defaults()}
    try:
        payload = JobSourceConfigurationCreateRequest.model_validate(
            {
                "provider": JobSourceProvider.GREENHOUSE.value,
                "display_name": values["display_name"],
                "company_name": values["company_name"],
                "board_token": values["board_token"],
                "source_url": optional_str(values["source_url"]),
                "enabled": True,
            }
        )
    except ValidationError as exc:
        return render_template(
            request,
            "job_sources/new.html",
            {
                "page_title": "New Job Source",
                "form_values": values,
                "form_errors": _validation_errors(exc),
            },
            status_code=422,
        )
    try:
        source = create_job_source_configuration(
            session,
            provider=payload.provider.value,
            display_name=payload.display_name,
            company_name=payload.company_name,
            board_token=payload.board_token,
            source_url=payload.source_url,
            enabled=payload.enabled,
        )
    except DomainError as exc:
        return render_template(
            request,
            "job_sources/new.html",
            {
                "page_title": "New Job Source",
                "form_values": values,
                "form_errors": {"board_token": str(exc)},
            },
            status_code=409,
        )
    return RedirectResponse(
        url=f"/job-sources/{source.id}?flash=source-created",
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


@router.get("/job-sources/{source_id}")
def job_sources_detail(
    request: Request,
    source_id: UUID,
    session: DbSession,
    flash: str | None = None,
) -> Response:
    try:
        source = get_job_source_configuration(session, source_id)
    except NotFoundError as exc:
        return render_template(
            request,
            "errors/error.html",
            {
                "page_title": "Job Source Not Found",
                "title": "Job source not found",
                "message": str(exc),
            },
            status_code=404,
        )
    flashes = []
    if flash == "source-created":
        flashes.append({"level": "success", "message": "Job source created."})
    if flash == "source-enabled":
        flashes.append({"level": "success", "message": "Job source enabled."})
    if flash == "source-disabled":
        flashes.append({"level": "success", "message": "Job source disabled."})
    runs = list_job_import_runs(session, source_id=source.id)
    return render_template(
        request,
        "job_sources/detail.html",
        {
            "page_title": source.display_name,
            "source": source,
            "runs": runs,
            "active_imported_count": len(
                list_ranked_discovered_leads(
                    session,
                    source_id=source.id,
                    include_ineligible=True,
                )
            ),
            "flash_messages": flashes,
        },
    )


@router.post("/job-sources/{source_id}/enable")
def job_sources_enable(source_id: UUID, session: DbSession) -> Response:
    set_job_source_enabled(session, source_id=source_id, enabled=True)
    return RedirectResponse(
        url=f"/job-sources/{source_id}?flash=source-enabled",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/job-sources/{source_id}/disable")
def job_sources_disable(source_id: UUID, session: DbSession) -> Response:
    set_job_source_enabled(session, source_id=source_id, enabled=False)
    return RedirectResponse(
        url=f"/job-sources/{source_id}?flash=source-disabled",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/job-sources/{source_id}/sync")
def job_sources_sync(
    source_id: UUID,
    session: DbSession,
    connector: JobSourceConnectorDependency,
    settings: SettingsDependency,
) -> Response:
    run = run_job_source_import(
        session,
        source_id=source_id,
        connector=connector,
        retain_raw_payload=settings.greenhouse_retain_raw_payload,
        close_on_empty=settings.greenhouse_close_on_empty_result,
        stale_after_seconds=settings.job_source_stale_after_seconds,
    )
    return RedirectResponse(
        url=f"/job-import-runs/{run.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/job-import-runs/{run_id}")
def job_import_run_detail(request: Request, run_id: UUID, session: DbSession) -> Response:
    run = get_job_import_run(session, run_id)
    source = get_job_source_configuration(session, run.source_configuration_id)
    return render_template(
        request,
        "job_sources/import_run.html",
        {"page_title": "Import Run", "run": run, "source": source},
    )


@router.get("/discover")
def discover_queue(
    request: Request,
    session: DbSession,
    source_id: str | None = None,
    company: str | None = None,
    source_posting_status: str | None = None,
    workflow_status: str | None = None,
    recommendation: str | None = None,
    minimum_score: str | None = None,
    location: str | None = None,
    workplace_type: str | None = None,
    location_eligibility: str | None = None,
) -> Response:
    try:
        parsed_source_id = UUID(source_id) if source_id else None
    except ValueError:
        return _render_filter_error(request, "Source filter must be a valid identifier.")
    try:
        parsed_minimum_score = float(minimum_score) if minimum_score else None
    except ValueError:
        return _render_filter_error(request, "Minimum score must be a valid number.")
    try:
        parsed_location_eligibility = (
            JobLocationEligibilityStatus(location_eligibility) if location_eligibility else None
        )
    except ValueError:
        return _render_filter_error(request, "Location eligibility filter is invalid.")
    selected = {
        "source_id": source_id or "",
        "company": company or "",
        "source_posting_status": source_posting_status or "",
        "workflow_status": workflow_status or "",
        "recommendation": recommendation or "",
        "minimum_score": minimum_score or "",
        "location": location or "",
        "workplace_type": workplace_type or "",
        "location_eligibility": location_eligibility or "",
    }
    items = list_ranked_discovered_leads(
        session,
        source_id=parsed_source_id,
        company=optional_str(company),
        source_posting_status=optional_str(source_posting_status),
        workflow_status=optional_str(workflow_status),
        recommendation=optional_str(recommendation),
        minimum_score=parsed_minimum_score,
        location=optional_str(location),
        workplace_type=optional_str(workplace_type),
        location_eligibility=parsed_location_eligibility,
    )
    all_matching_items = list_ranked_discovered_leads(
        session,
        source_id=parsed_source_id,
        company=optional_str(company),
        source_posting_status=optional_str(source_posting_status),
        workflow_status=optional_str(workflow_status),
        recommendation=optional_str(recommendation),
        minimum_score=parsed_minimum_score,
        location=optional_str(location),
        workplace_type=optional_str(workplace_type),
        include_ineligible=True,
    )
    stats = DiscoveryQueueStats(
        total_discovered=len(all_matching_items),
        currently_shown=len(items),
        actionable=sum(
            item.location_eligibility.status is not JobLocationEligibilityStatus.INELIGIBLE
            for item in all_matching_items
        ),
        needs_review=sum(
            item.location_eligibility.status is JobLocationEligibilityStatus.NEEDS_REVIEW
            for item in all_matching_items
        ),
        ineligible=sum(
            item.location_eligibility.status is JobLocationEligibilityStatus.INELIGIBLE
            for item in all_matching_items
        ),
    )
    active_query = urlencode({key: value for key, value in selected.items() if value})
    return_to = f"/discover?{active_query}" if active_query else "/discover"
    has_filters = any(value for value in selected.values())
    return render_template(
        request,
        "job_sources/discover.html",
        {
            "page_title": "Discovered jobs",
            "lead_items": items,
            "queue_stats": stats,
            "has_filters": has_filters,
            "return_to": return_to,
            "sources": list_job_source_configurations(session),
            "posting_statuses": list(PostingStatus),
            "source_posting_statuses": list(SourcePostingStatus),
            "recommendations": list(Recommendation),
            "workplace_types": list(WorkplaceType),
            "location_eligibilities": list(JobLocationEligibilityStatus),
            "selected": selected,
        },
    )


@router.post("/discover/jobs/{job_id}/status")
async def discover_update_status(request: Request, job_id: UUID, session: DbSession) -> Response:
    form = await request.form()
    status_value = str(form.get("posting_status", ""))
    return_to = str(form.get("return_to", "") or "")
    redirect_target = "/discover"
    if return_to:
        parsed_return_to = urlsplit(return_to)
        if (
            not parsed_return_to.scheme
            and not parsed_return_to.netloc
            and return_to.startswith("/discover")
        ):
            redirect_target = return_to
    update_job_lead_status(session, job_id, PostingStatus(status_value).value)
    return RedirectResponse(url=redirect_target, status_code=status.HTTP_303_SEE_OTHER)
