from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Response, status

from ai_job_finder.api.security import csrf_protection_dependency
from ai_job_finder.api.v1.routes.dependencies import (
    CurrentUser,
    DbSession,
    IdentitySessionProviderDependency,
    SettingsDependency,
)
from ai_job_finder.api.v1.schemas import AuthSessionCreateRequest, CurrentUserResponse
from ai_job_finder.application.authentication import IdentitySessionError, resolve_or_create_user
from ai_job_finder.domain.errors import AuthenticationRequiredError

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post(
    "/session",
    response_model=CurrentUserResponse,
    dependencies=[Depends(csrf_protection_dependency)],
)
def create_session(
    payload: AuthSessionCreateRequest,
    response: Response,
    session: DbSession,
    identity_session_provider: IdentitySessionProviderDependency,
    settings: SettingsDependency,
) -> CurrentUserResponse:
    try:
        established_session = identity_session_provider.establish_session(
            payload.id_token,
            max_age=timedelta(seconds=settings.auth_session_duration_seconds),
        )
    except IdentitySessionError as exc:
        raise AuthenticationRequiredError("Authentication is required.") from exc
    user = resolve_or_create_user(session, identity=established_session.identity)
    response.set_cookie(
        key=settings.auth_session_cookie_name,
        value=established_session.session_cookie,
        max_age=settings.auth_session_duration_seconds,
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return CurrentUserResponse.model_validate(user)


@router.get("/me", response_model=CurrentUserResponse)
def get_current_user(current_user: CurrentUser) -> CurrentUserResponse:
    return CurrentUserResponse.model_validate(current_user)


@router.delete(
    "/session",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(csrf_protection_dependency)],
)
def delete_session(response: Response, _: CurrentUser, settings: SettingsDependency) -> Response:
    response.delete_cookie(
        key=settings.auth_session_cookie_name,
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
        path="/",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
