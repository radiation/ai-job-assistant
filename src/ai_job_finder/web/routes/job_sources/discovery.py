from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit
from uuid import UUID

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import RedirectResponse

from ai_job_finder.application.job_searches import list_job_search_definitions
from ai_job_finder.application.job_sources import (
    list_job_source_configurations,
    list_ranked_discovered_leads,
)
from ai_job_finder.application.services import update_job_lead_status
from ai_job_finder.domain.enums import (
    JobLocationEligibilityStatus,
    PostingStatus,
    Recommendation,
    SourcePostingStatus,
    WorkplaceType,
)
from ai_job_finder.domain.errors import NotFoundError
from ai_job_finder.web.dependencies import DbSession, optional_str, render_template

router = APIRouter(tags=["web"])


@dataclass(slots=True)
class DiscoveryQueueStats:
    total_discovered: int
    currently_shown: int
    actionable: int
    needs_review: int
    ineligible: int


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


@router.get("/discover")
def discover_queue(
    request: Request,
    session: DbSession,
    search_definition_id: str | None = None,
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
        parsed_search_definition_id = UUID(search_definition_id) if search_definition_id else None
    except ValueError:
        return _render_filter_error(request, "Saved search filter must be a valid identifier.")
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
        "search_definition_id": search_definition_id or "",
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
        search_definition_id=parsed_search_definition_id,
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
        search_definition_id=parsed_search_definition_id,
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
            "saved_searches": list_job_search_definitions(session),
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
    try:
        update_job_lead_status(session, job_id, PostingStatus(status_value).value)
    except ValueError:
        return _render_filter_error(request, "Select a valid posting status.")
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
    return RedirectResponse(url=redirect_target, status_code=status.HTTP_303_SEE_OTHER)
