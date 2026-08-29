from __future__ import annotations

from ai_job_finder.api.dependencies import (
    job_discovery_provider_dependency,
    job_source_board_validator_dependency,
    job_source_connector_dependency,
    public_page_fetcher_dependency,
)
from ai_job_finder.application.job_discovery import (
    JobDiscoveryConfig,
    run_due_scheduled_discoveries,
    run_job_discovery,
)
from ai_job_finder.application.source_detection import SourceDetectionConfig
from ai_job_finder.infrastructure.database.session import get_db_session
from ai_job_finder.settings import get_settings


def main() -> int:
    settings = get_settings()
    provider = job_discovery_provider_dependency(settings)
    fetcher = public_page_fetcher_dependency(settings)
    board_validator = job_source_board_validator_dependency(settings)
    connector = job_source_connector_dependency(settings)
    config = JobDiscoveryConfig(
        max_queries_per_run=settings.job_discovery_max_queries_per_run,
        result_limit=settings.job_discovery_result_limit,
        max_total_candidates=settings.job_discovery_max_total_candidates,
        source_detection=SourceDetectionConfig(
            max_linked_scripts=settings.source_detection_max_linked_scripts,
            max_script_bytes=settings.source_detection_max_script_bytes,
            total_script_bytes=settings.source_detection_total_script_bytes,
        ),
        retain_raw_payload=settings.greenhouse_retain_raw_payload,
        close_on_empty=settings.greenhouse_close_on_empty_result,
        stale_after_seconds=settings.job_source_stale_after_seconds,
    )
    with next(get_db_session()) as session:
        results = run_due_scheduled_discoveries(
            session,
            run_discovery=lambda search_definition_id: run_job_discovery(
                session,
                search_definition_id=search_definition_id,
                provider_name=settings.job_discovery_provider,
                provider=provider,
                fetcher=fetcher,
                board_validator=board_validator,
                connector=connector,
                config=config,
            ),
        )
    print(f"Scheduled discovery completed for {len(results)} saved search(es).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
