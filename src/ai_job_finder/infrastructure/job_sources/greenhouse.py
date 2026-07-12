from __future__ import annotations

import html
import re
import time
from datetime import UTC, datetime
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
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

CONNECTOR_VERSION = "greenhouse-board-api-v1"


class GreenhouseJobSourceConnector:
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
        if source.provider is not JobSourceProvider.GREENHOUSE:
            raise InvalidJobSourceError(f"Unsupported job source provider: {source.provider}.")
        payload = self._fetch_json(source.board_token)
        jobs_payload = payload.get("jobs")
        if not isinstance(jobs_payload, list):
            raise MalformedJobSourcePayloadError("Greenhouse response did not contain a jobs list.")
        if self.max_jobs is not None and len(jobs_payload) > self.max_jobs:
            raise JobSourceProviderError("Greenhouse response exceeded the configured job limit.")

        jobs: list[NormalizedJobPosting] = []
        job_failures: list[JobSourceItemFailure] = []
        for item in jobs_payload:
            try:
                jobs.append(parse_greenhouse_job(source, item))
            except MalformedJobSourcePayloadError as exc:
                job_failures.append(
                    JobSourceItemFailure(
                        external_id=_job_identity_hint(item),
                        message=str(exc),
                    )
                )

        return JobSourceFetchResult(
            jobs=jobs,
            fetched_at=utc_now(),
            connector_version=CONNECTOR_VERSION,
            job_failures=job_failures,
        )

    def _fetch_json(self, board_token: str) -> dict[str, Any]:
        import json

        query = urlencode({"content": "true"})
        url = f"{self.api_base_url}/boards/{board_token}/jobs?{query}"
        request = Request(
            url,
            headers={"User-Agent": self.user_agent, "Accept": "application/json"},
        )
        last_error: Exception | None = None
        attempts = self.transient_retry_count + 1
        for attempt in range(attempts):
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    decoded = self._read_response_text(response)
                try:
                    parsed = json.loads(decoded)
                except json.JSONDecodeError as exc:
                    raise MalformedJobSourcePayloadError(
                        "Greenhouse response was not valid JSON."
                    ) from exc
                if not isinstance(parsed, dict):
                    raise MalformedJobSourcePayloadError(
                        "Greenhouse response was not a JSON object."
                    )
                return parsed
            except HTTPError as exc:
                if exc.code == 404:
                    raise InvalidJobSourceError("Greenhouse board token was not found.") from exc
                if exc.code in {408, 429, 500, 502, 503, 504}:
                    last_error = exc
                    if attempt < attempts - 1:
                        time.sleep(_retry_backoff_seconds(attempt))
                    continue
                raise JobSourceProviderError(f"Greenhouse returned HTTP {exc.code}.") from exc
            except TimeoutError as exc:
                last_error = exc
                if attempt < attempts - 1:
                    time.sleep(_retry_backoff_seconds(attempt))
            except URLError as exc:
                last_error = exc
                if attempt < attempts - 1:
                    time.sleep(_retry_backoff_seconds(attempt))
        if isinstance(last_error, TimeoutError):
            raise JobSourceTimeoutError("Greenhouse request timed out.") from last_error
        raise JobSourceProviderError("Greenhouse request failed after retries.") from last_error

    def _read_response_text(self, response: Any) -> str:
        if self.max_response_bytes is None:
            return cast(bytes, response.read()).decode("utf-8")
        raw = cast(bytes, response.read(self.max_response_bytes + 1))
        if len(raw) > self.max_response_bytes:
            raise JobSourceProviderError("Greenhouse response exceeded the configured size limit.")
        return raw.decode("utf-8")


def parse_greenhouse_job(
    source: JobSourceConfigurationSnapshot,
    payload: dict[str, Any],
) -> NormalizedJobPosting:
    if not isinstance(payload, dict):
        raise MalformedJobSourcePayloadError("Greenhouse job payload was not an object.")
    external_id = _required_str(payload, "id")
    content = (
        _optional_str(payload.get("content")) or _optional_str(payload.get("description")) or ""
    )
    description_normalized = html_to_plain_text(content)
    metadata = _metadata(payload)
    departments = _names(payload.get("departments"))
    offices = _names(payload.get("offices"))
    location_text = _location_text(payload)
    return NormalizedJobPosting(
        provider=JobSourceProvider.GREENHOUSE,
        company_name=source.company_name,
        title=_required_str(payload, "title"),
        location_text=location_text,
        workplace_type=_derive_workplace_type(
            location_text=location_text,
            description_normalized=description_normalized,
            metadata=metadata,
        ),
        description_raw=content,
        description_normalized=description_normalized,
        compensation_text=_compensation_text(payload),
        source_url=_safe_http_url(_optional_str(payload.get("absolute_url"))),
        external_id=external_id,
        internal_job_id=_internal_job_id(payload),
        source_updated_at=_parse_datetime(_optional_str(payload.get("updated_at"))),
        departments=departments,
        offices=offices,
        metadata=metadata,
        raw_payload=payload,
    )


