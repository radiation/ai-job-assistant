from __future__ import annotations

from fastapi import APIRouter

from ai_job_finder.web.routes.candidate.career_facts import router as career_facts_router
from ai_job_finder.web.routes.candidate.profile import router as profile_router

router = APIRouter()
router.include_router(profile_router)
router.include_router(career_facts_router)
