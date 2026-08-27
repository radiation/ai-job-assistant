from __future__ import annotations

from urllib.parse import urlsplit

GREENHOUSE_HOSTS = frozenset(
    {
        "boards.greenhouse.io",
        "job-boards.greenhouse.io",
        "boards-api.greenhouse.io",
    }
)

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
