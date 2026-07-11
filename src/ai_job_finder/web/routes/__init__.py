from __future__ import annotations

from fastapi import APIRouter

from ai_job_finder.web.routes.candidate import router as candidate_router
from ai_job_finder.web.routes.jobs import router as jobs_router

router = APIRouter()
router.include_router(jobs_router)
router.include_router(candidate_router)
