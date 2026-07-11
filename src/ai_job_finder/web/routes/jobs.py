from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from ai_job_finder.api.v1.schemas import JobLeadCreateRequest
from ai_job_finder.application.services import (
    create_job_evaluation,
    create_job_lead,
    get_job_lead,
    get_latest_job_evaluation,
    get_primary_candidate_profile,
    list_job_leads,
    update_job_lead_status,
)
from ai_job_finder.domain.enums import JobLeadSource, PostingStatus, WorkplaceType
from ai_job_finder.domain.errors import EvaluationPreconditionError, NotFoundError
from ai_job_finder.web.dependencies import (
    DbSession,
    is_htmx_request,
    latest_evaluation,
    optional_str,
    render_template,
)

router = APIRouter(tags=["web"])


@dataclass(slots=True)
class JobLeadListItem:
    job: Any
    latest_evaluation: Any | None


def _job_form_defaults() -> dict[str, str]:
    return {
        "source": JobLeadSource.MANUAL.value,
        "source_url": "",
        "external_id": "",
        "company_name": "",
        "title": "",
        "location_text": "",
        "workplace_type": "",
        "description_raw": "",
        "compensation_text": "",
    }


def _job_form_context(
    *,
    page_title: str,
    values: dict[str, str],
    errors: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "page_title": page_title,
        "form_values": values,
        "form_errors": errors or {},
        "source_options": list(JobLeadSource),
        "workplace_options": list(WorkplaceType),
    }


def _validation_errors(exc: ValidationError) -> dict[str, str]:
    field_errors: dict[str, str] = {}
    for error in exc.errors():
        location = error.get("loc", [])
        if not location:
            continue
        field_name = str(location[-1])
        field_errors.setdefault(field_name, error["msg"])
    return field_errors


def _detail_context(
    session: DbSession,
    request: Request,
    job_id: UUID,
    *,
    flash: str | None = None,
    status_error: str | None = None,
    evaluation_error: str | None = None,
) -> dict[str, Any]:
    job = get_job_lead(session, job_id)
    try:
        evaluation = get_latest_job_evaluation(session, job_id)
    except NotFoundError:
        evaluation = None

    flash_messages: list[dict[str, str]] = []
    if flash == "job-created":
        flash_messages.append({"level": "success", "message": "Job lead created."})
    if flash == "status-updated":
        flash_messages.append({"level": "success", "message": "Posting status updated."})
    if flash == "evaluation-created":
        flash_messages.append({"level": "success", "message": "Evaluation created."})

    return {
        "page_title": f"{job.company_name} · {job.title}",
        "job": job,
        "evaluation": evaluation,
        "posting_statuses": list(PostingStatus),
        "flash_messages": flash_messages,
        "status_error": status_error,
        "evaluation_error": evaluation_error,
        "request": request,
    }


