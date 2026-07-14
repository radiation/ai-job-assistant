from __future__ import annotations

from fastapi import APIRouter

from ai_job_finder.web.routes.job_sources.detections import router as detections_router
from ai_job_finder.web.routes.job_sources.discovery import router as discovery_router
from ai_job_finder.web.routes.job_sources.imports import router as imports_router
from ai_job_finder.web.routes.job_sources.sources import router as sources_router

router = APIRouter()
router.include_router(detections_router)
router.include_router(sources_router)
router.include_router(imports_router)
router.include_router(discovery_router)
