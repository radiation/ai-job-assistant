from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from ai_job_finder.api.v1.schemas import (
    CandidateProfileCreateRequest,
    CandidateProfileUpdateRequest,
)
from ai_job_finder.application.services import (
    create_candidate_profile,
    get_primary_candidate_profile,
    update_candidate_profile,
)
from ai_job_finder.domain.enums import (
    RemotePreference,
)
from ai_job_finder.web.dependencies import (
    DbSession,
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


def _candidate_form_defaults() -> dict[str, str]:
    return {
        "full_name": "",
        "preferred_locations": "",
        "acceptable_remote_geographies": "",
        "remote_preference": RemotePreference.FLEXIBLE.value,
        "target_levels": "",
        "target_functions": "",
    }


def _candidate_form_values(candidate: Any | None = None) -> dict[str, str]:
    if candidate is None:
        return _candidate_form_defaults()
    return {
        "full_name": candidate.full_name,
        "preferred_locations": "\n".join(candidate.preferred_locations),
        "acceptable_remote_geographies": "\n".join(candidate.acceptable_remote_geographies),
        "remote_preference": candidate.remote_preference,
        "target_levels": "\n".join(candidate.target_levels),
        "target_functions": "\n".join(candidate.target_functions),
    }


def _candidate_form_context(
    *,
    page_title: str,
    form_title: str,
    form_action: str,
    submit_label: str,
    values: dict[str, str],
    errors: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "page_title": page_title,
        "form_title": form_title,
        "form_action": form_action,
        "submit_label": submit_label,
        "form_values": values,
        "form_errors": errors or {},
        "remote_preferences": list(RemotePreference),
    }


def _candidate_flash(flash: str | None) -> list[dict[str, str]]:
    flashes = {
        "candidate-created": "Candidate profile created.",
        "candidate-updated": "Candidate profile updated.",
    }
    if flash and flash in flashes:
        return [{"level": "success", "message": flashes[flash]}]
    return []


@router.get("/candidate")
def candidate_profile(request: Request, session: DbSession, flash: str | None = None) -> Response:
    candidate = get_primary_candidate_profile(session)
    if candidate is None:
        return render_template(
            request,
            "candidate/form.html",
            _candidate_form_context(
                page_title="Candidate Setup",
                form_title="First-run candidate setup",
                form_action="/candidate",
                submit_label="Create candidate profile",
                values=_candidate_form_defaults(),
            ),
        )
    return render_template(
        request,
        "candidate/profile.html",
        {
            "page_title": "Candidate Profile",
            "candidate": candidate,
            "flash_messages": _candidate_flash(flash),
        },
    )


@router.post("/candidate")
async def candidate_create(request: Request, session: DbSession) -> Response:
    form = await request.form()
    values = {
        "full_name": str(form.get("full_name", "")),
        "preferred_locations": str(form.get("preferred_locations", "")),
        "acceptable_remote_geographies": str(form.get("acceptable_remote_geographies", "")),
        "remote_preference": str(form.get("remote_preference", "")),
        "target_levels": str(form.get("target_levels", "")),
        "target_functions": str(form.get("target_functions", "")),
    }
    try:
        payload = CandidateProfileCreateRequest.model_validate(
            {
                "full_name": values["full_name"],
                "preferred_locations": split_multivalue(values["preferred_locations"]),
                "acceptable_remote_geographies": split_multivalue(
                    values["acceptable_remote_geographies"]
                ),
                "remote_preference": values["remote_preference"],
                "target_levels": split_multivalue(values["target_levels"]),
                "target_functions": split_multivalue(values["target_functions"]),
            }
        )
    except ValidationError as exc:
        return render_template(
            request,
            "candidate/form.html",
            _candidate_form_context(
                page_title="Candidate Setup",
                form_title="First-run candidate setup",
                form_action="/candidate",
                submit_label="Create candidate profile",
                values=values,
                errors=_validation_errors(exc),
            ),
            status_code=422,
        )

    create_candidate_profile(
        session,
        full_name=payload.full_name,
        preferred_locations=payload.preferred_locations,
        acceptable_remote_geographies=payload.acceptable_remote_geographies,
        remote_preference=payload.remote_preference.value,
        target_levels=payload.target_levels,
        target_functions=payload.target_functions,
    )
    return RedirectResponse(
        url="/candidate?flash=candidate-created",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/candidate/edit")
def candidate_edit(request: Request, session: DbSession) -> Response:
    candidate = get_primary_candidate_profile(session)
    if candidate is None:
        return RedirectResponse(url="/candidate", status_code=status.HTTP_303_SEE_OTHER)
    return render_template(
        request,
        "candidate/form.html",
        _candidate_form_context(
            page_title="Edit Candidate Profile",
            form_title="Edit candidate profile",
            form_action="/candidate/edit",
            submit_label="Save candidate profile",
            values=_candidate_form_values(candidate),
        ),
    )


@router.post("/candidate/edit")
async def candidate_update(request: Request, session: DbSession) -> Response:
    candidate = get_primary_candidate_profile(session)
    if candidate is None:
        return RedirectResponse(url="/candidate", status_code=status.HTTP_303_SEE_OTHER)
    form = await request.form()
    values = {
        "full_name": str(form.get("full_name", "")),
        "preferred_locations": str(form.get("preferred_locations", "")),
        "acceptable_remote_geographies": str(form.get("acceptable_remote_geographies", "")),
        "remote_preference": str(form.get("remote_preference", "")),
        "target_levels": str(form.get("target_levels", "")),
        "target_functions": str(form.get("target_functions", "")),
    }
    try:
        payload = CandidateProfileUpdateRequest.model_validate(
            {
                "full_name": values["full_name"],
                "preferred_locations": split_multivalue(values["preferred_locations"]),
                "acceptable_remote_geographies": split_multivalue(
                    values["acceptable_remote_geographies"]
                ),
                "remote_preference": values["remote_preference"],
                "target_levels": split_multivalue(values["target_levels"]),
                "target_functions": split_multivalue(values["target_functions"]),
            }
        )
    except ValidationError as exc:
        return render_template(
            request,
            "candidate/form.html",
            _candidate_form_context(
                page_title="Edit Candidate Profile",
                form_title="Edit candidate profile",
                form_action="/candidate/edit",
                submit_label="Save candidate profile",
                values=values,
                errors=_validation_errors(exc),
            ),
            status_code=422,
        )

    update_candidate_profile(
        session,
        candidate_profile_id=candidate.id,
        full_name=payload.full_name,
        preferred_locations=payload.preferred_locations,
        acceptable_remote_geographies=payload.acceptable_remote_geographies,
        remote_preference=payload.remote_preference.value,
        target_levels=payload.target_levels,
        target_functions=payload.target_functions,
    )
    return RedirectResponse(
        url="/candidate?flash=candidate-updated",
        status_code=status.HTTP_303_SEE_OTHER,
    )
