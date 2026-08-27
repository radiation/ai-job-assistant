from __future__ import annotations

from collections.abc import Mapping

from ai_job_finder.domain.enums import JobSourceProvider
from ai_job_finder.domain.errors import InvalidJobSourceError
from ai_job_finder.domain.job_sources import (
    JobSourceConfigurationSnapshot,
    JobSourceConnector,
    JobSourceFetchResult,
)


class ProviderJobSourceConnector:
    def __init__(self, connectors: Mapping[JobSourceProvider, JobSourceConnector]) -> None:
        self._connectors = dict(connectors)

    def fetch_jobs(self, source: JobSourceConfigurationSnapshot) -> JobSourceFetchResult:
        connector = self._connectors.get(source.provider)
        if connector is None:
            raise InvalidJobSourceError(f"Unsupported job source provider: {source.provider}.")
        return connector.fetch_jobs(source)
