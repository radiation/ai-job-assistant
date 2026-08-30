from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ai_job_finder.infrastructure.authentication.identity_platform import (
    FirebaseIdentityPlatformSessionProvider,
)


class RecordingFirebaseClient:
    def __init__(self) -> None:
        self.id_token_check_revoked: bool | None = None
        self.session_cookie_check_revoked: bool | None = None

    def verify_id_token(self, _: str, *, check_revoked: bool) -> dict[str, object]:
        self.id_token_check_revoked = check_revoked
        return {"uid": "identity-subject", "auth_time": datetime.now(UTC).timestamp()}

    def create_session_cookie(self, _: str, *, expires_in: timedelta) -> str:
        assert expires_in == timedelta(days=1)
        return "signed-session-cookie"

    def verify_session_cookie(self, _: str, *, check_revoked: bool) -> dict[str, object]:
        self.session_cookie_check_revoked = check_revoked
        return {"uid": "identity-subject"}


def test_session_establishment_checks_revocation_but_normal_verification_does_not() -> None:
    provider = object.__new__(FirebaseIdentityPlatformSessionProvider)
    provider.client = RecordingFirebaseClient()
    provider.recent_authentication_max_age = timedelta(minutes=5)

    established = provider.establish_session("id-token", max_age=timedelta(days=1))
    identity = provider.verify_session("signed-session-cookie")

    assert established.identity.subject == "identity-subject"
    assert established.session_cookie == "signed-session-cookie"
    assert identity.provider == "google_identity_platform"
    assert provider.client.id_token_check_revoked is True
    assert provider.client.session_cookie_check_revoked is False
