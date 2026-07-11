from __future__ import annotations

from fastapi import APIRouter, Request, Response

from ai_job_finder.application.services import get_primary_candidate_profile, list_career_facts
from ai_job_finder.domain.enums import VerificationStatus
from ai_job_finder.web.dependencies import DbSession, render_template

router = APIRouter(tags=["web"])


@router.get("/candidate")
def candidate_profile(request: Request, session: DbSession) -> Response:
    candidate = get_primary_candidate_profile(session)
    return render_template(
        request,
        "candidate/profile.html",
        {
            "page_title": "Candidate Profile",
            "candidate": candidate,
        },
    )


@router.get("/career-facts")
def career_facts(request: Request, session: DbSession) -> Response:
    candidate = get_primary_candidate_profile(session)
    facts = list_career_facts(session, candidate.id) if candidate is not None else []
    verified_facts = [
        fact for fact in facts if fact.verification_status == VerificationStatus.VERIFIED.value
    ]
    unverified_facts = [
        fact for fact in facts if fact.verification_status != VerificationStatus.VERIFIED.value
    ]
    return render_template(
        request,
        "candidate/career_facts.html",
        {
            "page_title": "Career Facts",
            "candidate": candidate,
            "verified_facts": verified_facts,
            "unverified_facts": unverified_facts,
        },
    )
