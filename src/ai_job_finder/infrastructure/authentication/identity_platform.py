from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import firebase_admin
from firebase_admin import auth

from ai_job_finder.application.authentication import (
    AuthenticatedIdentity,
    EstablishedIdentitySession,
    IdentitySessionError,
)


class FirebaseIdentityPlatformSessionProvider:
    def __init__(
        self,
        *,
        project_id: str,
        tenant_id: str | None,
        recent_authentication_max_age: timedelta,
    ) -> None:
        self.project_id = project_id
        self.tenant_id = tenant_id
        self.recent_authentication_max_age = recent_authentication_max_age
        self.client = auth.Client(app=_firebase_app(project_id), tenant_id=tenant_id)

    def establish_session(
        self,
        id_token: str,
        *,
        max_age: timedelta,
    ) -> EstablishedIdentitySession:
        try:
            decoded_token = self.client.verify_id_token(id_token, check_revoked=True)
            self._ensure_recent_authentication(decoded_token)
            session_cookie = self.client.create_session_cookie(id_token, expires_in=max_age)
        except Exception as exc:
            raise IdentitySessionError("ID token verification failed.") from exc
        return EstablishedIdentitySession(
            identity=_identity_from_claims(decoded_token),
            session_cookie=session_cookie,
        )

    def verify_session(self, session_cookie: str) -> AuthenticatedIdentity:
        try:
            decoded_cookie = self.client.verify_session_cookie(session_cookie, check_revoked=False)
        except Exception as exc:
            raise IdentitySessionError("Session cookie verification failed.") from exc
        return _identity_from_claims(decoded_cookie)

    def _ensure_recent_authentication(self, claims: dict[str, Any]) -> None:
        auth_time = claims.get("auth_time")
        if not isinstance(auth_time, int | float):
            raise IdentitySessionError("ID token is missing a valid auth_time claim.")
        authenticated_at = datetime.fromtimestamp(auth_time, tz=UTC)
        if datetime.now(UTC) - authenticated_at > self.recent_authentication_max_age:
            raise IdentitySessionError("Recent authentication is required to establish a session.")


def _firebase_app(project_id: str) -> firebase_admin.App:
    try:
        return firebase_admin.get_app()
    except ValueError:
        return firebase_admin.initialize_app(options={"projectId": project_id})


def _identity_from_claims(claims: dict[str, Any]) -> AuthenticatedIdentity:
    uid = claims.get("uid")
    if not isinstance(uid, str) or not uid:
        raise IdentitySessionError("Verified token is missing a valid UID.")
    return AuthenticatedIdentity(provider="google_identity_platform", subject=uid)
