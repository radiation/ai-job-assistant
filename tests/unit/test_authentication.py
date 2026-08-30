from __future__ import annotations

from sqlalchemy.orm import Session

from ai_job_finder.application.authentication import (
    AuthenticatedIdentity,
    get_user_by_identity,
    resolve_or_create_user,
)
from ai_job_finder.infrastructure.database.base import Base
from ai_job_finder.infrastructure.database.session import create_engine_from_url


def test_resolve_or_create_user_reuses_provider_subject_identity() -> None:
    engine = create_engine_from_url("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        identity = AuthenticatedIdentity("google_identity_platform", "subject-1")
        first = resolve_or_create_user(session, identity=identity)
        second = resolve_or_create_user(session, identity=identity)

        assert first.id == second.id


def test_provider_and_subject_together_are_the_local_identity_key() -> None:
    engine = create_engine_from_url("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        first = resolve_or_create_user(
            session, identity=AuthenticatedIdentity("provider-one", "shared-subject")
        )
        second = resolve_or_create_user(
            session, identity=AuthenticatedIdentity("provider-two", "shared-subject")
        )

        assert first.id != second.id
        assert (
            get_user_by_identity(
                session, identity=AuthenticatedIdentity("provider-one", "missing-subject")
            )
            is None
        )
