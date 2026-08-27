from __future__ import annotations

import pytest

from ai_job_finder.domain.errors import InvalidJobDiscoveryUrlError
from ai_job_finder.domain.job_discovery import normalize_job_discovery_url
from ai_job_finder.domain.job_discovery.targeting import parse_lever_url


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


@pytest.mark.parametrize(
    ("url", "board_token", "external_posting_id"),
    [
        (
            "https://jobs.lever.co/LuminDigital/04866248-eacc-4955-9696-50e427b60a7e",
            "LuminDigital",
            "04866248-eacc-4955-9696-50e427b60a7e",
        ),
        ("https://jobs.lever.co/aledade", "aledade", None),
    ],
)
def test_parse_lever_url_extracts_board_and_optional_posting_id(
    url: str, board_token: str, external_posting_id: str | None
) -> None:
    parsed = parse_lever_url(url)

    assert parsed is not None
    assert parsed.board_token == board_token
    assert parsed.external_posting_id == external_posting_id


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/LuminDigital/04866248-eacc-4955-9696-50e427b60a7e",
        "https://jobs.lever.co/LuminDigital/posting/extra",
        "https://jobs.ashbyhq.com/LuminDigital/posting-123",
    ],
)
def test_parse_lever_url_does_not_claim_noncanonical_urls(url: str) -> None:
    assert parse_lever_url(url) is None
