from __future__ import annotations

import argparse
from uuid import UUID

from ai_job_finder.application.job_sources import run_job_source_import
from ai_job_finder.infrastructure.database.session import get_session_factory
from ai_job_finder.infrastructure.job_sources.greenhouse import GreenhouseJobSourceConnector
from ai_job_finder.settings import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync a configured public job source.")
    parser.add_argument("--source-id", required=True)
    args = parser.parse_args()

    settings = get_settings()
    connector = GreenhouseJobSourceConnector(
        api_base_url=settings.greenhouse_api_base_url,
        timeout_seconds=settings.greenhouse_timeout_seconds,
        transient_retry_count=settings.greenhouse_transient_retry_count,
        user_agent=settings.greenhouse_user_agent,
        max_response_bytes=settings.greenhouse_max_response_bytes,
        max_jobs=settings.greenhouse_max_jobs,
    )
    with get_session_factory()() as session:
        run = run_job_source_import(
            session,
            source_id=UUID(args.source_id),
            connector=connector,
            retain_raw_payload=settings.greenhouse_retain_raw_payload,
            close_on_empty=settings.greenhouse_close_on_empty_result,
            stale_after_seconds=settings.job_source_stale_after_seconds,
        )
    print(
        " ".join(
            [
                f"run_id={run.id}",
                f"status={run.status}",
                f"fetched={run.jobs_fetched}",
                f"created={run.jobs_created}",
                f"updated={run.jobs_updated}",
                f"unchanged={run.jobs_unchanged}",
                f"closed={run.jobs_closed}",
                f"evaluations={run.evaluations_created}",
            ]
        )
    )
    if run.error_message:
        print(f"error={run.error_message}")
    return 0 if run.status == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
