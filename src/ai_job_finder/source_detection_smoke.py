from __future__ import annotations

import os

from ai_job_finder.application.source_detection import _extract_greenhouse_tokens
from ai_job_finder.infrastructure.job_sources.greenhouse import GreenhouseJobSourceConnector
from ai_job_finder.infrastructure.public_fetcher import (
    PublicPageFetcherConfig,
    SafePublicPageFetcher,
)
from ai_job_finder.settings import get_settings


def main() -> int:
    if os.environ.get("AI_JOB_FINDER_RUN_SOURCE_DETECTION_SMOKE") != "true":
        print(
            "Skipped. Set AI_JOB_FINDER_RUN_SOURCE_DETECTION_SMOKE=true to run a live "
            "read-only source detection check."
        )
        return 0
    url = os.environ.get("AI_JOB_FINDER_SOURCE_DETECTION_SMOKE_URL")
    if not url:
        print("AI_JOB_FINDER_SOURCE_DETECTION_SMOKE_URL is required.")
        return 1
    settings = get_settings()
    fetcher = SafePublicPageFetcher(
        PublicPageFetcherConfig(
            timeout_seconds=settings.source_detection_timeout_seconds,
            transient_retry_count=settings.source_detection_transient_retry_count,
            max_response_bytes=settings.source_detection_max_response_bytes,
            max_redirects=settings.source_detection_max_redirects,
            allowed_ports=settings.source_detection_allowed_ports,
            user_agent=settings.greenhouse_user_agent,
        )
    )
    validator = GreenhouseJobSourceConnector(
        api_base_url=settings.greenhouse_api_base_url,
        timeout_seconds=settings.greenhouse_timeout_seconds,
        transient_retry_count=settings.greenhouse_transient_retry_count,
        user_agent=settings.greenhouse_user_agent,
        max_response_bytes=settings.greenhouse_max_response_bytes,
        max_jobs=settings.greenhouse_max_jobs,
    )
    page = fetcher.fetch(url)
    tokens = []
    seen: set[str] = set()
    for item in _extract_greenhouse_tokens(page.text, source_url=page.final_url, source="html"):
        token = str(item["token"])
        if token not in seen:
            seen.add(token)
            tokens.append(token)
    print(f"final_url={page.final_url}")
    if not tokens:
        print("detected_token=none")
        return 1
    for token in tokens:
        validation = validator.validate_board_token(token)
        if validation.valid:
            print(f"detected_token={token}")
            print(f"job_count={validation.job_count}")
            return 0
    print(f"detected_token={tokens[0]}")
    print("job_count=unvalidated")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
