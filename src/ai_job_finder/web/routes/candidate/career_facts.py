from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from ai_job_finder.api.v1.schemas import (
    CareerFactCreateRequest,
    CareerFactTransitionRequest,
    CareerFactUpdateRequest,
)
from ai_job_finder.application.services import (
    create_career_fact,
    get_career_fact,
    get_primary_candidate_profile,
    list_career_facts,
    transition_career_fact,
    update_career_fact,
)
from ai_job_finder.domain.enums import (
    CareerFactCategory,
    CareerFactLifecycle,
    EvidenceTag,
    ProvenanceType,
)
from ai_job_finder.domain.errors import ArchivedCareerFactModificationError, NotFoundError
from ai_job_finder.web.dependencies import (
    DbSession,
    is_htmx_request,
    optional_str,
    render_template,
    split_multivalue,
)

router = APIRouter(tags=["web"])


def _validation_errors(exc: ValidationError) -> dict[str, str]:
    field_errors: dict[str, str] = {}
    for error in exc.errors():
        location = error.get("loc", [])
        if not location:
            continue
        field_name = str(location[-1])
        field_errors.setdefault(field_name, error["msg"])
    return field_errors


def _fact_form_defaults() -> dict[str, Any]:
    return {
        "category": CareerFactCategory.PLATFORM.value,
        "source_organization": "",
        "statement": "",
        "metric": "",
        "technologies": "",
        "leadership_scope": "",
        "business_outcome": "",
        "approved_wording": "",
        "evidence_tags": [],
        "provenance_type": ProvenanceType.OTHER.value,
        "source_reference": "",
    }


def _fact_form_values(fact: Any | None = None) -> dict[str, Any]:
    if fact is None:
        return _fact_form_defaults()
    return {
        "category": fact.category,
        "source_organization": fact.source_organization or "",
        "statement": fact.statement,
        "metric": fact.metric or "",
        "technologies": "\n".join(fact.technologies),
        "leadership_scope": fact.leadership_scope or "",
        "business_outcome": fact.business_outcome or "",
        "approved_wording": fact.approved_wording,
        "evidence_tags": list(fact.evidence_tags),
        "provenance_type": fact.provenance_type,
        "source_reference": fact.source_reference,
    }


def _fact_form_context(
    *,
    page_title: str,
    form_title: str,
    form_action: str,
    submit_label: str,
    values: dict[str, Any],
    errors: dict[str, str] | None = None,
    fact: Any | None = None,
    notice: str | None = None,
) -> dict[str, Any]:
    return {
        "page_title": page_title,
        "form_title": form_title,
        "form_action": form_action,
        "submit_label": submit_label,
        "form_values": values,
        "form_errors": errors or {},
        "category_options": list(CareerFactCategory),
        "evidence_tag_options": list(EvidenceTag),
        "provenance_options": list(ProvenanceType),
        "fact": fact,
        "notice": notice,
    }


def _fact_flash(flash: str | None) -> list[dict[str, str]]:
    flashes = {
        "fact-created": "Career fact created as draft.",
        "fact-updated": "Career fact updated.",
        "fact-verified": "Career fact verified.",
        "fact-drafted": "Career fact returned to draft.",
        "fact-archived": "Career fact archived.",
        "fact-restored": "Career fact restored to draft.",
    }
    if flash and flash in flashes:
        return [{"level": "success", "message": flashes[flash]}]
    return []


def _lifecycle_fragment_context(fact: Any, lifecycle_error: str | None = None) -> dict[str, Any]:
    return {
        "fact": fact,
        "lifecycle_error": lifecycle_error,
    }


