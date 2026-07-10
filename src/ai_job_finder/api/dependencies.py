from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from ai_job_finder.infrastructure.database.session import get_db_session


def db_session_dependency() -> Iterator[Session]:
    yield from get_db_session()
