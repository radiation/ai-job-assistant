from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from ai_job_finder.api.dependencies import (
    db_session_dependency,
    identity_session_provider_dependency,
)
from ai_job_finder.application.authentication import AuthenticatedIdentity, resolve_or_create_user
from ai_job_finder.infrastructure.authentication.fake import FakeIdentitySessionProvider
from ai_job_finder.infrastructure.database.base import Base
from ai_job_finder.infrastructure.database.session import create_engine_from_url
from ai_job_finder.main import create_app


@pytest.fixture()
def database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", "sqlite+pysqlite:///:memory:")


@pytest.fixture()
def session_factory(database_url: str) -> Iterator[sessionmaker[Session]]:
    engine = create_engine_from_url(database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def client(session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    app = create_app()
    fake_identity_provider = FakeIdentitySessionProvider(
        {"test-id-token": AuthenticatedIdentity("google_identity_platform", "test-user")}
    )
    established_session = fake_identity_provider.establish_session(
        "test-id-token", max_age=timedelta(days=1)
    )

    def override_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[db_session_dependency] = override_db
    app.dependency_overrides[identity_session_provider_dependency] = lambda: fake_identity_provider
    with session_factory() as session:
        resolve_or_create_user(session, identity=established_session.identity)
    with TestClient(app, base_url="https://testserver") as test_client:
        test_client.cookies.set("ai_job_finder_session", established_session.session_cookie)
        test_client.cookies.set("ai_job_finder_csrf", "test-csrf-token")
        test_client.headers["X-CSRF-Token"] = "test-csrf-token"
        yield test_client
