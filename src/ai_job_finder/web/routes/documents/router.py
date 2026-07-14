from __future__ import annotations

from fastapi import APIRouter

from ai_job_finder.web.routes.documents.documents import router as documents_router
from ai_job_finder.web.routes.documents.proposals import router as proposals_router

router = APIRouter()
router.include_router(documents_router)
router.include_router(proposals_router)
