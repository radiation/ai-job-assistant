from __future__ import annotations

import json
import time
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ai_job_finder.application.job_discovery.ports import JobDiscoveryProvider
from ai_job_finder.domain.errors import JobDiscoveryProviderError, JobDiscoveryTimeoutError
from ai_job_finder.domain.job_discovery import DiscoveredJobCandidate, JobDiscoveryQuery


class BraveSearchJobDiscoveryProvider(JobDiscoveryProvider):
    def __init__(
        self,
        *,
        api_base_url: str,
        api_key: str,
        timeout_seconds: float,
        transient_retry_count: int,
        user_agent: str,
    ) -> None:
        self.api_base_url = api_base_url
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.transient_retry_count = transient_retry_count
        self.user_agent = user_agent

    def search(self, query: JobDiscoveryQuery) -> list[DiscoveredJobCandidate]:
        payload = self._fetch_json(query)
        web = payload.get("web")
        if not isinstance(web, dict):
            return []
        results = web.get("results")
        if not isinstance(results, list):
            return []
        candidates: list[DiscoveredJobCandidate] = []
        for rank, item in enumerate(results, start=1):
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if not isinstance(url, str) or not url.strip():
                continue
            extra_snippets = item.get("extra_snippets")
            snippet = item.get("description")
            if not isinstance(snippet, str) and isinstance(extra_snippets, list):
                snippet = next((value for value in extra_snippets if isinstance(value, str)), None)
            candidates.append(
                DiscoveredJobCandidate(
                    discovered_url=url,
                    provider_name="brave",
                    query_identifier=query.stable_query_id,
                    rank=rank,
                    provider_result_identifier=(
                        str(item["profile"]["id"])
                        if isinstance(item.get("profile"), dict)
                        and item["profile"].get("id") is not None
                        else None
                    ),
                    title_hint=(str(item["title"]) if item.get("title") is not None else None),
                    evidence_snippet=(str(snippet) if snippet is not None else None),
                    raw_evidence=_bounded_raw_evidence(item),
                )
            )
        return candidates[: query.result_limit]

    def _fetch_json(self, query: JobDiscoveryQuery) -> dict[str, Any]:
        params = urlencode(
            {
                "q": query.rendered_query,
                "count": min(query.result_limit, 20),
                "safesearch": "moderate",
                "extra_snippets": "true",
            }
        )
        request = Request(
            f"{self.api_base_url}?{params}",
            headers={
                "Accept": "application/json",
                "User-Agent": self.user_agent,
                "X-Subscription-Token": self.api_key,
            },
        )
        last_error: Exception | None = None
        attempts = self.transient_retry_count + 1
        for attempt in range(attempts):
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = json.loads(cast(bytes, response.read()).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise JobDiscoveryProviderError("Brave search returned a non-object response.")
                return payload
            except HTTPError as exc:
                if exc.code in {408, 429, 500, 502, 503, 504}:
                    last_error = exc
                    if attempt < attempts - 1:
                        time.sleep(_retry_backoff_seconds(attempt))
                        continue
                raise JobDiscoveryProviderError(f"Brave search returned HTTP {exc.code}.") from exc
            except TimeoutError as exc:
                last_error = exc
                if attempt < attempts - 1:
                    time.sleep(_retry_backoff_seconds(attempt))
                    continue
            except URLError as exc:
                last_error = exc
                if attempt < attempts - 1:
                    time.sleep(_retry_backoff_seconds(attempt))
                    continue
        if isinstance(last_error, TimeoutError):
            raise JobDiscoveryTimeoutError("Job discovery search timed out.") from last_error
        raise JobDiscoveryProviderError(
            "Job discovery search failed after retries."
        ) from last_error


def _bounded_raw_evidence(item: dict[str, Any]) -> dict[str, Any]:
    raw: dict[str, Any] = {}
    for key in ("title", "url", "description"):
        value = item.get(key)
        if isinstance(value, str):
            raw[key] = value[:500]
    return raw


def _retry_backoff_seconds(attempt: int) -> float:
    backoff = 0.25 * float(2**attempt)
    return min(backoff, 1.0)
