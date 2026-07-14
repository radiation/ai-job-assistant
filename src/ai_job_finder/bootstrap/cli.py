from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from ai_job_finder.bootstrap.client import ApiClient
from ai_job_finder.bootstrap.contracts import HarnessError, _metadata_to_dict
from ai_job_finder.bootstrap.harness import BootstrapHarness

DEFAULT_BASE_URL = os.environ.get("AI_JOB_FINDER_BASE_URL", "http://localhost:8000")
DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("AI_JOB_FINDER_BOOTSTRAP_TIMEOUT", "10"))
DEFAULT_READINESS_TIMEOUT_SECONDS = float(
    os.environ.get("AI_JOB_FINDER_BOOTSTRAP_READINESS_TIMEOUT", "30")
)


@dataclass(slots=True)
class HarnessConfig:
    base_url: str
    timeout: float
    readiness_timeout: float
    reset: bool
    allow_destructive: bool
    allow_non_localhost_destructive: bool
    verbose: bool
    json_output: str | None
    document_ingestion: bool = False
    fake_greenhouse: bool = False
    fake_greenhouse_fixture_path: Path | None = None


def parse_args(argv: list[str] | None = None) -> HarnessConfig:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--readiness-timeout", type=float, default=DEFAULT_READINESS_TIMEOUT_SECONDS
    )
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--allow-destructive", action="store_true")
    parser.add_argument("--allow-non-localhost-destructive", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json-output")
    parser.add_argument(
        "--document-ingestion",
        action="store_true",
        help=(
            "Run the optional document-ingestion acceptance phase. Configure the app with "
            "EXTRACTION_ENABLED=true and EXTRACTION_PROVIDER=fake for normal local use."
        ),
    )
    parser.add_argument(
        "--fake-greenhouse",
        action="store_true",
        help=(
            "Run the optional fake-Greenhouse acceptance phase against a file-backed "
            "fake connector."
        ),
    )
    parser.add_argument(
        "--fake-greenhouse-fixture-path",
        default=os.environ.get("GREENHOUSE_FAKE_FIXTURE_PATH"),
    )
    args = parser.parse_args(argv)
    return HarnessConfig(
        base_url=args.base_url,
        timeout=args.timeout,
        readiness_timeout=args.readiness_timeout,
        reset=args.reset,
        allow_destructive=args.allow_destructive,
        allow_non_localhost_destructive=args.allow_non_localhost_destructive,
        verbose=args.verbose,
        json_output=args.json_output,
        document_ingestion=args.document_ingestion,
        fake_greenhouse=args.fake_greenhouse,
        fake_greenhouse_fixture_path=(
            Path(args.fake_greenhouse_fixture_path) if args.fake_greenhouse_fixture_path else None
        ),
    )


def format_failure(error: HarnessError) -> str:
    lines = [
        f"FAIL phase={error.phase}",
        f"assertion={error.assertion}",
        f"endpoint={error.endpoint}",
        f"expected={error.expected}",
        f"actual={error.actual}",
    ]
    if error.response_body is not None:
        lines.append(f"response={json.dumps(error.response_body, default=str)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    config = parse_args(argv)
    client = ApiClient(config.base_url, config.timeout, verbose=config.verbose)
    harness = BootstrapHarness(client, config)
    try:
        metadata = harness.run()
    except HarnessError as error:
        harness._record_failure(error)
        print(format_failure(error), file=sys.stderr)
        metadata = harness.metadata
        if config.json_output:
            with open(config.json_output, "w", encoding="utf-8") as handle:
                json.dump(_metadata_to_dict(metadata), handle, indent=2)
        print(
            f"Acceptance checks: {metadata.passed} passed, {metadata.failed} failed",
            file=sys.stderr,
        )
        client.close()
        return 1
    if config.json_output:
        with open(config.json_output, "w", encoding="utf-8") as handle:
            json.dump(_metadata_to_dict(metadata), handle, indent=2)
    print(f"Acceptance checks: {metadata.passed} passed, {metadata.failed} failed")
    client.close()
    return 0
