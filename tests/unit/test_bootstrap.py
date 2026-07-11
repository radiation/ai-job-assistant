from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import httpx
from pytest import MonkeyPatch

from ai_job_finder.bootstrap import (
    BOOTSTRAP_SOURCE_PREFIX,
    ApiClient,
    BootstrapHarness,
    CandidateResponse,
    HarnessConfig,
    HarnessError,
    JobLeadResponse,
    JobLeadSource,
    WorkplaceType,
    format_failure,
    is_bootstrap_owned_candidate,
    is_bootstrap_owned_fact,
    is_localhost_url,
    main,
    parse_json_body,
)


def test_parse_json_body_handles_text_response() -> None:
    response = httpx.Response(500, text="boom")
    assert parse_json_body(response) == "boom"


def test_format_failure_includes_endpoint_and_expected_actual() -> None:
    error = HarnessError(
        "phase_1",
        "candidate create failed",
        endpoint="POST /api/v1/candidate-profile",
        expected=201,
        actual=409,
        response_body={"error": "conflict"},
    )
    text = format_failure(error)
    assert "endpoint=POST /api/v1/candidate-profile" in text
    assert "expected=201" in text
    assert "actual=409" in text


def test_localhost_safety_check() -> None:
    assert is_localhost_url("http://localhost:8000") is True
    assert is_localhost_url("http://127.0.0.1:8000") is True
    assert is_localhost_url("http://example.com") is False


def test_bootstrap_ownership_detection() -> None:
    candidate = CandidateResponse.model_validate(
        {
            "id": "candidate-1",
            "full_name": "Alex Mercer",
            "preferred_locations": ["Seattle"],
            "remote_preference": "flexible",
            "target_levels": ["director"],
            "target_functions": ["platform engineering"],
            "created_at": "2026-07-11T00:00:00Z",
            "updated_at": "2026-07-11T00:00:00Z",
        }
    )
    assert is_bootstrap_owned_candidate(candidate) is True

    fact: dict[str, Any] = {
        "id": "fact-1",
        "candidate_profile_id": "candidate-1",
        "category": "platform",
        "source_organization": "Northstar",
        "statement": "statement",
        "metric": None,
        "technologies": [],
        "leadership_scope": None,
        "business_outcome": None,
        "approved_wording": "approved",
        "lifecycle_status": "draft",
        "evidence_tags": [],
        "provenance_type": "project_notes",
        "source_reference": (
            f"{BOOTSTRAP_SOURCE_PREFIX}fact/platform?owner=bootstrap:candidate-kb-slice"
        ),
        "verified_at": None,
        "archived_at": None,
        "created_at": "2026-07-11T00:00:00Z",
        "updated_at": "2026-07-11T00:00:00Z",
    }
    assert is_bootstrap_owned_fact(type("Fact", (), fact)()) is True


def test_non_localhost_destructive_refused() -> None:
    config = HarnessConfig(
        base_url="http://example.com",
        timeout=1,
        readiness_timeout=1,
        reset=True,
        allow_destructive=True,
        allow_non_localhost_destructive=False,
        verbose=False,
        json_output=None,
    )
    harness = BootstrapHarness(ApiClient("http://localhost", 1), config)
    try:
        harness._enforce_safety()
    except HarnessError as error:
        assert "non-localhost" in error.assertion
    else:
        raise AssertionError("Expected destructive safety failure")
    finally:
        harness.client.close()


def test_main_returns_nonzero_on_failure(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    class StubHarness:
        def __init__(self, client: object, config: object) -> None:
            self.metadata = type(
                "Meta",
                (),
                {
                    "passed": 0,
                    "failed": 0,
                    "phases": [],
                    "base_url": "",
                    "reset_requested": False,
                    "created_ids": {},
                    "reused_ids": {},
                },
            )()

        def run(self) -> object:
            raise HarnessError(
                "phase_x",
                "forced failure",
                endpoint="GET /api/v1/health",
                expected=200,
                actual=500,
            )

        def _record_failure(self, error: HarnessError) -> None:
            self.metadata.failed += 1

    import ai_job_finder.bootstrap as bootstrap_module

    monkeypatch.setattr(bootstrap_module, "BootstrapHarness", StubHarness)
    exit_code = main(["--json-output", str(tmp_path / "result.json")])
    assert exit_code == 1


def test_idempotent_job_lookup_uses_external_id() -> None:
    captured: list[dict[str, object]] = []

    class StubClient:
        def list_jobs(self, **params: object) -> list[JobLeadResponse]:
            captured.append(params)
            return []

        def create_job(self, payload: object) -> JobLeadResponse:
            return JobLeadResponse.model_validate(
                {
                    "id": "job-1",
                    "source": JobLeadSource.MANUAL.value,
                    "source_url": "https://example.test/jobs/strong-platform",
                    "external_id": "bootstrap-strong-platform-devex",
                    "company_name": "Northstar",
                    "title": "Senior Director, Platform Engineering",
                    "location_text": "Seattle, WA",
                    "workplace_type": WorkplaceType.HYBRID.value,
                    "description_raw": "raw",
                    "description_normalized": "normalized",
                    "compensation_text": None,
                    "discovered_at": "2026-07-11T00:00:00Z",
                    "posting_status": "discovered",
                    "created_at": "2026-07-11T00:00:00Z",
                    "updated_at": "2026-07-11T00:00:00Z",
                }
            )

    harness = BootstrapHarness(
        cast(ApiClient, StubClient()),
        HarnessConfig(
            base_url="http://localhost:8000",
            timeout=1,
            readiness_timeout=1,
            reset=False,
            allow_destructive=False,
            allow_non_localhost_destructive=False,
            verbose=False,
            json_output=None,
        ),
    )
    job = harness._ensure_job("strong")
    assert job.external_id == "bootstrap-strong-platform-devex"
    assert captured == [{"source": "manual", "external_id": "bootstrap-strong-platform-devex"}]
