from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from ai_job_finder.api.v1.schemas import JobSourceConfigurationCreateRequest
from ai_job_finder.application.job_imports import (
    create_job_source_configuration,
    get_job_source_configuration,
    list_job_import_runs,
    list_job_source_configurations,
    list_ranked_discovered_leads,
    set_job_source_enabled,
)
from ai_job_finder.domain.enums import (
    JobSourceProvider,
)
from ai_job_finder.domain.errors import DomainError, NotFoundError
from ai_job_finder.web.dependencies import DbSession, optional_str, render_template

router = APIRouter(tags=["web"])


@dataclass(slots=True)
class SourceListItem:
    source: Any
    active_imported_count: int


def _source_form_defaults() -> dict[str, str]:
    return {
        "display_name": "",
        "company_name": "",
        "board_token": "",
        "source_url": "",
    }


def _validation_errors(exc: ValidationError) -> dict[str, str]:
    field_errors: dict[str, str] = {}
    for error in exc.errors():
        location = error.get("loc", [])
        if location:
            field_errors.setdefault(str(location[-1]), str(error["msg"]))
    return field_errors


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
