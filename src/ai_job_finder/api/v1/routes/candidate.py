from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from ai_job_finder.api.v1.routes.dependencies import DbSession
from ai_job_finder.api.v1.schemas import (
    CandidateProfileCreateRequest,
    CandidateProfileResponse,
    CandidateProfileUpdateRequest,
    CandidateSliceResetResponse,
)
from ai_job_finder.application.services import (
    create_candidate_profile,
    get_current_candidate_profile,
    reset_current_candidate_profile,
    update_candidate_profile,
)
from ai_job_finder.domain.errors import NotFoundError
from ai_job_finder.settings import get_settings

router = APIRouter()


@router.post(
    "/candidate-profile",
    response_model=CandidateProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_candidate_profile(
    payload: CandidateProfileCreateRequest, session: DbSession
) -> CandidateProfileResponse:
    candidate = create_candidate_profile(
        session,
        full_name=payload.full_name,
        preferred_locations=payload.preferred_locations,
        acceptable_remote_geographies=payload.acceptable_remote_geographies,
        remote_preference=payload.remote_preference.value,
        target_levels=payload.target_levels,
        target_functions=payload.target_functions,
    )
    return CandidateProfileResponse.model_validate(candidate)


@router.get("/candidate-profile", response_model=CandidateProfileResponse)
def get_current_candidate_profile_route(session: DbSession) -> CandidateProfileResponse:
    candidate = get_current_candidate_profile(session)
    if candidate is None:
        raise NotFoundError("No active candidate profile exists.")
    return CandidateProfileResponse.model_validate(candidate)


@router.put("/candidate-profile", response_model=CandidateProfileResponse)
def put_candidate_profile(
    payload: CandidateProfileUpdateRequest,
    session: DbSession,
) -> CandidateProfileResponse:
    candidate = get_current_candidate_profile(session)
    if candidate is None:
        raise NotFoundError("No active candidate profile exists.")
    candidate = update_candidate_profile(
        session,
        candidate_profile_id=candidate.id,
        full_name=payload.full_name,
        preferred_locations=payload.preferred_locations,
        acceptable_remote_geographies=payload.acceptable_remote_geographies,
        remote_preference=payload.remote_preference.value,
        target_levels=payload.target_levels,
        target_functions=payload.target_functions,
    )
    return CandidateProfileResponse.model_validate(candidate)


@router.post(
    "/dev/reset-candidate-profile",
    response_model=CandidateSliceResetResponse,
)
def post_reset_candidate_profile(session: DbSession) -> CandidateSliceResetResponse:
    if not get_settings().enable_dev_reset_api:
        raise HTTPException(status_code=404, detail="Not found")
    return CandidateSliceResetResponse(candidate_deleted=reset_current_candidate_profile(session))
