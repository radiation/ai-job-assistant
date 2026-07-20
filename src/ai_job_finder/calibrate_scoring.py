from __future__ import annotations

import argparse
from pathlib import Path

from ai_job_finder.application.job_searches.calibration import (
    format_calibration_report,
    run_scoring_calibration,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the deterministic scoring calibration harness."
    )
    parser.add_argument("--fixture", default=None)
    args = parser.parse_args()
    report = run_scoring_calibration(Path(args.fixture) if args.fixture else None)
    print(format_calibration_report(report))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
