from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

import psycopg

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+psycopg://postgres:postgres@localhost:5432/ai_job_finder_test"
)
POSTGRES_WAIT_TIMEOUT_SECONDS = 20
UNIT_TEST_PATH = "tests/unit"
INTEGRATION_TEST_PATH = "tests/integration"


def _run(*command: str) -> int:
    completed = subprocess.run(command, check=False)
    return completed.returncode


def _run_or_exit(*command: str) -> None:
    raise SystemExit(_run(*command))


def _postgres_connectable(database_url: str) -> bool:
    connect_url = database_url.replace("+psycopg", "", 1)
    deadline = time.monotonic() + POSTGRES_WAIT_TIMEOUT_SECONDS

    while time.monotonic() < deadline:
        try:
            with psycopg.connect(connect_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
            return True
        except psycopg.Error:
            time.sleep(1)

    return False


def _resolve_test_database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)


def _pytest_args(*test_paths: str) -> tuple[str, ...]:
    return ("uv", "run", "pytest", *test_paths)


def fast_checks_main() -> None:
    commands = [
        ("uv", "run", "ruff", "check", "."),
        ("uv", "run", "ruff", "format", "--check", "."),
        ("uv", "run", "mypy", "."),
    ]
    for command in commands:
        exit_code = _run(*command)
        if exit_code != 0:
            raise SystemExit(exit_code)


def format_main() -> None:
    commands = [
        ("uv", "run", "ruff", "check", "--fix", "."),
        ("uv", "run", "ruff", "format", "."),
    ]
    for command in commands:
        exit_code = _run(*command)
        if exit_code != 0:
            raise SystemExit(exit_code)


def tests_main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit", action="store_true")
    parser.add_argument("--integration", action="store_true")
    parser.add_argument("--require-postgres", action="store_true")
    args = parser.parse_args()

    if args.unit and args.integration:
        pytest_command = _pytest_args(UNIT_TEST_PATH, INTEGRATION_TEST_PATH)
    elif args.unit:
        pytest_command = _pytest_args(UNIT_TEST_PATH)
    elif args.integration:
        pytest_command = _pytest_args(INTEGRATION_TEST_PATH)
    else:
        pytest_command = _pytest_args()

    if args.require_postgres:
        test_database_url = _resolve_test_database_url()
        os.environ.setdefault("TEST_DATABASE_URL", test_database_url)
        if not _postgres_connectable(test_database_url):
            print(
                "PostgreSQL is required for this test run. Start it with "
                "'docker compose up -d postgres' or set TEST_DATABASE_URL to a reachable database.",
                file=sys.stderr,
            )
            raise SystemExit(1)

            _run_or_exit(*pytest_command)


def validate_main() -> None:
    fast_checks_main()
    tests_main()
