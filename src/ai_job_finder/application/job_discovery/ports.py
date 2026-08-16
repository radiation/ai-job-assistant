from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ai_job_finder.domain.job_discovery import DiscoveredJobCandidate, JobDiscoveryQuery


class JobDiscoveryProvider(Protocol):
    def search(self, query: JobDiscoveryQuery) -> Sequence[DiscoveredJobCandidate]: ...
