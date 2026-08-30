from __future__ import annotations

from fastapi import APIRouter, Depends

from ai_job_finder.api.dependencies import current_user_dependency
from ai_job_finder.api.security import csrf_protection_dependency
from ai_job_finder.api.v1.routes import (
    auth,
    candidate,
    career_facts,
    documents,
    health,
    job_discovery,
    job_searches,
    job_sources,
    jobs,
    proposals,
    source_detections,
)

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(auth.router)

protected_router = APIRouter(
    dependencies=[Depends(current_user_dependency), Depends(csrf_protection_dependency)]
)
protected_router.include_router(candidate.router)
protected_router.include_router(career_facts.router)
protected_router.include_router(documents.router)
protected_router.include_router(proposals.router)
protected_router.include_router(jobs.router)
protected_router.include_router(job_searches.router)
protected_router.include_router(job_discovery.router)
protected_router.include_router(job_sources.router)
protected_router.include_router(source_detections.router)
router.include_router(protected_router)
