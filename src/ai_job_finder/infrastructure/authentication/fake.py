from __future__ import annotations

from datetime import timedelta

from ai_job_finder.application.authentication import (
    AuthenticatedIdentity,
    EstablishedIdentitySession,
    IdentitySessionError,
)


class FakeIdentitySessionProvider:
    def __init__(
        self,
        identities_by_id_token: dict[str, AuthenticatedIdentity],
        *,
        expired_session_cookies: set[str] | None = None,
    ) -> None:
        self.identities_by_id_token = identities_by_id_token
        self.identities_by_session_cookie: dict[str, AuthenticatedIdentity] = {}
        self.expired_session_cookies = expired_session_cookies or set()

    def establish_session(
        self,
        id_token: str,
        *,
        max_age: timedelta,
    ) -> EstablishedIdentitySession:
        del max_age
        identity = self.identities_by_id_token.get(id_token)
        if identity is None:
            raise IdentitySessionError("Invalid ID token.")
        session_cookie = f"session:{id_token}"
        self.identities_by_session_cookie[session_cookie] = identity
        return EstablishedIdentitySession(identity=identity, session_cookie=session_cookie)

    def verify_session(self, session_cookie: str) -> AuthenticatedIdentity:
        if session_cookie in self.expired_session_cookies:
            raise IdentitySessionError("Session cookie has expired.")
        identity = self.identities_by_session_cookie.get(session_cookie)
        if identity is None:
            raise IdentitySessionError("Invalid session cookie.")
        return identity
