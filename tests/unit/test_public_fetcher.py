from __future__ import annotations

import gzip
from email.message import Message
from io import BytesIO

import pytest

from ai_job_finder.domain.errors import UnsafeUrlError
from ai_job_finder.infrastructure.public_fetcher import (
    PublicPageFetcherConfig,
    SafePublicPageFetcher,
)


def _fetcher() -> SafePublicPageFetcher:
    return SafePublicPageFetcher(
        PublicPageFetcherConfig(
            timeout_seconds=1,
            transient_retry_count=0,
            max_response_bytes=1024,
            max_redirects=1,
            allowed_ports=[80, 443],
            user_agent="test",
        )
    )


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/careers",
        "https://user:pass@example.com/careers",
        "http://localhost/careers",
        "http://127.0.0.1/careers",
        "http://[::1]/careers",
        "http://10.0.0.1/careers",
        "http://169.254.169.254/latest/meta-data",
        "http://2130706433/careers",
        "https://example.com:8443/careers",
    ],
)
def test_fetcher_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        _fetcher().fetch(url)


def test_fetcher_normalizes_plain_host_to_https() -> None:
    assert (
        SafePublicPageFetcher.normalize_url("example.com/careers") == "https://example.com/careers"
    )


def test_fetcher_decodes_bounded_gzip_response() -> None:
    headers = Message()
    headers["Content-Encoding"] = "gzip"
    headers["Content-Type"] = "text/html; charset=utf-8"

    class Response(BytesIO):
        def __init__(self) -> None:
            super().__init__(gzip.compress(b"<html>jobs</html>"))
            self.headers = headers

    assert _fetcher()._read_text(Response(), "https://example.com/careers") == "<html>jobs</html>"
