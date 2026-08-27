from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from ai_job_finder.application.extraction import CareerFactExtractor
from ai_job_finder.application.job_discovery.ports import JobDiscoveryProvider
from ai_job_finder.domain.enums import JobSourceProvider
from ai_job_finder.domain.errors import (
    ExtractionProviderUnavailableError,
    JobDiscoveryProviderUnavailableError,
)
from ai_job_finder.domain.job_sources import JobSourceConnector
from ai_job_finder.domain.source_detection import (
    JobSourceBoardValidator,
    PublicPageFetcher,
)
from ai_job_finder.infrastructure.database.session import get_db_session
from ai_job_finder.infrastructure.job_discovery import (
    BraveSearchJobDiscoveryProvider,
    FakeJobDiscoveryProvider,
    FileBackedFakeJobDiscoveryProvider,
)
from ai_job_finder.infrastructure.job_sources.ashby import AshbyJobSourceConnector
from ai_job_finder.infrastructure.job_sources.fake import FileBackedFakeJobSourceConnector
from ai_job_finder.infrastructure.job_sources.greenhouse import GreenhouseJobSourceConnector
from ai_job_finder.infrastructure.job_sources.router import (
    ProviderJobSourceBoardValidator,
    ProviderJobSourceConnector,
)
from ai_job_finder.infrastructure.llm.fake import FakeCareerFactExtractor
from ai_job_finder.infrastructure.llm.vertex import VertexGeminiCareerFactExtractor
from ai_job_finder.infrastructure.public_fetcher import (
    PublicPageFetcherConfig,
    SafePublicPageFetcher,
)
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


def job_source_connector_dependency(
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> JobSourceConnector:
    greenhouse = _greenhouse_connector(settings)
    ashby = AshbyJobSourceConnector(
        api_base_url=settings.ashby_api_base_url,
        timeout_seconds=settings.ashby_timeout_seconds,
        transient_retry_count=settings.ashby_transient_retry_count,
        user_agent=settings.greenhouse_user_agent,
        max_response_bytes=settings.ashby_max_response_bytes,
        max_jobs=settings.ashby_max_jobs,
    )
    return ProviderJobSourceConnector(
        {JobSourceProvider.GREENHOUSE: greenhouse, JobSourceProvider.ASHBY: ashby}
    )


def job_discovery_provider_dependency(
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> JobDiscoveryProvider:
    if settings.job_discovery_provider == "fake":
        if settings.job_discovery_fake_fixture_path is not None:
            return FileBackedFakeJobDiscoveryProvider(settings.job_discovery_fake_fixture_path)
        return FakeJobDiscoveryProvider()
    if settings.job_discovery_provider == "brave":
        if not settings.job_discovery_brave_api_key:
            raise JobDiscoveryProviderUnavailableError(
                "JOB_DISCOVERY_BRAVE_API_KEY is required when job_discovery_provider=brave."
            )
        return BraveSearchJobDiscoveryProvider(
            api_base_url=settings.job_discovery_brave_api_base_url,
            api_key=settings.job_discovery_brave_api_key,
            timeout_seconds=settings.job_discovery_timeout_seconds,
            transient_retry_count=settings.job_discovery_transient_retry_count,
            user_agent=settings.greenhouse_user_agent,
        )
    raise JobDiscoveryProviderUnavailableError(
        f"Unsupported job discovery provider: {settings.job_discovery_provider}."
    )


def job_source_board_validator_dependency(
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> JobSourceBoardValidator:
    return ProviderJobSourceBoardValidator(
        {
            JobSourceProvider.GREENHOUSE: _greenhouse_connector(settings),
            JobSourceProvider.ASHBY: _ashby_connector(settings),
        }
    )


def _ashby_connector(settings: Settings) -> AshbyJobSourceConnector:
    return AshbyJobSourceConnector(
        api_base_url=settings.ashby_api_base_url,
        timeout_seconds=settings.ashby_timeout_seconds,
        transient_retry_count=settings.ashby_transient_retry_count,
        user_agent=settings.greenhouse_user_agent,
        max_response_bytes=settings.ashby_max_response_bytes,
        max_jobs=settings.ashby_max_jobs,
    )


def _greenhouse_connector(
    settings: Settings,
) -> GreenhouseJobSourceConnector | FileBackedFakeJobSourceConnector:
    if settings.greenhouse_fake_fixture_path is not None:
        return FileBackedFakeJobSourceConnector(settings.greenhouse_fake_fixture_path)
    return GreenhouseJobSourceConnector(
        api_base_url=settings.greenhouse_api_base_url,
        timeout_seconds=settings.greenhouse_timeout_seconds,
        transient_retry_count=settings.greenhouse_transient_retry_count,
        user_agent=settings.greenhouse_user_agent,
        max_response_bytes=settings.greenhouse_max_response_bytes,
        max_jobs=settings.greenhouse_max_jobs,
    )


def public_page_fetcher_dependency(
    settings: Annotated[Settings, Depends(settings_dependency)],
) -> PublicPageFetcher:
    return SafePublicPageFetcher(
        PublicPageFetcherConfig(
            timeout_seconds=settings.source_detection_timeout_seconds,
            transient_retry_count=settings.source_detection_transient_retry_count,
            max_response_bytes=settings.source_detection_max_response_bytes,
            max_redirects=settings.source_detection_max_redirects,
            allowed_ports=settings.source_detection_allowed_ports,
            user_agent=settings.greenhouse_user_agent,
        )
    )
