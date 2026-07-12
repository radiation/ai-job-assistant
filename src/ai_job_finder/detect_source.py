from __future__ import annotations

import argparse

from ai_job_finder.application.source_detection import (
    SourceDetectionConfig,
    approve_source_detection_run,
    create_source_detection_run,
)
from ai_job_finder.infrastructure.database.models import SourceDetectionRunModel
from ai_job_finder.infrastructure.database.session import get_session_factory
from ai_job_finder.infrastructure.job_sources.fake import FileBackedFakeJobSourceConnector
from ai_job_finder.infrastructure.job_sources.greenhouse import GreenhouseJobSourceConnector
from ai_job_finder.infrastructure.public_fetcher import (
    PublicPageFetcherConfig,
    SafePublicPageFetcher,
)
from ai_job_finder.settings import Settings, get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect a deterministic Greenhouse job source.")
    parser.add_argument("--company", dest="company_name")
    parser.add_argument("--url", dest="input_url")
    parser.add_argument("--alias", dest="brand_alias")
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--create-and-sync", action="store_true")
    parser.add_argument("--select-token")
    args = parser.parse_args()
    if not args.company_name and not args.input_url:
        parser.error("provide --company, --url, or both")
    if args.create and args.create_and_sync:
        parser.error("use only one of --create or --create-and-sync")

    settings = get_settings()
    connector = _greenhouse_connector(settings)
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
    with get_session_factory()() as session:
        run = create_source_detection_run(
            session,
            company_name=args.company_name,
            input_url=args.input_url,
            brand_alias=args.brand_alias,
            fetcher=fetcher,
            validator=connector,
            config=SourceDetectionConfig(
                max_linked_scripts=settings.source_detection_max_linked_scripts,
                max_script_bytes=settings.source_detection_max_script_bytes,
                total_script_bytes=settings.source_detection_total_script_bytes,
            ),
        )
        _print_run(run)
        if args.create or args.create_and_sync:
            result = approve_source_detection_run(
                session,
                run_id=run.id,
                selected_token=args.select_token,
                create_and_sync=args.create_and_sync,
                connector=connector,
                retain_raw_payload=settings.greenhouse_retain_raw_payload,
                close_on_empty=settings.greenhouse_close_on_empty_result,
                stale_after_seconds=settings.job_source_stale_after_seconds,
            )
            print(
                " ".join(
                    [
                        f"source_id={result.source.id}",
                        f"token={result.source.board_token}",
                        f"existing={str(result.existing_source).lower()}",
                    ]
                )
            )
            if result.import_run:
                print(
                    " ".join(
                        [
                            f"import_run_id={result.import_run.id}",
                            f"import_status={result.import_run.status}",
                            f"fetched={result.import_run.jobs_fetched}",
                        ]
                    )
                )
    return 0 if run.status in {"detected", "ambiguous", "source_created"} else 1


def _greenhouse_connector(
    settings: Settings,
) -> GreenhouseJobSourceConnector | FileBackedFakeJobSourceConnector:
    if settings.greenhouse_fake_fixture_path is not None:
        return FileBackedFakeJobSourceConnector(settings.greenhouse_fake_fixture_path)
    return GreenhouseJobSourceConnector(
        api_base_url=settings.greenhouse_api_base_url,
        timeout_seconds=settings.greenhouse_timeout_seconds,
        transient_retry_count=settings.greenhouse_transient_retry_count,
        user_agent=settings.greenhouse_user_agent,
        max_response_bytes=settings.greenhouse_max_response_bytes,
        max_jobs=settings.greenhouse_max_jobs,
    )


def _print_run(run: SourceDetectionRunModel) -> None:
    print(
        " ".join(
            [
                f"run_id={run.id}",
                f"status={run.status}",
                f"provider={run.detected_provider or 'none'}",
                f"token={run.validated_token or 'none'}",
                (
                    f"jobs={run.validated_job_count}"
                    if run.validated_job_count is not None
                    else "jobs=unknown"
                ),
            ]
        )
    )
    if run.final_url:
        print(f"final_url={run.final_url}")
    for candidate in run.candidate_tokens:
        validation = candidate.get("validation", {}) if isinstance(candidate, dict) else {}
        print(
            " ".join(
                [
                    f"candidate={candidate.get('token')}",
                    f"source={candidate.get('source')}",
                    f"status={validation.get('status')}",
                    f"jobs={validation.get('job_count')}",
                    f"existing={candidate.get('existing_source_configuration_id') or 'false'}",
                ]
            )
        )
        titles = validation.get("sample_titles")
        if titles:
            print(f"sample_titles={', '.join(titles)}")
    if run.error_message:
        print(f"error={run.error_message}")


if __name__ == "__main__":
    raise SystemExit(main())
