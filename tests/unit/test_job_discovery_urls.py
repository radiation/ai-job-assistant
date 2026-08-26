from __future__ import annotations

import pytest

from ai_job_finder.domain.errors import InvalidJobDiscoveryUrlError
from ai_job_finder.domain.job_discovery import normalize_job_discovery_url


def test_normalize_job_discovery_url_collapses_equivalent_urls() -> None:
    assert (
        normalize_job_discovery_url("HTTPS://Example.COM:443/jobs/123#fragment")
        == "https://example.com/jobs/123"
    )


def test_normalize_job_discovery_url_preserves_meaningful_query_parameters() -> None:
    assert (
        normalize_job_discovery_url("https://example.com/jobs/123?gh_jid=abc123&ref=board")
        == "https://example.com/jobs/123?gh_jid=abc123&ref=board"
    )


def test_normalize_job_discovery_url_removes_tracking_parameters() -> None:
    assert (
        normalize_job_discovery_url(
            "https://example.com/jobs/123?utm_source=test&fbclid=1&gh_jid=abc123"
        )
        == "https://example.com/jobs/123?gh_jid=abc123"
    )


def test_normalize_job_discovery_url_rejects_invalid_scheme() -> None:
    with pytest.raises(InvalidJobDiscoveryUrlError):
        normalize_job_discovery_url("ftp://example.com/jobs/123")
