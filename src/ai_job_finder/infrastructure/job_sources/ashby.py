from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
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

CONNECTOR_VERSION = "ashby-posting-api-v1"


class AshbyJobSourceConnector:
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
        if source.provider is not JobSourceProvider.ASHBY:
            raise InvalidJobSourceError(f"Unsupported job source provider: {source.provider}.")
        payload = self._fetch_json(source.board_token)
        jobs_payload = payload.get("jobs")
        if not isinstance(jobs_payload, list):
            raise MalformedJobSourcePayloadError("Ashby response did not contain a jobs list.")
        if self.max_jobs is not None and len(jobs_payload) > self.max_jobs:
            raise JobSourceProviderError("Ashby response exceeded the configured job limit.")
        jobs: list[NormalizedJobPosting] = []
        failures: list[JobSourceItemFailure] = []
        for item in jobs_payload:
            try:
                jobs.append(parse_ashby_job(source, item))
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
                error_message="Ashby board token is required.",
            )
        try:
            payload = self._fetch_json(token)
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
        jobs = payload.get("jobs")
        if not isinstance(jobs, list):
            return JobSourceBoardValidation(
                token=token,
                status="malformed",
                valid=False,
                error_message="Ashby response did not contain a jobs list.",
            )
        titles = [
            str(item["title"]).strip()
            for item in jobs
            if isinstance(item, dict)
            and isinstance(item.get("title"), str)
            and item["title"].strip()
        ][:5]
        return JobSourceBoardValidation(
            token=token,
            status="valid_empty" if not jobs else "valid",
            valid=True,
            job_count=len(jobs),
            sample_titles=titles,
        )

    def _fetch_json(self, board_token: str) -> dict[str, Any]:
        request = Request(
            f"{self.api_base_url}/{quote(board_token, safe='')}",
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
                        "Ashby response exceeded the configured size limit."
                    )
                parsed = json.loads(raw.decode("utf-8"))
                if not isinstance(parsed, dict):
                    raise MalformedJobSourcePayloadError("Ashby response was not a JSON object.")
                return parsed
            except HTTPError as exc:
                if exc.code == 404:
                    raise InvalidJobSourceError("Ashby board token was not found.") from exc
                if exc.code not in {408, 429, 500, 502, 503, 504}:
                    raise JobSourceProviderError(f"Ashby returned HTTP {exc.code}.") from exc
                last_error = exc
            except TimeoutError as exc:
                last_error = exc
            except URLError as exc:
                last_error = exc
            if attempt < self.transient_retry_count:
                time.sleep(0.25 * (2**attempt))
        if isinstance(last_error, TimeoutError):
            raise JobSourceTimeoutError("Ashby request timed out.") from last_error
        raise JobSourceProviderError("Ashby request failed after retries.") from last_error


def parse_ashby_job(
    source: JobSourceConfigurationSnapshot, payload: dict[str, Any]
) -> NormalizedJobPosting:
    if not isinstance(payload, dict):
        raise MalformedJobSourcePayloadError("Ashby job payload was not an object.")
    external_id = _required_str(payload, "id")
    title = _required_str(payload, "title")
    description_raw = (
        _optional_str(payload.get("descriptionHtml"))
        or _optional_str(payload.get("descriptionPlain"))
        or ""
    )
    description_normalized = _optional_str(payload.get("descriptionPlain")) or html_to_plain_text(
        description_raw
    )
    location = _optional_str(payload.get("location"))
    return NormalizedJobPosting(
        provider=JobSourceProvider.ASHBY,
        company_name=source.company_name,
        title=title,
        location_text=location,
        workplace_type=_workplace_type(payload.get("workplaceType"), payload.get("isRemote")),
        description_raw=description_raw,
        description_normalized=description_normalized,
        compensation_text=None,
        source_url=_safe_http_url(_optional_str(payload.get("jobUrl")))
        or f"https://jobs.ashbyhq.com/{source.board_token}/{external_id}",
        external_id=external_id,
        internal_job_id=None,
        source_updated_at=_parse_datetime(_optional_str(payload.get("publishedAt"))),
        departments=_names(payload.get("department")),
        offices=[location] if location else [],
        metadata={
            "employment_type": _optional_str(payload.get("employmentType")),
            "team": _optional_str(payload.get("team")),
            "is_remote": payload.get("isRemote")
            if isinstance(payload.get("isRemote"), bool)
            else None,
        },
        raw_payload=payload,
    )


def _required_str(payload: dict[str, Any], field_name: str) -> str:
    value = _optional_str(payload.get(field_name))
    if value is None:
        raise MalformedJobSourcePayloadError(f"Ashby job payload is missing {field_name}.")
    return value


def _optional_str(value: Any) -> str | None:
    if isinstance(value, (int, float)):
        return str(value)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _identity_hint(payload: Any) -> str | None:
    return _optional_str(payload.get("id")) if isinstance(payload, dict) else None


def _names(value: Any) -> list[str]:
    return [value.strip()] if isinstance(value, str) and value.strip() else []


def _workplace_type(value: Any, is_remote: Any) -> WorkplaceType | None:
    normalized = _optional_str(value)
    if normalized:
        try:
            return WorkplaceType(normalized.casefold())
        except ValueError:
            pass
    return WorkplaceType.REMOTE if is_remote is True else None


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _safe_http_url(value: str | None) -> str | None:
    if value is None:
        return None
    parts = urlsplit(value)
    if parts.scheme.casefold() not in {"http", "https"} or not parts.netloc:
        return None
    return urlunsplit(
        (parts.scheme.casefold(), parts.netloc.casefold(), parts.path, parts.query, "")
    )
