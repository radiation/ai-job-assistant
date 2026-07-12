from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import UUID

from ai_job_finder.domain.enums import JobSourceProvider
from ai_job_finder.domain.job_sources import JobSourceConfigurationSnapshot
from ai_job_finder.infrastructure.job_sources.greenhouse import GreenhouseJobSourceConnector
from ai_job_finder.settings import get_settings


def main() -> int:
    if os.environ.get("AI_JOB_FINDER_RUN_GREENHOUSE_SMOKE") != "true":
        print(
            "Skipped. Set AI_JOB_FINDER_RUN_GREENHOUSE_SMOKE=true to run a live fetch-only check."
        )
        return 0
    board_token = os.environ.get("AI_JOB_FINDER_GREENHOUSE_SMOKE_BOARD_TOKEN")
    company_name = os.environ.get(
        "AI_JOB_FINDER_GREENHOUSE_SMOKE_COMPANY", board_token or "Greenhouse"
    )
    if not board_token:
        print("Greenhouse smoke requires AI_JOB_FINDER_GREENHOUSE_SMOKE_BOARD_TOKEN.")
        return 1
    settings = get_settings()
    connector = GreenhouseJobSourceConnector(
        api_base_url=settings.greenhouse_api_base_url,
        timeout_seconds=settings.greenhouse_timeout_seconds,
        transient_retry_count=settings.greenhouse_transient_retry_count,
        user_agent=settings.greenhouse_user_agent,
        max_response_bytes=settings.greenhouse_max_response_bytes,
        max_jobs=settings.greenhouse_max_jobs,
    )
    source = JobSourceConfigurationSnapshot(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        provider=JobSourceProvider.GREENHOUSE,
        display_name=f"{company_name} smoke",
        company_name=company_name,
        board_token=board_token,
        source_url=f"https://boards.greenhouse.io/{board_token}",
        enabled=True,
        last_successful_sync_at=None,
        last_sync_status=None,
        last_sync_error=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    result = connector.fetch_jobs(source)
    print(f"connector_version={result.connector_version}")
    print(f"jobs_fetched={len(result.jobs)}")
    for job in result.jobs[:3]:
        print(f"job id={job.external_id} title={job.title!r} url={job.source_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