@router.get("/career-facts")
def career_facts(
    request: Request,
    session: DbSession,
    lifecycle_status: str | None = None,
    category: str | None = None,
    source_organization: str | None = None,
    evidence_tag: str | None = None,
) -> Response:
    candidate = get_primary_candidate_profile(session)
    if candidate is None:
        return RedirectResponse(url="/candidate", status_code=status.HTTP_303_SEE_OTHER)

    selected_lifecycle = None
    selected_category = None
    selected_tag = None
    if lifecycle_status:
        try:
            selected_lifecycle = CareerFactLifecycle(lifecycle_status)
        except ValueError:
            selected_lifecycle = None
    if category:
        try:
            selected_category = CareerFactCategory(category)
        except ValueError:
            selected_category = None
    if evidence_tag:
        try:
            selected_tag = EvidenceTag(evidence_tag)
        except ValueError:
            selected_tag = None

    facts = list_career_facts(
        session,
        candidate.id,
        lifecycle_status=selected_lifecycle.value if selected_lifecycle else None,
        category=selected_category.value if selected_category else None,
        source_organization=optional_str(source_organization),
        evidence_tag=selected_tag.value if selected_tag else None,
        include_archived=selected_lifecycle is CareerFactLifecycle.ARCHIVED,
    )
    all_facts = list_career_facts(session, candidate.id, include_archived=True)
    organizations = sorted(
        {fact.source_organization for fact in all_facts if fact.source_organization}
    )
    return render_template(
        request,
        "candidate/career_facts.html",
        {
            "page_title": "Career Facts",
            "facts": facts,
            "category_options": list(CareerFactCategory),
            "lifecycle_options": list(CareerFactLifecycle),
            "evidence_tag_options": list(EvidenceTag),
            "organization_options": organizations,
            "selected_filters": {
                "lifecycle_status": selected_lifecycle.value if selected_lifecycle else "",
                "category": selected_category.value if selected_category else "",
                "source_organization": optional_str(source_organization) or "",
                "evidence_tag": selected_tag.value if selected_tag else "",
            },
            "has_filters": any([lifecycle_status, category, source_organization, evidence_tag]),
        },
    )


@router.get("/career-facts/new")
def career_fact_new(request: Request, session: DbSession) -> Response:
    candidate = get_primary_candidate_profile(session)
    if candidate is None:
        return RedirectResponse(url="/candidate", status_code=status.HTTP_303_SEE_OTHER)
    return render_template(
        request,
        "candidate/fact_form.html",
        _fact_form_context(
            page_title="New Career Fact",
            form_title="Create career fact",
            form_action="/career-facts",
            submit_label="Create draft fact",
            values=_fact_form_defaults(),
        ),
    )


