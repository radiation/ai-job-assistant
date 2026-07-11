from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    test_database_url: str | None = None
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    enable_dev_reset_api: bool = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
