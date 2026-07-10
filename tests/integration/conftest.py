from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from ai_job_finder.api.dependencies import db_session_dependency
from ai_job_finder.infrastructure.database.base import Base
from ai_job_finder.infrastructure.database.session import create_engine_from_url
from ai_job_finder.main import create_app


@pytest.fixture()
def database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", "sqlite+pysqlite:///:memory:")


@pytest.fixture()
def session_factory(database_url: str) -> sessionmaker[Session]:
    engine = create_engine_from_url(database_url)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


@pytest.fixture()
def client(session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    app = create_app()

    def override_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[db_session_dependency] = override_db
    with TestClient(app) as test_client:
        yield test_client