@router.get("/")
def root() -> Response:
    return RedirectResponse(url="/jobs", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/jobs")
def jobs_list(
    request: Request,
    session: DbSession,
    posting_status: str | None = None,
) -> Response:
    status_filter = None
    if posting_status:
        try:
            status_filter = PostingStatus(posting_status)
        except ValueError:
            status_filter = None

    jobs = list_job_leads(
        session,
        posting_status=status_filter.value if status_filter is not None else None,
    )
    items = [
        JobLeadListItem(job=job, latest_evaluation=latest_evaluation(job.evaluations))
        for job in jobs
    ]
    return render_template(
        request,
        "jobs/list.html",
        {
            "page_title": "Job Leads",
            "job_items": items,
            "posting_statuses": list(PostingStatus),
            "selected_status": status_filter.value if status_filter is not None else "",
        },
    )


@router.get("/jobs/new")
def jobs_new(request: Request) -> Response:
    return render_template(
        request,
        "jobs/new.html",
        _job_form_context(page_title="New Job Lead", values=_job_form_defaults()),
    )


@router.post("/jobs")
async def jobs_create(request: Request, session: DbSession) -> Response:
    form = await request.form()
    values = {field: str(form.get(field, "")) for field in _job_form_defaults()}
    try:
        payload = JobLeadCreateRequest.model_validate(
            {
                "source": values["source"],
                "source_url": optional_str(values["source_url"]),
                "external_id": optional_str(values["external_id"]),
                "company_name": values["company_name"],
                "title": values["title"],
                "location_text": optional_str(values["location_text"]),
                "workplace_type": optional_str(values["workplace_type"]),
                "description_raw": values["description_raw"],
                "description_normalized": values["description_raw"],
                "compensation_text": optional_str(values["compensation_text"]),
            }
        )
    except ValidationError as exc:
        return render_template(
            request,
            "jobs/new.html",
            _job_form_context(
                page_title="New Job Lead",
                values=values,
                errors=_validation_errors(exc),
            ),
            status_code=422,
        )

    job = create_job_lead(
        session,
        source=payload.source.value,
        source_url=payload.source_url,
        external_id=payload.external_id,
        company_name=payload.company_name,
        title=payload.title,
        location_text=payload.location_text,
        workplace_type=payload.workplace_type.value if payload.workplace_type else None,
        description_raw=payload.description_raw,
        description_normalized=None,
        compensation_text=payload.compensation_text,
    )
    return RedirectResponse(
        url=f"/jobs/{job.id}?flash=job-created",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/jobs/{job_id}")
def jobs_detail(
    request: Request,
    job_id: UUID,
    session: DbSession,
    flash: str | None = None,
) -> Response:
    try:
        context = _detail_context(session, request, job_id, flash=flash)
    except NotFoundError as exc:
        return render_template(
            request,
            "errors/error.html",
            {
                "page_title": "Job Lead Not Found",
                "title": "Job lead not found",
                "message": str(exc),
            },
            status_code=404,
        )
    return render_template(request, "jobs/detail.html", context)


@router.post("/jobs/{job_id}/status")
async def jobs_update_status(request: Request, job_id: UUID, session: DbSession) -> Response:
    form = await request.form()
    posting_status = str(form.get("posting_status", ""))
    htmx = is_htmx_request(request)
    try:
        job = update_job_lead_status(session, job_id, PostingStatus(posting_status).value)
    except (NotFoundError, ValueError) as exc:
        status_error = "Select a valid posting status." if isinstance(exc, ValueError) else str(exc)
        if htmx:
            job = get_job_lead(session, job_id)
            return render_template(
                request,
                "jobs/_status.html",
                {
                    "job": job,
                    "posting_statuses": list(PostingStatus),
                    "status_error": status_error,
                },
                status_code=404 if isinstance(exc, NotFoundError) else 422,
            )
        if isinstance(exc, NotFoundError):
            return render_template(
                request,
                "errors/error.html",
                {
                    "page_title": "Job Lead Not Found",
                    "title": "Job lead not found",
                    "message": str(exc),
                },
                status_code=404,
            )
        context = _detail_context(session, request, job_id, status_error=status_error)
        return render_template(request, "jobs/detail.html", context, status_code=422)
    except Exception as exc:
        if htmx:
            job = get_job_lead(session, job_id)
            return render_template(
                request,
                "jobs/_status.html",
                {
                    "job": job,
                    "posting_statuses": list(PostingStatus),
                    "status_error": str(exc),
                },
                status_code=409,
            )
        context = _detail_context(session, request, job_id, status_error=str(exc))
        return render_template(request, "jobs/detail.html", context, status_code=409)

    if htmx:
        return render_template(
            request,
            "jobs/_status.html",
            {
                "job": job,
                "posting_statuses": list(PostingStatus),
                "status_error": None,
            },
        )
    return RedirectResponse(
        url=f"/jobs/{job.id}?flash=status-updated",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/jobs/{job_id}/evaluation")
def jobs_create_evaluation(request: Request, job_id: UUID, session: DbSession) -> Response:
    htmx = is_htmx_request(request)
    candidate = get_primary_candidate_profile(session)
    if candidate is None:
        message = "Create a candidate profile before evaluating job leads."
        if htmx:
            job = get_job_lead(session, job_id)
            return render_template(
                request,
                "jobs/_evaluation.html",
                {
                    "job": job,
                    "evaluation": None,
                    "evaluation_error": message,
                },
                status_code=409,
            )
        context = _detail_context(session, request, job_id, evaluation_error=message)
        return render_template(request, "jobs/detail.html", context, status_code=409)

    try:
        create_job_evaluation(session, job_lead_id=job_id, candidate_profile_id=candidate.id)
    except EvaluationPreconditionError as exc:
        job = get_job_lead(session, job_id)
        try:
            evaluation = get_latest_job_evaluation(session, job_id)
        except NotFoundError:
            evaluation = None
        if htmx:
            return render_template(
                request,
                "jobs/_evaluation.html",
                {
                    "job": job,
                    "evaluation": evaluation,
                    "evaluation_error": str(exc),
                },
                status_code=409,
            )
        context = _detail_context(session, request, job_id, evaluation_error=str(exc))
        return render_template(request, "jobs/detail.html", context, status_code=409)

    job = get_job_lead(session, job_id)
    evaluation = get_latest_job_evaluation(session, job_id)
    if htmx:
        return render_template(
            request,
            "jobs/_evaluation.html",
            {
                "job": job,
                "evaluation": evaluation,
                "evaluation_error": None,
            },
        )
    return RedirectResponse(
        url=f"/jobs/{job.id}?flash=evaluation-created",
        status_code=status.HTTP_303_SEE_OTHER,
    )
