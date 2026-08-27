from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

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


def discovery_excluded_aggregator_domain(url: str) -> str | None:
    host = (urlsplit(url).hostname or "").casefold().rstrip(".")
    if not host:
        return None
    for domain in DISCOVERY_EXCLUDED_AGGREGATOR_DOMAINS:
        if host == domain or host.endswith(f".{domain}"):
            return domain
    return None
