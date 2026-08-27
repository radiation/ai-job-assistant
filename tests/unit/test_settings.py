from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.engine import URL

from ai_job_finder.settings import Settings, SettingsConfigurationError, resolve_database_url


def test_database_url_wins_when_present() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://localhost/local-dev",
        db_user="job_finder_app",
        db_password="secret",
        db_name="job_finder",
        instance_unix_socket="/cloudsql/project:region:instance",
    )

    assert resolve_database_url(settings) == "postgresql+psycopg://localhost/local-dev"


def test_component_settings_build_cloud_sql_unix_socket_url() -> None:
    settings = Settings(
        database_url=None,
        db_user="job_finder_app",
        db_password="secret",
        db_name="job_finder",
        instance_unix_socket="/cloudsql/bryanchoate:us-central1:bryanchoate-postgres",
    )

    assert resolve_database_url(settings) == URL.create(
        drivername="postgresql+psycopg",
        username="job_finder_app",
        password="secret",
        database="job_finder",
        query={"host": "/cloudsql/bryanchoate:us-central1:bryanchoate-postgres"},
    ).render_as_string(hide_password=False)


def test_incomplete_database_configuration_fails_clearly() -> None:
    settings = Settings(
        database_url=None,
        db_user="job_finder_app",
        db_password=None,
        db_name="job_finder",
        instance_unix_socket="/cloudsql/bryanchoate:us-central1:bryanchoate-postgres",
    )

    with pytest.raises(SettingsConfigurationError) as excinfo:
        resolve_database_url(settings)

    assert "DATABASE_URL" in str(excinfo.value)
    assert "DB_USER, DB_PASSWORD, DB_NAME, and INSTANCE_UNIX_SOCKET" in str(excinfo.value)


def test_discovery_query_cap_uses_expected_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JOB_DISCOVERY_MAX_QUERIES_PER_RUN", "12")
    monkeypatch.delenv("JOB_DISCOVERY_MAX_QUERIES", raising=False)

    assert Settings(_env_file=None).job_discovery_max_queries_per_run == 12


def test_compose_wires_discovery_query_cap_to_settings_environment_variable() -> None:
    compose_file = Path(__file__).parents[2] / "docker-compose.yml"

    assert (
        "JOB_DISCOVERY_MAX_QUERIES_PER_RUN: ${JOB_DISCOVERY_MAX_QUERIES_PER_RUN:-12}"
        in compose_file.read_text()
    )
