from __future__ import annotations

from ai_job_finder.bootstrap import cli as _cli
from ai_job_finder.bootstrap.cli import HarnessConfig, format_failure, parse_args
from ai_job_finder.bootstrap.client import (
    ApiClient,
    is_bootstrap_owned_candidate,
    is_bootstrap_owned_fact,
    is_localhost_url,
    parse_json_body,
)
from ai_job_finder.bootstrap.contracts import (
    CandidateResponse,
    HarnessError,
    JobLeadResponse,
    JobLeadSource,
    WorkplaceType,
)
from ai_job_finder.bootstrap.fixtures import (
    BOOTSTRAP_OWNER,
    BOOTSTRAP_SOURCE_PREFIX,
    SCORING_VERSION,
)
from ai_job_finder.bootstrap.harness import BootstrapHarness


def main(argv: list[str] | None = None) -> int:
    return _cli.main(argv)


__all__ = [
    "BOOTSTRAP_OWNER",
    "BOOTSTRAP_SOURCE_PREFIX",
    "SCORING_VERSION",
    "ApiClient",
    "BootstrapHarness",
    "CandidateResponse",
    "HarnessConfig",
    "HarnessError",
    "JobLeadResponse",
    "JobLeadSource",
    "WorkplaceType",
    "format_failure",
    "is_bootstrap_owned_candidate",
    "is_bootstrap_owned_fact",
    "is_localhost_url",
    "main",
    "parse_args",
    "parse_json_body",
]
