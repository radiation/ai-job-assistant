from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from ai_job_finder.api.dependencies import (
    db_session_dependency,
    identity_session_provider_dependency,
)
from ai_job_finder.application.authentication import AuthenticatedIdentity
from ai_job_finder.infrastructure.authentication.fake import FakeIdentitySessionProvider
from ai_job_finder.main import create_app


@pytest.fixture()
def identity_session_provider() -> FakeIdentitySessionProvider:
    return FakeIdentitySessionProvider(
        {"valid-id-token": AuthenticatedIdentity("google_identity_platform", "new-user")}
    )


@pytest.fixture()
def unauthenticated_client(
    session_factory: sessionmaker[Session],
    identity_session_provider: FakeIdentitySessionProvider,
) -> Iterator[TestClient]:
    app = create_app()

    def override_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[db_session_dependency] = override_db
    app.dependency_overrides[identity_session_provider_dependency] = lambda: (
        identity_session_provider
    )
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client


def test_health_is_public(unauthenticated_client: TestClient) -> None:
    assert unauthenticated_client.get("/api/v1/health").status_code == 200


def test_business_api_requires_session_cookie(unauthenticated_client: TestClient) -> None:
    response = unauthenticated_client.get("/api/v1/job-leads")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_business_web_route_redirects_to_sign_in(unauthenticated_client: TestClient) -> None:
    response = unauthenticated_client.get("/jobs", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/sign-in"


def test_session_establishment_requires_matching_csrf(unauthenticated_client: TestClient) -> None:
    no_token = unauthenticated_client.post(
        "/api/v1/auth/session", json={"id_token": "valid-id-token"}
    )
    assert no_token.status_code == 403

    unauthenticated_client.cookies.set("ai_job_finder_csrf", "expected")
    mismatched = unauthenticated_client.post(
        "/api/v1/auth/session",
        json={"id_token": "valid-id-token"},
        headers={"X-CSRF-Token": "unexpected"},
    )
    assert mismatched.status_code == 403


def test_session_lifecycle_and_current_user(unauthenticated_client: TestClient) -> None:
    unauthenticated_client.get("/sign-in")
    csrf_token = unauthenticated_client.cookies["ai_job_finder_csrf"]
    response = unauthenticated_client.post(
        "/api/v1/auth/session",
        json={"id_token": "valid-id-token"},
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "Secure" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]
    assert unauthenticated_client.get("/api/v1/auth/me").json()["external_subject"] == "new-user"

    logout = unauthenticated_client.delete(
        "/api/v1/auth/session", headers={"X-CSRF-Token": csrf_token}
    )
    assert logout.status_code == 204
    assert "Max-Age=0" in logout.headers["set-cookie"]


def test_html_form_csrf_token_allows_mutation(client: TestClient) -> None:
    response = client.post(
        "/jobs",
        data={
            "source": "manual",
            "company_name": "Northstar",
            "title": "Director",
            "description_raw": "Own strategy.",
            "csrf_token": "test-csrf-token",
        },
    )

    assert response.status_code == 200


def test_htmx_csrf_header_allows_mutation(client: TestClient) -> None:
    created = client.post(
        "/api/v1/job-leads",
        json={
            "source": "manual",
            "company_name": "Northstar",
            "title": "Director",
            "description_raw": "Own strategy.",
            "description_normalized": "Own strategy.",
        },
    )

    response = client.post(
        f"/jobs/{created.json()['id']}/status",
        data={"posting_status": "reviewing"},
        headers={"HX-Request": "true", "X-CSRF-Token": "test-csrf-token"},
    )

    assert response.status_code == 200
    assert "reviewing" in response.text


def test_missing_local_user_is_not_reprovisioned(
    unauthenticated_client: TestClient,
    identity_session_provider: FakeIdentitySessionProvider,
) -> None:
    established = identity_session_provider.establish_session(
        "valid-id-token", max_age=timedelta(days=1)
    )
    unauthenticated_client.cookies.set("ai_job_finder_session", established.session_cookie)

    assert unauthenticated_client.get("/api/v1/auth/me").status_code == 401


def test_expired_session_is_rejected(
    unauthenticated_client: TestClient,
    identity_session_provider: FakeIdentitySessionProvider,
) -> None:
    identity_session_provider.expired_session_cookies.add("expired-session")
    unauthenticated_client.cookies.set("ai_job_finder_session", "expired-session")

    assert unauthenticated_client.get("/api/v1/auth/me").status_code == 401
