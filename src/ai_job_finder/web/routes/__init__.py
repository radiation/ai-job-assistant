from __future__ import annotations

from fastapi import APIRouter, Depends

from ai_job_finder.api.dependencies import current_user_dependency
from ai_job_finder.api.security import csrf_protection_dependency
from ai_job_finder.web.routes.auth import router as auth_router
from ai_job_finder.web.routes.candidate import router as candidate_router
from ai_job_finder.web.routes.documents import router as documents_router
from ai_job_finder.web.routes.job_searches import router as job_searches_router
from ai_job_finder.web.routes.job_sources import router as job_sources_router
from ai_job_finder.web.routes.jobs import router as jobs_router

router = APIRouter()
router.include_router(auth_router)

protected_router = APIRouter(
    dependencies=[Depends(current_user_dependency), Depends(csrf_protection_dependency)]
)
protected_router.include_router(jobs_router)
protected_router.include_router(job_sources_router)
protected_router.include_router(job_searches_router)
protected_router.include_router(candidate_router)
protected_router.include_router(documents_router)
router.include_router(protected_router)
