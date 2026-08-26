from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ai_job_finder.application.job_discovery.ports import JobDiscoveryProvider
from ai_job_finder.domain.job_discovery import DiscoveredJobCandidate, JobDiscoveryQuery


@dataclass(slots=True)
class FakeJobDiscoveryProvider(JobDiscoveryProvider):
    results_by_query: dict[str, list[DiscoveredJobCandidate]] = field(default_factory=dict)
    error_by_query: dict[str, Exception] = field(default_factory=dict)
    provider_name: str = "fake"

    def search(self, query: JobDiscoveryQuery) -> list[DiscoveredJobCandidate]:
        error = self.error_by_query.get(query.rendered_query)
        if error is not None:
            raise error
        return list(self.results_by_query.get(query.rendered_query, []))


@dataclass(slots=True)
class FileBackedFakeJobDiscoveryProvider(JobDiscoveryProvider):
    fixture_path: Path
    provider_name: str = "fake"

    def search(self, query: JobDiscoveryQuery) -> list[DiscoveredJobCandidate]:
        payload = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return []
        errors = payload.get("errors", {})
        if isinstance(errors, dict):
            error_message = errors.get(query.rendered_query)
            if isinstance(error_message, str) and error_message:
                raise RuntimeError(error_message)
        queries = payload.get("queries", {})
        if not isinstance(queries, dict):
            return []
        result_payload = queries.get(query.rendered_query, [])
        if not isinstance(result_payload, list):
            return []
        return [_candidate_from_payload(query, item) for item in result_payload]


def _candidate_from_payload(query: JobDiscoveryQuery, payload: Any) -> DiscoveredJobCandidate:
    if not isinstance(payload, dict):
        return DiscoveredJobCandidate(
            discovered_url="",
            provider_name="fake",
            query_identifier=query.stable_query_id,
            rank=0,
        )
    discovered_at = payload.get("discovered_at")
    parsed_discovered_at = None
    if isinstance(discovered_at, str):
        parsed_discovered_at = datetime.fromisoformat(discovered_at)
    return DiscoveredJobCandidate(
        discovered_url=str(payload.get("discovered_url") or ""),
        provider_name=str(payload.get("provider_name") or "fake"),
        query_identifier=query.stable_query_id,
        rank=int(payload.get("rank") or 0),
        provider_result_identifier=(
            str(payload["provider_result_identifier"])
            if payload.get("provider_result_identifier") is not None
            else None
        ),
        title_hint=str(payload["title_hint"]) if payload.get("title_hint") is not None else None,
        company_hint=(
            str(payload["company_hint"]) if payload.get("company_hint") is not None else None
        ),
        location_hint=(
            str(payload["location_hint"]) if payload.get("location_hint") is not None else None
        ),
        evidence_snippet=(
            str(payload["evidence_snippet"])
            if payload.get("evidence_snippet") is not None
            else None
        ),
        discovered_at=parsed_discovered_at,
        raw_evidence=dict(payload.get("raw_evidence", {})),
    )
