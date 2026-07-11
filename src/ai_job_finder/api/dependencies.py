from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from ai_job_finder.application.extraction import CareerFactExtractor
from ai_job_finder.domain.errors import ExtractionProviderUnavailableError
from ai_job_finder.infrastructure.database.session import get_db_session
from ai_job_finder.infrastructure.llm.fake import FakeCareerFactExtractor
from ai_job_finder.infrastructure.llm.vertex import VertexGeminiCareerFactExtractor
from ai_job_finder.infrastructure.storage import DocumentStorage, LocalDocumentStorage
from ai_job_finder.settings import Settings, get_settings


def db_session_dependency() -> Iterator[Session]:
    yield from get_db_session()


def settings_dependency() -> Settings:
    return get_settings()


def document_storage_dependency(
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> DocumentStorage:
    return LocalDocumentStorage(settings.local_document_storage_dir)


def career_fact_extractor_dependency(
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> CareerFactExtractor:
    if not settings.extraction_enabled:
        msg = "Career fact extraction is disabled by configuration."
        raise ExtractionProviderUnavailableError(msg)
    if settings.extraction_provider == "fake":
        return FakeCareerFactExtractor(
            prompt_version=settings.extraction_prompt_version,
            schema_version=settings.extraction_schema_version,
            temperature=settings.extraction_temperature,
        )
    if not settings.vertex_project or not settings.vertex_region:
        msg = "Vertex project and region are required when extraction_provider=vertex."
        raise ExtractionProviderUnavailableError(msg)
    return VertexGeminiCareerFactExtractor(
        project=settings.vertex_project,
        region=settings.vertex_region,
        model_id=settings.vertex_gemini_model_id,
        prompt_version=settings.extraction_prompt_version,
        schema_version=settings.extraction_schema_version,
        temperature=settings.extraction_temperature,
        timeout_seconds=settings.extraction_timeout_seconds,
    )
