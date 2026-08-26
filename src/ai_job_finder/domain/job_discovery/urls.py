from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ai_job_finder.domain.errors import InvalidJobDiscoveryUrlError

TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
}


def normalize_job_discovery_url(url: str) -> str:
    value = url.strip()
    if not value:
        raise InvalidJobDiscoveryUrlError("Discovered URL is required.")
    parts = urlsplit(value)
    if parts.username or parts.password:
        raise InvalidJobDiscoveryUrlError(
            "Discovered URLs with embedded credentials are not supported."
        )
    if parts.scheme.lower() not in {"http", "https"}:
        raise InvalidJobDiscoveryUrlError("Only HTTP and HTTPS discovered URLs are supported.")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise InvalidJobDiscoveryUrlError("Discovered URL host is required.")
    port = parts.port
    if port == 80 and parts.scheme.lower() == "http":
        port = None
    if port == 443 and parts.scheme.lower() == "https":
        port = None
    netloc = host if port is None else f"{host}:{port}"
    path = parts.path or "/"
    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_") and key.casefold() not in TRACKING_QUERY_KEYS
    ]
    query = urlencode(filtered_query, doseq=True)
    return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))
