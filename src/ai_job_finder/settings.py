from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
