from __future__ import annotations

from fastapi import APIRouter

from ai_job_finder.api.v1.routes import (
    candidate,
    career_facts,
    documents,
    health,
    job_sources,
    jobs,
    proposals,
    source_detections,
)

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(candidate.router)
router.include_router(career_facts.router)
router.include_router(documents.router)
router.include_router(proposals.router)
router.include_router(jobs.router)
router.include_router(job_sources.router)
router.include_router(source_detections.router)
