from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class SettingsConfigurationError(ValueError):
    pass


def resolve_database_url(settings: Settings) -> str:
    if settings.database_url:
        return settings.database_url

    db_user = settings.db_user
    db_password = settings.db_password
    db_name = settings.db_name
    instance_unix_socket = settings.instance_unix_socket

    production_values = (db_user, db_password, db_name, instance_unix_socket)
    if all(production_values):
        assert db_user is not None
        assert db_password is not None
        assert db_name is not None
        assert instance_unix_socket is not None
        return URL.create(
            drivername="postgresql+psycopg",
            username=db_user,
            password=db_password,
            database=db_name,
            query={"host": instance_unix_socket},
        ).render_as_string(hide_password=False)

    raise SettingsConfigurationError(
        "Configure DATABASE_URL for local development or set all of "
        "DB_USER, DB_PASSWORD, DB_NAME, and INSTANCE_UNIX_SOCKET."
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str | None = None
    db_user: str | None = None
    db_password: str | None = None
    db_name: str | None = None
    instance_unix_socket: str | None = None
    test_database_url: str | None = None
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    enable_dev_reset_api: bool = False
    extraction_enabled: bool = False
    extraction_provider: str = "vertex"
    vertex_project: str | None = None
    vertex_region: str | None = None
    vertex_gemini_model_id: str = "gemini-2.5-flash"
    extraction_prompt_version: str = "career_fact_extraction_v1"
    extraction_schema_version: str = "career_fact_extraction_schema_v1"
    extraction_temperature: float = 0.0
    extraction_timeout_seconds: float = 30.0
    extraction_chunk_size: int = 12_000
    extraction_max_chunks: int = 8
    extraction_max_extracted_characters: int = 80_000
    max_upload_size_bytes: int = 5 * 1024 * 1024
    local_document_storage_dir: Path = Path(".local/document-storage")
    greenhouse_api_base_url: str = "https://boards-api.greenhouse.io/v1"
    greenhouse_timeout_seconds: float = 10.0
    greenhouse_transient_retry_count: int = 2
    greenhouse_user_agent: str = "ai-job-finder/0.1"
    greenhouse_close_on_empty_result: bool = False
    greenhouse_retain_raw_payload: bool = True
    greenhouse_max_response_bytes: int | None = 5 * 1024 * 1024
    greenhouse_max_jobs: int | None = 2_000
    greenhouse_fake_fixture_path: Path | None = None
    ashby_api_base_url: str = "https://api.ashbyhq.com/posting-api/job-board"
    ashby_timeout_seconds: float = 10.0
    ashby_transient_retry_count: int = 2
    ashby_max_response_bytes: int | None = 5 * 1024 * 1024
    ashby_max_jobs: int | None = 2_000
    lever_api_base_url: str = "https://api.lever.co/v0/postings"
    lever_timeout_seconds: float = 10.0
    lever_transient_retry_count: int = 2
    lever_max_response_bytes: int | None = 5 * 1024 * 1024
    lever_max_jobs: int | None = 2_000
    job_source_stale_after_seconds: int = 3600
    source_detection_timeout_seconds: float = 8.0
    source_detection_transient_retry_count: int = 1
    source_detection_max_response_bytes: int = 1_000_000
    source_detection_max_redirects: int = 5
    source_detection_allowed_ports: list[int] = [80, 443]
    source_detection_max_linked_scripts: int = 4
    source_detection_max_script_bytes: int = 200_000
    source_detection_total_script_bytes: int = 500_000
    job_discovery_provider: str = "fake"
    job_discovery_fake_fixture_path: Path | None = None
    job_discovery_result_limit: int = 5
    job_discovery_max_queries_per_run: int = 6
    job_discovery_max_total_candidates: int = 25
    job_discovery_timeout_seconds: float = 10.0
    job_discovery_transient_retry_count: int = 1
    job_discovery_brave_api_base_url: str = "https://api.search.brave.com/res/v1/web/search"
    job_discovery_brave_api_key: str | None = None
    email_alerts_enabled: bool = False
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_tls_mode: Literal["starttls", "implicit", "none"] = "starttls"
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    email_alert_sender: str | None = None
    email_alert_recipient: str | None = None
    public_application_base_url: str = "http://127.0.0.1:8000"
    smtp_timeout_seconds: float = 10.0

    @field_validator("job_discovery_fake_fixture_path", mode="before")
    @classmethod
    def _empty_job_discovery_fixture_path_is_none(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @field_validator("greenhouse_fake_fixture_path", mode="before")
    @classmethod
    def _empty_fake_fixture_path_is_none(cls, value: object) -> object:
        if value == "":
            return None
        return value

    def resolved_database_url(self) -> str:
        return resolve_database_url(self)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
