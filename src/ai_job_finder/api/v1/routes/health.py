from __future__ import annotations

from fastapi import APIRouter

from ai_job_finder.api.v1.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")
