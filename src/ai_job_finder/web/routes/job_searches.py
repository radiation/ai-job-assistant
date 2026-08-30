from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from pydantic_core import ErrorDetails

from ai_job_finder.api.v1.routes.dependencies import (
    JobDiscoveryProviderDependency,
    JobSourceBoardValidatorDependency,
    JobSourceConnectorDependency,
    PublicPageFetcherDependency,
    SettingsDependency,
)
from ai_job_finder.api.v1.schemas import JobSearchDefinitionCreateRequest
from ai_job_finder.application.job_discovery import (
    DAILY_DISCOVERY_CADENCE,
    JobDiscoveryConfig,
    configure_scheduled_discovery,
    get_job_discovery_run_detail,
    list_actionable_notifications,
    list_job_discovery_runs,
    run_job_discovery,
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
from ai_job_finder.application.source_detection import SourceDetectionConfig
from ai_job_finder.domain.enums import WorkplaceType
from ai_job_finder.domain.errors import DomainError, NotFoundError
from ai_job_finder.domain.job_searches import JobSearchDomain, JobSearchSeniority
from ai_job_finder.infrastructure.database.models import JobSearchDefinitionModel
from ai_job_finder.web.dependencies import DbSession, render_template, split_multivalue

router = APIRouter(tags=["web"])
_RUN_DETAIL_PAGE_SIZE = 100

_CHECKBOX_FIELDS = {
    "target_domains",
    "target_seniority_levels",
    "allowed_workplace_types",
}

_FIELD_LABEL_OVERRIDES = {
    "vice_president": "VP",
}

_FIELD_LABELS = {
    "name": "Name",
    "title_include_patterns": "Title include pattern",
    "title_exclude_patterns": "Title exclude pattern",
    "target_domains": "Target domain",
    "target_seniority_levels": "Target seniority level",
    "allowed_locations": "Allowed location",
    "allowed_remote_geographies": "Allowed remote geography",
    "allowed_workplace_types": "Allowed workplace type",
    "minimum_score_threshold": "Minimum score threshold",
}


@dataclass(slots=True)
class SearchListItem:
    search: JobSearchDefinitionModel
    run_count: int


@dataclass(frozen=True, slots=True)
class FormOption:
    value: str
    label: str


def _display_label(value: str) -> str:
    return _FIELD_LABEL_OVERRIDES.get(value, value.replace("_", " ").title())


def _options_for(
    enum_type: type[JobSearchDomain] | type[JobSearchSeniority] | type[WorkplaceType],
) -> list[FormOption]:
    return [
        FormOption(value=option.value, label=_display_label(option.value)) for option in enum_type
    ]


def _form_defaults() -> dict[str, Any]:
    return {
        "name": "",
        "title_include_patterns": "",
        "title_exclude_patterns": "",
        "target_domains": [],
        "target_seniority_levels": [],
        "allowed_locations": "",
        "allowed_remote_geographies": "",
        "allowed_workplace_types": [],
        "minimum_score_threshold": "70",
    }


def _values_from_search(search: JobSearchDefinitionModel) -> dict[str, Any]:
    return {
        "name": str(search.name),
        "title_include_patterns": "\n".join(search.title_include_patterns),
        "title_exclude_patterns": "\n".join(search.title_exclude_patterns),
        "target_domains": list(search.target_domains),
        "target_seniority_levels": list(search.target_seniority_levels),
        "allowed_locations": "\n".join(search.allowed_locations),
        "allowed_remote_geographies": "\n".join(search.allowed_remote_geographies),
        "allowed_workplace_types": list(search.allowed_workplace_types),
        "minimum_score_threshold": f"{search.minimum_score_threshold:g}",
    }


def _form_context(
    *,
    page_title: str,
    values: dict[str, Any],
    errors: dict[str, str] | None = None,
) -> dict[str, Any]:
    field_errors = errors or {}
    return {
        "page_title": page_title,
        "form_values": values,
        "form_errors": field_errors,
        "form_error_summary": list(dict.fromkeys(field_errors.values())),
        "domain_options": _options_for(JobSearchDomain),
        "seniority_options": _options_for(JobSearchSeniority),
        "workplace_type_options": _options_for(WorkplaceType),
    }


def _validation_error_field(error: ErrorDetails) -> str | None:
    for item in error.get("loc", []):
        if isinstance(item, str):
            return item
    return None


def _format_validation_error(field_name: str, error: ErrorDetails) -> str:
    error_type = str(error.get("type", ""))
    value = error.get("input")

    if field_name == "name" and error_type == "string_too_short":
        return "Name is required."

    if field_name == "minimum_score_threshold":
        if error_type in {"float_parsing", "float_type"}:
            return "Minimum score threshold must be a number between 0 and 100."
        if error_type in {"greater_than_equal", "less_than_equal"}:
            return "Minimum score threshold must be between 0 and 100."

    if error_type == "enum":
        return (
            f'{_FIELD_LABELS.get(field_name, field_name.replace("_", " "))} "{value}" is not valid.'
        )

    return str(error["msg"])


def _validation_errors(exc: ValidationError) -> dict[str, str]:
    field_errors: dict[str, str] = {}
    for error in exc.errors():
        field_name = _validation_error_field(error)
        if field_name is None:
            continue
        field_errors.setdefault(field_name, _format_validation_error(field_name, error))
    return field_errors


def _selected_values(raw_values: list[str]) -> list[str]:
    selected: list[str] = []
    for raw_value in raw_values:
        for value in split_multivalue(raw_value):
            if value not in selected:
                selected.append(value)
    return selected


def _read_form_values(form: Any) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field, default in _form_defaults().items():
        if field in _CHECKBOX_FIELDS:
            values[field] = _selected_values([str(value) for value in form.getlist(field)])
            continue
        values[field] = str(form.get(field, default))
    return values


def _parse_form(values: dict[str, Any]) -> JobSearchDefinitionCreateRequest:
    return JobSearchDefinitionCreateRequest.model_validate(
        {
            "name": values["name"],
            "enabled": True,
            "title_include_patterns": split_multivalue(values["title_include_patterns"]),
            "title_exclude_patterns": split_multivalue(values["title_exclude_patterns"]),
            "target_domains": values["target_domains"],
            "target_seniority_levels": values["target_seniority_levels"],
            "allowed_locations": split_multivalue(values["allowed_locations"]),
            "allowed_remote_geographies": split_multivalue(values["allowed_remote_geographies"]),
            "allowed_workplace_types": values["allowed_workplace_types"],
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
        _form_context(page_title="New Saved Search", values=_form_defaults()),
    )


@router.post("/job-searches")
async def job_searches_create(request: Request, session: DbSession) -> Response:
    form = await request.form()
    values = _read_form_values(form)
    try:
        payload = _parse_form(values)
    except ValidationError as exc:
        return render_template(
            request,
            "job_searches/new.html",
            _form_context(
                page_title="New Saved Search",
                values=values,
                errors=_validation_errors(exc),
            ),
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
            _form_context(
                page_title="New Saved Search",
                values=values,
                errors={"name": str(exc)},
            ),
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
            "discovery_runs": list_job_discovery_runs(session, search_definition_id=search.id),
            "notifications": list_actionable_notifications(session, search_definition_id=search.id),
            **_form_context(page_title=search.name, values=_values_from_search(search)),
        },
    )


@router.post("/job-searches/{search_definition_id}")
async def job_searches_update(
    request: Request,
    search_definition_id: UUID,
    session: DbSession,
) -> Response:
    form = await request.form()
    values = _read_form_values(form)
    try:
        payload = _parse_form(values)
    except ValidationError as exc:
        errors = _validation_errors(exc)
        search = get_job_search_definition(session, search_definition_id)
        return render_template(
            request,
            "job_searches/detail.html",
            {
                "page_title": search.name,
                "search": search,
                "runs": list_job_search_runs(session, search_definition_id=search.id),
                "discovery_runs": list_job_discovery_runs(session, search_definition_id=search.id),
                "notifications": list_actionable_notifications(
                    session, search_definition_id=search.id
                ),
                **_form_context(page_title=search.name, values=values, errors=errors),
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
                "discovery_runs": list_job_discovery_runs(session, search_definition_id=search.id),
                "notifications": list_actionable_notifications(
                    session, search_definition_id=search.id
                ),
                **_form_context(page_title=search.name, values=values, errors={"name": str(exc)}),
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


@router.post("/job-searches/{search_definition_id}/discovery-schedule")
async def job_searches_update_discovery_schedule(
    request: Request,
    search_definition_id: UUID,
    session: DbSession,
) -> Response:
    form = await request.form()
    configure_scheduled_discovery(
        session,
        search_definition_id=search_definition_id,
        enabled=str(form.get("enabled", "false")).casefold() == "true",
        cadence=DAILY_DISCOVERY_CADENCE,
    )
    return RedirectResponse(
        url=f"/job-searches/{search_definition_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/job-searches/{search_definition_id}/runs")
def job_searches_run(search_definition_id: UUID, session: DbSession) -> Response:
    run = run_job_search(session, search_definition_id=search_definition_id)
    return RedirectResponse(url=f"/job-search-runs/{run.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/job-searches/{search_definition_id}/discovery-runs")
def job_searches_run_discovery(
    search_definition_id: UUID,
    session: DbSession,
    provider: JobDiscoveryProviderDependency,
    fetcher: PublicPageFetcherDependency,
    board_validator: JobSourceBoardValidatorDependency,
    connector: JobSourceConnectorDependency,
    settings: SettingsDependency,
) -> Response:
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
    return RedirectResponse(
        url=f"/job-discovery-runs/{run.id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/job-search-runs/{run_id}")
def job_search_runs_detail(
    request: Request,
    run_id: UUID,
    session: DbSession,
    page: int = 1,
) -> Response:
    run = get_job_search_run(session, run_id)
    current_page = max(page, 1)
    match_record_count = run.candidates_considered - run.failures_count
    match_offset = (current_page - 1) * _RUN_DETAIL_PAGE_SIZE
    match_records = list_job_search_matches(
        session,
        search_run_id=run_id,
        limit=_RUN_DETAIL_PAGE_SIZE,
        offset=match_offset,
    )
    return render_template(
        request,
        "job_searches/run_detail.html",
        {
            "page_title": f"Saved Search Run {run.id}",
            "run": run,
            "search": get_job_search_definition(session, run.search_definition_id),
            "match_records": match_records,
            "match_record_count": match_record_count,
            "matched_count": run.candidates_considered - run.excluded_count,
            "current_page": current_page,
            "has_previous_page": current_page > 1,
            "has_next_page": match_offset + len(match_records) < match_record_count,
            "page_start": match_offset + 1 if match_records else 0,
            "page_end": match_offset + len(match_records),
        },
    )


@router.get("/job-discovery-runs/{run_id}")
def job_discovery_runs_detail(request: Request, run_id: UUID, session: DbSession) -> Response:
    detail = get_job_discovery_run_detail(session, run_id)
    search = get_job_search_definition(session, detail.run.search_definition_id)
    return render_template(
        request,
        "job_searches/discovery_run_detail.html",
        {
            "page_title": f"Discovery Run {detail.run.id}",
            "run": detail.run,
            "search": search,
            "detail": detail,
        },
    )
