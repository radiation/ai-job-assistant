from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from ai_job_finder.settings import get_settings


def _enable_sqlite_foreign_keys(engine: Engine) -> None:
    if engine.url.get_backend_name() != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection: Any, _: object) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def create_engine_from_url(database_url: str) -> Engine:
    connect_args: dict[str, Any] = {}
    engine_kwargs: dict[str, Any] = {"future": True}

    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        if database_url.endswith(":memory:"):
            engine_kwargs["poolclass"] = StaticPool

    if connect_args:
        engine_kwargs["connect_args"] = connect_args

    engine = create_engine(database_url, **engine_kwargs)
    _enable_sqlite_foreign_keys(engine)
    return engine


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine_from_url(get_settings().database_url)


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False, class_=Session)


def get_db_session() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
