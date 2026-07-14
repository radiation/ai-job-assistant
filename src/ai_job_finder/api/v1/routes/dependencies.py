from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from ai_job_finder.api.dependencies import (
    career_fact_extractor_dependency,
    db_session_dependency,
    document_storage_dependency,
    greenhouse_board_validator_dependency,
    job_source_connector_dependency,
    public_page_fetcher_dependency,
    settings_dependency,
)
from ai_job_finder.application.extraction import CareerFactExtractor
from ai_job_finder.domain.job_sources import JobSourceConnector
from ai_job_finder.domain.source_detection import GreenhouseBoardValidator, PublicPageFetcher
from ai_job_finder.infrastructure.storage import DocumentStorage
from ai_job_finder.settings import Settings

DbSession = Annotated[Session, Depends(db_session_dependency)]
DocumentStorageDependency = Annotated[DocumentStorage, Depends(document_storage_dependency)]
SettingsDependency = Annotated[Settings, Depends(settings_dependency)]
ExtractorDependency = Annotated[CareerFactExtractor, Depends(career_fact_extractor_dependency)]
JobSourceConnectorDependency = Annotated[
    JobSourceConnector, Depends(job_source_connector_dependency)
]
PublicPageFetcherDependency = Annotated[PublicPageFetcher, Depends(public_page_fetcher_dependency)]
GreenhouseBoardValidatorDependency = Annotated[
    GreenhouseBoardValidator, Depends(greenhouse_board_validator_dependency)
]
