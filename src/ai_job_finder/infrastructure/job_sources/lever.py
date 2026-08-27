from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ai_job_finder.domain.common import utc_now
from ai_job_finder.domain.enums import JobSourceProvider, WorkplaceType
from ai_job_finder.domain.errors import (
    InvalidJobSourceError,
    JobSourceProviderError,
    JobSourceTimeoutError,
    MalformedJobSourcePayloadError,
)
from ai_job_finder.domain.job_sources import (
    JobSourceConfigurationSnapshot,
    JobSourceFetchResult,
    JobSourceItemFailure,
    NormalizedJobPosting,
)
from ai_job_finder.domain.source_detection import JobSourceBoardValidation
from ai_job_finder.infrastructure.job_sources.greenhouse import html_to_plain_text

CONNECTOR_VERSION = "lever-postings-api-v1"


class LeverJobSourceConnector:
    def __init__(
        self,
        *,
        api_base_url: str,
        timeout_seconds: float,
        transient_retry_count: int,
        user_agent: str,
        max_response_bytes: int | None,
        max_jobs: int | None,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transient_retry_count = transient_retry_count
        self.user_agent = user_agent
        self.max_response_bytes = max_response_bytes
        self.max_jobs = max_jobs

    def fetch_jobs(self, source: JobSourceConfigurationSnapshot) -> JobSourceFetchResult:
        if source.provider is not JobSourceProvider.LEVER:
            raise InvalidJobSourceError(f"Unsupported job source provider: {source.provider}.")
        jobs_payload = self._fetch_json(source.board_token)
        if self.max_jobs is not None and len(jobs_payload) > self.max_jobs:
            raise JobSourceProviderError("Lever response exceeded the configured job limit.")
        jobs: list[NormalizedJobPosting] = []
        failures: list[JobSourceItemFailure] = []
        for item in jobs_payload:
            try:
                jobs.append(parse_lever_job(source, item))
            except MalformedJobSourcePayloadError as exc:
                failures.append(
                    JobSourceItemFailure(external_id=_identity_hint(item), message=str(exc))
                )
        return JobSourceFetchResult(
            jobs=jobs,
            fetched_at=utc_now(),
            connector_version=CONNECTOR_VERSION,
            job_failures=failures,
        )

    def validate_board_token(self, board_token: str) -> JobSourceBoardValidation:
        token = board_token.strip()
        if not token:
            return JobSourceBoardValidation(
                token=token,
                status="invalid",
                valid=False,
                error_message="Lever board token is required.",
            )
        try:
            jobs = self._fetch_json(token)
        except InvalidJobSourceError as exc:
            return JobSourceBoardValidation(
                token=token, status="invalid", valid=False, error_message=str(exc)
            )
        except MalformedJobSourcePayloadError as exc:
            return JobSourceBoardValidation(
                token=token, status="malformed", valid=False, error_message=str(exc)
            )
        except JobSourceProviderError as exc:
            return JobSourceBoardValidation(
                token=token, status="unavailable", valid=False, error_message=str(exc)
            )
        titles = [
            title
            for item in jobs
            if isinstance(item, dict) and (title := _optional_str(item.get("text")))
        ][:5]
        return JobSourceBoardValidation(
            token=token,
            status="valid_empty" if not jobs else "valid",
            valid=True,
            job_count=len(jobs),
            sample_titles=titles,
        )

    def _fetch_json(self, board_token: str) -> list[dict[str, Any]]:
        request = Request(
            f"{self.api_base_url}/{quote(board_token, safe='')}?mode=json",
            headers={"User-Agent": self.user_agent, "Accept": "application/json"},
        )
        last_error: Exception | None = None
        for attempt in range(self.transient_retry_count + 1):
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    raw = cast(
                        bytes,
                        response.read()
                        if self.max_response_bytes is None
                        else response.read(self.max_response_bytes + 1),
                    )
                if self.max_response_bytes is not None and len(raw) > self.max_response_bytes:
                    raise JobSourceProviderError(
                        "Lever response exceeded the configured size limit."
                    )
                parsed = json.loads(raw.decode("utf-8"))
                if not isinstance(parsed, list) or not all(
                    isinstance(item, dict) for item in parsed
                ):
                    raise MalformedJobSourcePayloadError("Lever response was not a jobs list.")
                return parsed
            except HTTPError as exc:
                if exc.code == 404:
                    raise InvalidJobSourceError("Lever board token was not found.") from exc
                if exc.code not in {408, 429, 500, 502, 503, 504}:
                    raise JobSourceProviderError(f"Lever returned HTTP {exc.code}.") from exc
                last_error = exc
            except TimeoutError as exc:
                last_error = exc
            except URLError as exc:
                last_error = exc
            if attempt < self.transient_retry_count:
                time.sleep(0.25 * (2**attempt))
        if isinstance(last_error, TimeoutError):
            raise JobSourceTimeoutError("Lever request timed out.") from last_error
        raise JobSourceProviderError("Lever request failed after retries.") from last_error


def parse_lever_job(
    source: JobSourceConfigurationSnapshot, payload: dict[str, Any]
) -> NormalizedJobPosting:
    if not isinstance(payload, dict):
        raise MalformedJobSourcePayloadError("Lever job payload was not an object.")
    external_id = _required_str(payload, "id")
    title = _required_str(payload, "text")
    description_raw = _optional_str(payload.get("description")) or ""
    categories: dict[str, Any] = {}
    if isinstance(payload.get("categories"), dict):
        categories = payload["categories"]
    location = _optional_str(categories.get("location"))
    commitment = _optional_str(categories.get("commitment"))
    team = _optional_str(categories.get("team"))
    department = _optional_str(categories.get("department"))
    workplace_type = _workplace_type(
        _optional_str(payload.get("workplaceType")), location, description_raw
    )
    return NormalizedJobPosting(
        provider=JobSourceProvider.LEVER,
        company_name=source.company_name,
        title=title,
        location_text=location,
        workplace_type=workplace_type,
        description_raw=description_raw,
        description_normalized=html_to_plain_text(description_raw),
        compensation_text=None,
        source_url=f"https://jobs.lever.co/{source.board_token}/{external_id}",
        external_id=external_id,
        internal_job_id=None,
        source_updated_at=_parse_millis(payload.get("createdAt")),
        departments=[value for value in [department, team] if value],
        offices=[location] if location else [],
        metadata={
            "employment_type": commitment,
            "team": team,
            "workplace_type": _optional_str(payload.get("workplaceType")),
        },
        raw_payload=payload,
    )


def _required_str(payload: dict[str, Any], field_name: str) -> str:
    value = _optional_str(payload.get(field_name))
    if value is None:
        raise MalformedJobSourcePayloadError(f"Lever job payload is missing {field_name}.")
    return value


def _optional_str(value: Any) -> str | None:
    if isinstance(value, (int, float)):
        return str(value)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _identity_hint(payload: Any) -> str | None:
    return _optional_str(payload.get("id")) if isinstance(payload, dict) else None


def _workplace_type(
    value: str | None, location: str | None, description: str
) -> WorkplaceType | None:
    if value:
        try:
            return WorkplaceType(value.casefold())
        except ValueError:
            pass
    combined = " ".join(part for part in [location, description] if part).casefold()
    if "remote" in combined:
        return WorkplaceType.REMOTE
    if "hybrid" in combined:
        return WorkplaceType.HYBRID
    return None


def _parse_millis(value: Any) -> datetime | None:
    if not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    except OverflowError, OSError, ValueError:
        return None
