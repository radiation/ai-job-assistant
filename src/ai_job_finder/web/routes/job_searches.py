from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from ai_job_finder.api.v1.schemas import JobSearchDefinitionCreateRequest
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
from ai_job_finder.domain.errors import DomainError, NotFoundError
from ai_job_finder.infrastructure.database.models import JobSearchDefinitionModel
from ai_job_finder.web.dependencies import DbSession, render_template, split_multivalue

router = APIRouter(tags=["web"])


@dataclass(slots=True)
class SearchListItem:
    search: JobSearchDefinitionModel
    run_count: int


def _form_defaults() -> dict[str, str]:
    return {
        "name": "",
        "title_include_patterns": "",
        "title_exclude_patterns": "",
        "target_domains": "",
        "target_seniority_levels": "",
        "allowed_locations": "",
        "allowed_remote_geographies": "",
        "allowed_workplace_types": "",
        "minimum_score_threshold": "70",
    }


def _values_from_search(search: JobSearchDefinitionModel) -> dict[str, str]:
    return {
        "name": str(search.name),
        "title_include_patterns": "\n".join(search.title_include_patterns),
        "title_exclude_patterns": "\n".join(search.title_exclude_patterns),
        "target_domains": "\n".join(search.target_domains),
        "target_seniority_levels": "\n".join(search.target_seniority_levels),
        "allowed_locations": "\n".join(search.allowed_locations),
        "allowed_remote_geographies": "\n".join(search.allowed_remote_geographies),
        "allowed_workplace_types": "\n".join(search.allowed_workplace_types),
        "minimum_score_threshold": f"{search.minimum_score_threshold:g}",
    }


def _validation_errors(exc: ValidationError) -> dict[str, str]:
    field_errors: dict[str, str] = {}
    for error in exc.errors():
        location = error.get("loc", [])
        if location:
            field_errors.setdefault(str(location[-1]), str(error["msg"]))
    return field_errors


def _parse_form(values: dict[str, str]) -> JobSearchDefinitionCreateRequest:
    return JobSearchDefinitionCreateRequest.model_validate(
        {
            "name": values["name"],
            "enabled": True,
            "title_include_patterns": split_multivalue(values["title_include_patterns"]),
            "title_exclude_patterns": split_multivalue(values["title_exclude_patterns"]),
            "target_domains": split_multivalue(values["target_domains"]),
            "target_seniority_levels": split_multivalue(values["target_seniority_levels"]),
            "allowed_locations": split_multivalue(values["allowed_locations"]),
            "allowed_remote_geographies": split_multivalue(values["allowed_remote_geographies"]),
            "allowed_workplace_types": split_multivalue(values["allowed_workplace_types"]),
            "minimum_score_threshold": values["minimum_score_threshold"],
        }
    )


@router.get("/job-searches")
def job_searches_list(request: Request, session: DbSession) -> Response:
    items = [
        SearchListItem(search=search, run_count=len(search.runs))
        for search in list_job_search_definitions(session)
    ]
    return render_template(
        request,
        "job_searches/list.html",
        {"page_title": "Saved Searches", "search_items": items},
    )


@router.get("/job-searches/new")
def job_searches_new(request: Request) -> Response:
    return render_template(
        request,
        "job_searches/new.html",
        {"page_title": "New Saved Search", "form_values": _form_defaults(), "form_errors": {}},
    )


@router.post("/job-searches")
async def job_searches_create(request: Request, session: DbSession) -> Response:
    form = await request.form()
    values = {field: str(form.get(field, "")) for field in _form_defaults()}
    try:
        payload = _parse_form(values)
    except ValidationError as exc:
        return render_template(
            request,
            "job_searches/new.html",
            {
                "page_title": "New Saved Search",
                "form_values": values,
                "form_errors": _validation_errors(exc),
            },
            status_code=422,
        )
    try:
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
    except DomainError as exc:
        return render_template(
            request,
            "job_searches/new.html",
            {
                "page_title": "New Saved Search",
                "form_values": values,
                "form_errors": {"name": str(exc)},
            },
            status_code=409,
        )
    return RedirectResponse(
        url=f"/job-searches/{search.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/job-searches/{search_definition_id}")
def job_searches_detail(
    request: Request,
    search_definition_id: UUID,
    session: DbSession,
) -> Response:
    try:
        search = get_job_search_definition(session, search_definition_id)
    except NotFoundError as exc:
        return render_template(
            request,
            "errors/error.html",
            {
                "page_title": "Saved Search Not Found",
                "title": "Saved search not found",
                "message": str(exc),
            },
            status_code=404,
        )
    return render_template(
        request,
        "job_searches/detail.html",
        {
            "page_title": search.name,
            "search": search,
            "runs": list_job_search_runs(session, search_definition_id=search.id),
            "form_values": _values_from_search(search),
            "form_errors": {},
        },
    )


@router.post("/job-searches/{search_definition_id}")
async def job_searches_update(
    request: Request,
    search_definition_id: UUID,
    session: DbSession,
) -> Response:
    form = await request.form()
    values = {field: str(form.get(field, "")) for field in _form_defaults()}
    try:
        payload = _parse_form(values)
    except ValidationError as exc:
        search = get_job_search_definition(session, search_definition_id)
        return render_template(
            request,
            "job_searches/detail.html",
            {
                "page_title": search.name,
                "search": search,
                "runs": list_job_search_runs(session, search_definition_id=search.id),
                "form_values": values,
                "form_errors": _validation_errors(exc),
            },
            status_code=422,
        )
    try:
        update_job_search_definition(
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
    except DomainError as exc:
        search = get_job_search_definition(session, search_definition_id)
        return render_template(
            request,
            "job_searches/detail.html",
            {
                "page_title": search.name,
                "search": search,
                "runs": list_job_search_runs(session, search_definition_id=search.id),
                "form_values": values,
                "form_errors": {"name": str(exc)},
            },
            status_code=409,
        )
    return RedirectResponse(
        url=f"/job-searches/{search_definition_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/job-searches/{search_definition_id}/enable")
def job_searches_enable(search_definition_id: UUID, session: DbSession) -> Response:
    set_job_search_definition_enabled(
        session,
        search_definition_id=search_definition_id,
        enabled=True,
    )
    return RedirectResponse(
        url=f"/job-searches/{search_definition_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/job-searches/{search_definition_id}/disable")
def job_searches_disable(search_definition_id: UUID, session: DbSession) -> Response:
    set_job_search_definition_enabled(
        session,
        search_definition_id=search_definition_id,
        enabled=False,
    )
    return RedirectResponse(
        url=f"/job-searches/{search_definition_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/job-searches/{search_definition_id}/runs")
def job_searches_run(search_definition_id: UUID, session: DbSession) -> Response:
    run = run_job_search(session, search_definition_id=search_definition_id)
    return RedirectResponse(url=f"/job-search-runs/{run.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/job-search-runs/{run_id}")
def job_search_runs_detail(request: Request, run_id: UUID, session: DbSession) -> Response:
    run = get_job_search_run(session, run_id)
    return render_template(
        request,
        "job_searches/run_detail.html",
        {
            "page_title": f"Saved Search Run {run.id}",
            "run": run,
            "search": get_job_search_definition(session, run.search_definition_id),
            "match_records": list_job_search_matches(session, search_run_id=run_id),
        },
    )
