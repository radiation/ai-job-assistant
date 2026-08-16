from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class JobDiscoveryQuery:
    stable_query_id: str
    search_definition_id: UUID
    ordinal: int
    rendered_query: str
    title_phrase: str
    target_domain: str | None
    location_or_workplace_term: str | None
    result_limit: int


@dataclass(frozen=True, slots=True)
class DiscoveredJobCandidate:
    discovered_url: str
    provider_name: str
    query_identifier: str
    rank: int
    provider_result_identifier: str | None = None
    title_hint: str | None = None
    company_hint: str | None = None
    location_hint: str | None = None
    evidence_snippet: str | None = None
    discovered_at: datetime | None = None
    raw_evidence: dict[str, Any] = field(default_factory=dict)
