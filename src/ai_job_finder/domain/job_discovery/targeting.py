from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from ai_job_finder.domain.enums import JobSourceProvider

GREENHOUSE_HOSTS = frozenset(
    {
        "boards.greenhouse.io",
        "job-boards.greenhouse.io",
        "boards-api.greenhouse.io",
    }
)

ASHBY_CANONICAL_HOST = "jobs.ashbyhq.com"
ASHBY_HOSTS = frozenset({ASHBY_CANONICAL_HOST})
ASHBY_BOARD_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,199}")
LEVER_CANONICAL_HOST = "jobs.lever.co"
LEVER_HOSTS = frozenset({LEVER_CANONICAL_HOST})
LEVER_BOARD_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,199}")
LEVER_POSTING_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,199}")


@dataclass(frozen=True, slots=True)
class GreenhouseUrl:
    board_token: str
    external_posting_id: str | None


def parse_greenhouse_url(url: str) -> GreenhouseUrl | None:
    greenhouse_board_token_pattern = ASHBY_BOARD_TOKEN_PATTERN
    greenhouse_posting_id_pattern = LEVER_POSTING_ID_PATTERN
    parts = urlsplit(url)
    if (parts.hostname or "").casefold().rstrip(".") not in GREENHOUSE_HOSTS:
        return None
    path_parts = [part for part in parts.path.split("/") if part]
    if not path_parts or not greenhouse_board_token_pattern.fullmatch(path_parts[0]):
        return None
    if len(path_parts) == 1:
        return GreenhouseUrl(board_token=path_parts[0].casefold(), external_posting_id=None)
    if (
        len(path_parts) != 3
        or path_parts[1].casefold() != "jobs"
        or not greenhouse_posting_id_pattern.fullmatch(path_parts[2])
    ):
        return None
    return GreenhouseUrl(board_token=path_parts[0].casefold(), external_posting_id=path_parts[2])


@dataclass(frozen=True, slots=True)
class AshbyUrl:
    board_token: str
    external_posting_id: str | None


def parse_ashby_url(url: str) -> AshbyUrl | None:
    parts = urlsplit(url)
    if (parts.hostname or "").casefold().rstrip(".") not in ASHBY_HOSTS:
        return None
    path_parts = [part for part in parts.path.split("/") if part]
    if not path_parts or not ASHBY_BOARD_TOKEN_PATTERN.fullmatch(path_parts[0]):
        return None
    external_posting_id = path_parts[1] if len(path_parts) > 1 else None
    if external_posting_id == "application" or len(path_parts) > 2:
        return None
    return AshbyUrl(board_token=path_parts[0], external_posting_id=external_posting_id)


@dataclass(frozen=True, slots=True)
class LeverUrl:
    board_token: str
    external_posting_id: str | None


def parse_lever_url(url: str) -> LeverUrl | None:
    parts = urlsplit(url)
    if (parts.hostname or "").casefold().rstrip(".") not in LEVER_HOSTS:
        return None
    path_parts = [part for part in parts.path.split("/") if part]
    if not path_parts or not LEVER_BOARD_TOKEN_PATTERN.fullmatch(path_parts[0]):
        return None
    external_posting_id = path_parts[1] if len(path_parts) > 1 else None
    if external_posting_id is not None and not LEVER_POSTING_ID_PATTERN.fullmatch(
        external_posting_id
    ):
        return None
    if len(path_parts) > 2:
        return None
    return LeverUrl(board_token=path_parts[0], external_posting_id=external_posting_id)


@dataclass(frozen=True, slots=True)
class SupportedAtsUrl:
    provider: JobSourceProvider
    board_token: str
    external_posting_id: str | None


def parse_supported_ats_url(url: str) -> SupportedAtsUrl | None:
    greenhouse = parse_greenhouse_url(url)
    if greenhouse is not None:
        return SupportedAtsUrl(
            provider=JobSourceProvider.GREENHOUSE,
            board_token=greenhouse.board_token,
            external_posting_id=greenhouse.external_posting_id,
        )
    ashby = parse_ashby_url(url)
    if ashby is not None:
        return SupportedAtsUrl(
            provider=JobSourceProvider.ASHBY,
            board_token=ashby.board_token,
            external_posting_id=ashby.external_posting_id,
        )
    lever = parse_lever_url(url)
    if lever is not None:
        return SupportedAtsUrl(
            provider=JobSourceProvider.LEVER,
            board_token=lever.board_token,
            external_posting_id=lever.external_posting_id,
        )
    return None


DISCOVERY_ATS_QUERY_HOSTS = (
    "boards.greenhouse.io",
    "jobs.ashbyhq.com",
    "jobs.lever.co",
)

DISCOVERY_EXCLUDED_AGGREGATOR_DOMAINS = (
    "indeed.com",
    "linkedin.com",
    "glassdoor.com",
    "ziprecruiter.com",
)

DISCOVERY_BROAD_QUERY_EXCLUDED_DOMAINS = (
    *DISCOVERY_EXCLUDED_AGGREGATOR_DOMAINS,
    "builtin.com",
    "wellfound.com",
    "theladders.com",
    "virtualvocations.com",
    "dice.com",
)


def discovery_excluded_aggregator_domain(url: str) -> str | None:
    host = (urlsplit(url).hostname or "").casefold().rstrip(".")
    if not host:
        return None
    for domain in DISCOVERY_EXCLUDED_AGGREGATOR_DOMAINS:
        if host == domain or host.endswith(f".{domain}"):
            return domain
    return None


def discovery_result_index_reason(url: str, *, title_hint: str | None) -> str | None:
    """Return a reason only for result shapes that cannot represent one job posting."""
    if parse_supported_ats_url(url) is not None:
        return None

    parts = urlsplit(url)
    path = parts.path.casefold().rstrip("/")
    if path == "/search" or path.startswith("/search/"):
        return "Excluded generic search result before source detection."
    if path.startswith("/jobs/search") or path.startswith("/job-search"):
        return "Excluded generic job-search result before source detection."

    normalized_title = " ".join((title_hint or "").casefold().split())
    if normalized_title.startswith("best ") and " jobs" in normalized_title:
        return "Excluded generic jobs-list result before source detection."
    return None