def html_to_plain_text(value: str) -> str:
    text = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", value)
    text = re.sub(r"(?i)</\s*(p|div|li|ul|ol|h[1-6])\s*>", "\n", text)
    text = re.sub(r"(?is)<\s*(script|style).*?>.*?</\s*\1\s*>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _required_str(payload: dict[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise MalformedJobSourcePayloadError(f"Greenhouse job payload is missing {field_name}.")


def _optional_str(value: Any) -> str | None:
    if isinstance(value, int):
        return str(value)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        if isinstance(item, dict):
            name = _optional_str(item.get("name"))
            if name:
                names.append(name)
    return names


def _location_text(payload: dict[str, Any]) -> str | None:
    location = payload.get("location")
    if isinstance(location, dict):
        return _optional_str(location.get("name"))
    return None


def _derive_workplace_type(
    *,
    location_text: str | None,
    description_normalized: str,
    metadata: dict[str, Any],
) -> WorkplaceType | None:
    metadata_value = _workplace_type_from_metadata(metadata)
    if metadata_value is not None:
        return metadata_value
    location_value = _classify_workplace_value(location_text)
    if location_value is not None:
        return location_value
    for line in description_normalized.splitlines():
        match = re.match(
            r"^(?:workplace|work|location)\s+type\s*:\s*(.+)$",
            line,
            flags=re.IGNORECASE,
        )
        if match:
            return _classify_workplace_value(match.group(1))
    return None


def _workplace_type_from_metadata(metadata: dict[str, Any]) -> WorkplaceType | None:
    for name, value in metadata.items():
        if _normalize_label(name) in {
            "workplace type",
            "workplace",
            "location type",
            "remote status",
        }:
            return _classify_workplace_value(_optional_str(value))
    return None


def _classify_workplace_value(value: str | None) -> WorkplaceType | None:
    if value is None:
        return None
    normalized = re.sub(r"\s+", " ", value.casefold()).strip()
    if not normalized:
        return None
    if re.search(r"\b(?:not|no)\b[^\n]{0,24}\bremote\b", normalized):
        if re.search(r"\bon[ -]?site\b|\bonsite\b|\bin office\b", normalized):
            return WorkplaceType.ONSITE
        return None
    if re.search(r"\bhybrid\b", normalized):
        return WorkplaceType.HYBRID
    if re.search(r"\bon[ -]?site\b|\bonsite\b|\bin office\b", normalized):
        return WorkplaceType.ONSITE
    if re.search(r"\bremote\b", normalized):
        return WorkplaceType.REMOTE
    return None


def _compensation_text(payload: dict[str, Any]) -> str | None:
    metadata = payload.get("metadata")
    if not isinstance(metadata, list):
        return None
    pieces: list[str] = []
    for item in metadata:
        if not isinstance(item, dict):
            continue
        name = _optional_str(item.get("name")) or ""
        value = _optional_str(item.get("value"))
        if value and any(token in name.casefold() for token in ["salary", "compensation", "pay"]):
            pieces.append(f"{name}: {value}")
    return "; ".join(pieces) if pieces else None


def _internal_job_id(payload: dict[str, Any]) -> str | None:
    internal = _optional_str(payload.get("internal_job_id"))
    if internal:
        return internal
    requisition = payload.get("requisition_id")
    return _optional_str(requisition)


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.replace("Z", "+00:00")
    if re.match(r".*[+-]\d{4}$", normalized):
        normalized = f"{normalized[:-2]}:{normalized[-2:]}"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _metadata(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("metadata")
    if not isinstance(metadata, list):
        return {}
    result: dict[str, Any] = {}
    for item in metadata:
        if not isinstance(item, dict):
            continue
        name = _optional_str(item.get("name"))
        if name:
            result[name] = item.get("value")
    return result


def _normalize_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _safe_http_url(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    hostname = parsed.hostname.casefold() if parsed.hostname else ""
    netloc = hostname
    if parsed.port is not None and not (
        (parsed.scheme == "http" and parsed.port == 80)
        or (parsed.scheme == "https" and parsed.port == 443)
    ):
        netloc = f"{hostname}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path or "/", parsed.query, ""))


def _job_identity_hint(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    external_id = payload.get("id")
    if isinstance(external_id, int):
        return str(external_id)
    if isinstance(external_id, str) and external_id.strip():
        return external_id.strip()
    return None


def _retry_backoff_seconds(attempt: int) -> float:
    return float(min(0.25 * (2**attempt), 1.0))