@router.post("/career-facts")
async def career_fact_create(request: Request, session: DbSession) -> Response:
    candidate = get_primary_candidate_profile(session)
    if candidate is None:
        return RedirectResponse(url="/candidate", status_code=status.HTTP_303_SEE_OTHER)
    form = await request.form()
    values: dict[str, Any] = {
        "category": str(form.get("category", "")),
        "source_organization": str(form.get("source_organization", "")),
        "statement": str(form.get("statement", "")),
        "metric": str(form.get("metric", "")),
        "technologies": str(form.get("technologies", "")),
        "leadership_scope": str(form.get("leadership_scope", "")),
        "business_outcome": str(form.get("business_outcome", "")),
        "approved_wording": str(form.get("approved_wording", "")),
        "evidence_tags": [str(value) for value in form.getlist("evidence_tags")],
        "provenance_type": str(form.get("provenance_type", "")),
        "source_reference": str(form.get("source_reference", "")),
    }
    try:
        payload = CareerFactCreateRequest.model_validate(
            {
                "category": values["category"],
                "source_organization": optional_str(values["source_organization"]),
                "statement": values["statement"],
                "metric": optional_str(values["metric"]),
                "technologies": split_multivalue(values["technologies"]),
                "leadership_scope": optional_str(values["leadership_scope"]),
                "business_outcome": optional_str(values["business_outcome"]),
                "approved_wording": values["approved_wording"],
                "evidence_tags": values["evidence_tags"],
                "provenance_type": values["provenance_type"],
                "source_reference": values["source_reference"],
            }
        )
    except ValidationError as exc:
        return render_template(
            request,
            "candidate/fact_form.html",
            _fact_form_context(
                page_title="New Career Fact",
                form_title="Create career fact",
                form_action="/career-facts",
                submit_label="Create draft fact",
                values=values,
                errors=_validation_errors(exc),
            ),
            status_code=422,
        )

    fact = create_career_fact(
        session,
        candidate_profile_id=candidate.id,
        category=payload.category.value,
        source_organization=payload.source_organization,
        statement=payload.statement,
        metric=payload.metric,
        technologies=payload.technologies,
        leadership_scope=payload.leadership_scope,
        business_outcome=payload.business_outcome,
        approved_wording=payload.approved_wording,
        evidence_tags=[tag.value for tag in payload.evidence_tags],
        provenance_type=payload.provenance_type.value,
        source_reference=payload.source_reference,
    )
    return RedirectResponse(
        url=f"/career-facts/{fact.id}?flash=fact-created",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/career-facts/{fact_id}")
def career_fact_detail(
    request: Request,
    fact_id: UUID,
    session: DbSession,
    flash: str | None = None,
) -> Response:
    fact = get_career_fact(session, fact_id)
    return render_template(
        request,
        "candidate/fact_detail.html",
        {
            "page_title": "Career Fact Detail",
            "fact": fact,
            "flash_messages": _fact_flash(flash),
        },
    )


@router.get("/career-facts/{fact_id}/edit")
def career_fact_edit(request: Request, fact_id: UUID, session: DbSession) -> Response:
    fact = get_career_fact(session, fact_id)
    if fact.lifecycle_status == CareerFactLifecycle.ARCHIVED.value:
        return RedirectResponse(
            url=f"/career-facts/{fact.id}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    notice = None
    if fact.lifecycle_status == CareerFactLifecycle.VERIFIED.value:
        notice = "Saving material changes to a verified fact returns it to draft."
    return render_template(
        request,
        "candidate/fact_form.html",
        _fact_form_context(
            page_title="Edit Career Fact",
            form_title="Edit career fact",
            form_action=f"/career-facts/{fact.id}/edit",
            submit_label="Save fact",
            values=_fact_form_values(fact),
            fact=fact,
            notice=notice,
        ),
    )


@router.post("/career-facts/{fact_id}/edit")
async def career_fact_update(request: Request, fact_id: UUID, session: DbSession) -> Response:
    fact = get_career_fact(session, fact_id)
    form = await request.form()
    values: dict[str, Any] = {
        "category": str(form.get("category", "")),
        "source_organization": str(form.get("source_organization", "")),
        "statement": str(form.get("statement", "")),
        "metric": str(form.get("metric", "")),
        "technologies": str(form.get("technologies", "")),
        "leadership_scope": str(form.get("leadership_scope", "")),
        "business_outcome": str(form.get("business_outcome", "")),
        "approved_wording": str(form.get("approved_wording", "")),
        "evidence_tags": [str(value) for value in form.getlist("evidence_tags")],
        "provenance_type": str(form.get("provenance_type", "")),
        "source_reference": str(form.get("source_reference", "")),
    }
    try:
        payload = CareerFactUpdateRequest.model_validate(
            {
                "category": values["category"],
                "source_organization": optional_str(values["source_organization"]),
                "statement": values["statement"],
                "metric": optional_str(values["metric"]),
                "technologies": split_multivalue(values["technologies"]),
                "leadership_scope": optional_str(values["leadership_scope"]),
                "business_outcome": optional_str(values["business_outcome"]),
                "approved_wording": values["approved_wording"],
                "evidence_tags": values["evidence_tags"],
                "provenance_type": values["provenance_type"],
                "source_reference": values["source_reference"],
            }
        )
    except ValidationError as exc:
        return render_template(
            request,
            "candidate/fact_form.html",
            _fact_form_context(
                page_title="Edit Career Fact",
                form_title="Edit career fact",
                form_action=f"/career-facts/{fact.id}/edit",
                submit_label="Save fact",
                values=values,
                errors=_validation_errors(exc),
                fact=fact,
                notice=(
                    "Saving material changes to a verified fact returns it to draft."
                    if fact.lifecycle_status == CareerFactLifecycle.VERIFIED.value
                    else None
                ),
            ),
            status_code=422,
        )

    try:
        updated_fact = update_career_fact(
            session,
            fact_id=fact.id,
            category=payload.category.value,
            source_organization=payload.source_organization,
            statement=payload.statement,
            metric=payload.metric,
            technologies=payload.technologies,
            leadership_scope=payload.leadership_scope,
            business_outcome=payload.business_outcome,
            approved_wording=payload.approved_wording,
            evidence_tags=[tag.value for tag in payload.evidence_tags],
            provenance_type=payload.provenance_type.value,
            source_reference=payload.source_reference,
        )
    except ArchivedCareerFactModificationError as exc:
        return render_template(
            request,
            "candidate/fact_form.html",
            _fact_form_context(
                page_title="Edit Career Fact",
                form_title="Edit career fact",
                form_action=f"/career-facts/{fact.id}/edit",
                submit_label="Save fact",
                values=values,
                errors={"statement": str(exc)},
                fact=fact,
            ),
            status_code=409,
        )

    return RedirectResponse(
        url=f"/career-facts/{updated_fact.id}?flash=fact-updated",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/career-facts/{fact_id}/lifecycle")
async def career_fact_transition_action(
    request: Request,
    fact_id: UUID,
    session: DbSession,
) -> Response:
    current_fact = get_career_fact(session, fact_id)
    previous_status = current_fact.lifecycle_status
    form = await request.form()
    lifecycle_value = str(form.get("lifecycle_status", ""))
    htmx = is_htmx_request(request)
    try:
        payload = CareerFactTransitionRequest.model_validate({"lifecycle_status": lifecycle_value})
        fact = transition_career_fact(
            session,
            fact_id=fact_id,
            lifecycle_status=payload.lifecycle_status.value,
        )
    except ValidationError, ValueError:
        message = "Select a valid lifecycle action."
        if htmx:
            return render_template(
                request,
                "candidate/_fact_lifecycle.html",
                _lifecycle_fragment_context(current_fact, message),
                status_code=422,
            )
        return render_template(
            request,
            "candidate/fact_detail.html",
            {
                "page_title": "Career Fact Detail",
                "fact": current_fact,
                "flash_messages": [{"level": "error", "message": message}],
            },
            status_code=422,
        )
    except NotFoundError:
        raise
    except Exception as exc:
        if htmx:
            return render_template(
                request,
                "candidate/_fact_lifecycle.html",
                _lifecycle_fragment_context(current_fact, str(exc)),
                status_code=409,
            )
        return render_template(
            request,
            "candidate/fact_detail.html",
            {
                "page_title": "Career Fact Detail",
                "fact": current_fact,
                "flash_messages": [{"level": "error", "message": str(exc)}],
            },
            status_code=409,
        )

    if htmx:
        return render_template(
            request,
            "candidate/_fact_lifecycle.html",
            _lifecycle_fragment_context(fact),
        )

    flash = {
        CareerFactLifecycle.VERIFIED.value: "fact-verified",
        CareerFactLifecycle.ARCHIVED.value: "fact-archived",
        CareerFactLifecycle.DRAFT.value: (
            "fact-restored"
            if previous_status == CareerFactLifecycle.ARCHIVED.value
            else "fact-drafted"
        ),
    }[fact.lifecycle_status]
    return RedirectResponse(
        url=f"/career-facts/{fact.id}?flash={flash}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
