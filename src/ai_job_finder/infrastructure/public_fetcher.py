from __future__ import annotations

import ipaddress
import socket
import time
from collections.abc import Iterable
from dataclasses import dataclass
from email.message import Message
from typing import IO, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, OpenerDirector, Request, build_opener

from ai_job_finder.domain.errors import (
    BlockedRedirectError,
    OversizedResponseError,
    UnavailablePageError,
    UnsafeUrlError,
    UnsupportedContentTypeError,
)
from ai_job_finder.domain.source_detection import PublicPage


class _ReadableResponse(Protocol):
    headers: Message[str, str]

    def read(self, limit: int = -1) -> bytes: ...


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        return None


@dataclass(frozen=True, slots=True)
class PublicPageFetcherConfig:
    timeout_seconds: float
    transient_retry_count: int
    max_response_bytes: int
    max_redirects: int
    allowed_ports: Iterable[int]
    user_agent: str
    allowed_content_types: tuple[str, ...] = (
        "text/html",
        "application/xhtml+xml",
        "text/plain",
        "application/javascript",
        "text/javascript",
    )


class SafePublicPageFetcher:
    def __init__(self, config: PublicPageFetcherConfig) -> None:
        self.config = config
        self._allowed_ports = set(config.allowed_ports)
        self._opener: OpenerDirector = build_opener(_NoRedirectHandler)

    def fetch(self, url: str) -> PublicPage:
        normalized_url = self.normalize_url(url)
        requested_url = normalized_url
        redirects = 0
        attempts = self.config.transient_retry_count + 1
        while True:
            self._validate_url(normalized_url)
            request = Request(
                normalized_url,
                headers={
                    "User-Agent": self.config.user_agent,
                    "Accept": (
                        "text/html,application/xhtml+xml,text/plain,"
                        "application/javascript,text/javascript;q=0.9,*/*;q=0.1"
                    ),
                },
            )
            last_error: Exception | None = None
            for attempt in range(attempts):
                try:
                    response_context = self._opener.open(
                        request, timeout=self.config.timeout_seconds
                    )
                    with response_context as response:
                        content_type = self._content_type(response.headers.get("Content-Type"))
                        self._validate_content_type(content_type)
                        text = self._read_text(response, normalized_url)
                        final_url = response.geturl()
                        self._validate_url(final_url)
                        return PublicPage(
                            requested_url=requested_url,
                            final_url=final_url,
                            content_type=content_type,
                            text=text,
                        )
                except HTTPError as exc:
                    if exc.code in {301, 302, 303, 307, 308}:
                        location = exc.headers.get("Location")
                        if not location:
                            raise BlockedRedirectError(
                                "Redirect did not include a target URL."
                            ) from exc
                        redirects += 1
                        if redirects > self.config.max_redirects:
                            raise BlockedRedirectError("Redirect limit exceeded.") from exc
                        next_url = self.normalize_url(urljoin(normalized_url, location))
                        try:
                            self._validate_url(next_url)
                        except UnsafeUrlError as unsafe_exc:
                            raise BlockedRedirectError(
                                "Redirect target was blocked."
                            ) from unsafe_exc
                        normalized_url = next_url
                        break
                    if exc.code in {408, 429, 500, 502, 503, 504}:
                        last_error = exc
                        if attempt < attempts - 1:
                            time.sleep(_retry_backoff_seconds(attempt))
                            continue
                    raise UnavailablePageError("Public page fetch failed.") from exc
                except (TimeoutError, URLError, OSError) as exc:
                    last_error = exc
                    if attempt < attempts - 1:
                        time.sleep(_retry_backoff_seconds(attempt))
                        continue
                    raise UnavailablePageError("Public page fetch failed.") from exc
            else:
                raise UnavailablePageError("Public page fetch failed.") from last_error

    @staticmethod
    def normalize_url(url: str) -> str:
        value = url.strip()
        parts = urlsplit(value)
        if not parts.scheme:
            value = f"https://{value}"
            parts = urlsplit(value)
        if parts.username or parts.password:
            raise UnsafeUrlError("URLs with embedded credentials are not supported.")
        scheme = parts.scheme.lower()
        host = (parts.hostname or "").lower().rstrip(".")
        if not host:
            raise UnsafeUrlError("URL host is required.")
        port = f":{parts.port}" if parts.port is not None else ""
        netloc = f"{host}{port}"
        path = parts.path or "/"
        return urlunsplit((scheme, netloc, path, parts.query, ""))

    def _validate_url(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"}:
            raise UnsafeUrlError("Only HTTP and HTTPS URLs are supported.")
        if parts.username or parts.password:
            raise UnsafeUrlError("URLs with embedded credentials are not supported.")
        host = (parts.hostname or "").lower().rstrip(".")
        if not host:
            raise UnsafeUrlError("URL host is required.")
        if host in {"localhost", "metadata.google.internal"}:
            raise UnsafeUrlError("URL host is not public.")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        if port not in self._allowed_ports:
            raise UnsafeUrlError("URL port is not allowed.")
        for address in _resolve_public_addresses(host):
            if _is_blocked_address(address):
                raise UnsafeUrlError("URL host resolved to a non-public address.")

    def _validate_content_type(self, content_type: str) -> None:
        if not any(
            content_type.startswith(allowed) for allowed in self.config.allowed_content_types
        ):
            raise UnsupportedContentTypeError("Fetched page content type is not supported.")

    def _read_text(self, response: _ReadableResponse, url: str) -> str:
        raw = response.read(self.config.max_response_bytes + 1)
        if len(raw) > self.config.max_response_bytes:
            raise OversizedResponseError("Fetched page exceeded the configured size limit.")
        encoding = response.headers.get_content_charset() or "utf-8"
        try:
            return raw.decode(encoding, errors="replace")
        except LookupError as exc:
            raise UnsupportedContentTypeError(f"Unsupported response charset for {url}.") from exc

    @staticmethod
    def _content_type(value: str | None) -> str:
        if not value:
            return "application/octet-stream"
        return value.split(";", 1)[0].strip().lower()


def _resolve_public_addresses(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    literal = _parse_ip_literal(host)
    if literal is not None:
        return [literal]
    try:
        records = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUrlError("URL host could not be resolved.") from exc
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for record in records:
        sockaddr = record[4]
        address_value = sockaddr[0]
        addresses.append(ipaddress.ip_address(address_value))
    if not addresses:
        raise UnsafeUrlError("URL host could not be resolved.")
    return addresses


def _parse_ip_literal(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    if host.isdigit():
        try:
            return ipaddress.IPv4Address(int(host, 10))
        except ipaddress.AddressValueError:
            return None
    if host.startswith("0x"):
        try:
            return ipaddress.IPv4Address(int(host, 16))
        except ValueError, ipaddress.AddressValueError:
            return None
    return None


def _is_blocked_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if address.is_loopback or address.is_private or address.is_link_local:
        return True
    if address.is_multicast or address.is_unspecified or address.is_reserved:
        return True
    if isinstance(address, ipaddress.IPv4Address) and address == ipaddress.IPv4Address(
        "169.254.169.254"
    ):
        return True
    return False


def _retry_backoff_seconds(attempt: int) -> float:
    backoff = 0.25 * float(2**attempt)
    return min(backoff, 1.0)
