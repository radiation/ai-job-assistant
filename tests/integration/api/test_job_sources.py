from __future__ import annotations

from typing import Any, cast

from fastapi.testclient import TestClient

from ai_job_finder.api.dependencies import job_source_connector_dependency
from ai_job_finder.domain.enums import JobSourceProvider, WorkplaceType
from ai_job_finder.domain.errors import InvalidJobSourceError, JobSourceProviderError
from ai_job_finder.domain.job_sources import JobSourceItemFailure, NormalizedJobPosting
from ai_job_finder.infrastructure.job_sources.fake import FakeJobSourceConnector


def _create_candidate(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/api/v1/candidate-profile",
        json={
            "full_name": "Jordan Lee",
            "preferred_locations": ["Seattle", "Remote"],
            "acceptable_remote_geographies": ["United States"],
            "remote_preference": "flexible",
            "target_levels": ["director"],
            "target_functions": ["platform engineering"],
        },
    )
    assert response.status_code == 201
    candidate = cast(dict[str, Any], response.json())
    assert candidate["acceptable_remote_geographies"] == ["United States"]
    return candidate


def _create_fact(
    client: TestClient,
    *,
    category: str = "platform",
    source_organization: str = "Example",
    statement: str = "Built platform",
    evidence_tags: list[str] | None = None,
    provenance_type: str = "project_notes",
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/career-facts",
        json={
            "category": category,
            "source_organization": source_organization,
            "statement": statement,
            "metric": "40% faster",
            "technologies": ["Python", "Kubernetes"],
            "leadership_scope": "30 engineers",
            "business_outcome": "Faster delivery",
            "approved_wording": "Built platform with measurable impact",
            "evidence_tags": evidence_tags or ["platform_engineering", "cloud"],
            "provenance_type": provenance_type,
            "source_reference": "scorecard",
        },
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def _verify_fact(client: TestClient, fact_id: str) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/career-facts/{fact_id}/transitions",
        json={"lifecycle_status": "verified"},
    )
    assert response.status_code == 200
    return cast(dict[str, Any], response.json())


def _create_job(client: TestClient, external_id: str = "job-1") -> str:
    response = client.post(
        "/api/v1/job-leads",
        json={
            "source": "manual",
            "source_url": "https://example.com/job/1",
            "external_id": external_id,
            "company_name": "Northstar",
            "title": "Director, Platform Engineering",
            "location_text": "Seattle, WA",
            "workplace_type": "hybrid",
            "description_raw": "Own platform strategy and roadmap.",
            "description_normalized": (
                "Own platform strategy and roadmap, lead teams, and build a self-service "
                "developer platform with Kubernetes, CI/CD, and reliability focus."
            ),
            "compensation_text": "$250k",
        },
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def _greenhouse_posting(
    external_id: str,
    *,
    title: str = "Director, Platform Engineering",
    description: str = "Lead platform engineering, Kubernetes, CI/CD, and cloud reliability.",
    location_text: str = "Remote",
    workplace_type: WorkplaceType = WorkplaceType.REMOTE,
) -> NormalizedJobPosting:
    return NormalizedJobPosting(
        provider=JobSourceProvider.GREENHOUSE,
        company_name="Acme",
        title=title,
        location_text=location_text,
        workplace_type=workplace_type,
        description_raw=description,
        description_normalized=description,
        compensation_text="$200k",
        source_url=f"https://boards.greenhouse.io/acme/jobs/{external_id}",
        external_id=external_id,
        internal_job_id=f"req-{external_id}",
        source_updated_at=None,
        departments=["Engineering"],
        offices=["Remote"],
        metadata={},
        raw_payload={"id": external_id},
    )


def test_job_source_crud_sync_and_ranked_discovery(client: TestClient) -> None:
    candidate = _create_candidate(client)
    _verify_fact(
        client,
        _create_fact(
            client,
            statement="Led platform engineering with Kubernetes and developer experience scope.",
            evidence_tags=["platform_engineering", "developer_experience", "cloud", "kubernetes"],
        )["id"],
    )
    assert candidate["id"]

    fake_connector = FakeJobSourceConnector(
        jobs=[
            _greenhouse_posting("strong"),
            _greenhouse_posting(
                "weak",
                title="Finance Operations Manager",
                description="Own finance operations reporting and vendor invoices.",
            ),
        ]
    )
    app = cast(Any, client.app)
    app.dependency_overrides[job_source_connector_dependency] = lambda: fake_connector

    create_response = client.post(
        "/api/v1/job-sources",
        json={
            "provider": "greenhouse",
            "display_name": "Acme Greenhouse",
            "company_name": "Acme",
            "board_token": "acme",
            "source_url": "https://boards.greenhouse.io/acme",
            "enabled": True,
        },
    )
    assert create_response.status_code == 201
    source_id = create_response.json()["id"]

    duplicate_response = client.post(
        "/api/v1/job-sources",
        json={
            "provider": "greenhouse",
            "display_name": "Acme Duplicate",
            "company_name": "Acme",
            "board_token": "acme",
            "source_url": None,
            "enabled": True,
        },
    )
    assert duplicate_response.status_code == 409
    assert duplicate_response.json()["error"]["code"] == "duplicate_job_source"

    disable_response = client.post(f"/api/v1/job-sources/{source_id}/disable")
    assert disable_response.status_code == 200
    assert disable_response.json()["enabled"] is False
    enable_response = client.post(f"/api/v1/job-sources/{source_id}/enable")
    assert enable_response.status_code == 200
    assert enable_response.json()["enabled"] is True

    first_import = client.post(f"/api/v1/job-sources/{source_id}/imports")
    assert first_import.status_code == 201
    assert first_import.json()["status"] == "succeeded"
    assert first_import.json()["jobs_created"] == 2
    assert first_import.json()["evaluations_created"] == 2

    second_import = client.post(f"/api/v1/job-sources/{source_id}/imports")
    assert second_import.status_code == 201
    assert second_import.json()["jobs_unchanged"] == 2
    assert second_import.json()["evaluations_created"] == 0

    queue_response = client.get("/api/v1/discovered-leads")
    assert queue_response.status_code == 200
    leads = queue_response.json()
    assert len(leads) == 2
    assert leads[0]["job"]["external_id"].endswith(":strong")
    assert leads[0]["location_eligibility"]["status"] == "needs_review"
    assert leads[0]["location_eligibility"]["reasons"] == ["remote_geography_unclear"]
    assert (
        leads[0]["latest_evaluation"]["overall_score"]
        >= leads[1]["latest_evaluation"]["overall_score"]
    )

    eligibility_response = client.get(
        "/api/v1/discovered-leads", params={"location_eligibility": "needs_review"}
    )
    assert eligibility_response.status_code == 200
    assert len(eligibility_response.json()) == 2

    filtered_response = client.get("/api/v1/discovered-leads", params={"recommendation": "decline"})
    assert filtered_response.status_code == 200

    invalid_connector = FakeJobSourceConnector(error=InvalidJobSourceError("invalid board"))
    app.dependency_overrides[job_source_connector_dependency] = lambda: invalid_connector
    failed_import = client.post(f"/api/v1/job-sources/{source_id}/imports")
    assert failed_import.status_code == 201
    assert failed_import.json()["status"] == "failed"
    assert "invalid board" in failed_import.json()["error_message"]

    runs_response = client.get("/api/v1/job-import-runs", params={"source_id": source_id})
    assert runs_response.status_code == 200
    assert len(runs_response.json()) == 3

    run_detail = client.get(f"/api/v1/job-import-runs/{first_import.json()['id']}")
    assert run_detail.status_code == 200
    assert run_detail.json()["jobs_created"] == 2

    status_response = client.patch(
        f"/api/v1/job-leads/{leads[0]['job']['id']}/status",
        json={"posting_status": "reviewing"},
    )
    assert status_response.status_code == 200
    assert status_response.json()["posting_status"] == "reviewing"

    app.dependency_overrides.pop(job_source_connector_dependency, None)


def test_job_source_import_api_partial_failed_and_disabled(client: TestClient) -> None:
    _create_candidate(client)
    app = cast(Any, client.app)

    source_response = client.post(
        "/api/v1/job-sources",
        json={
            "provider": "greenhouse",
            "display_name": "Acme Greenhouse",
            "company_name": "Acme",
            "board_token": "acme-partial",
            "source_url": "https://boards.greenhouse.io/acme",
            "enabled": True,
        },
    )
    assert source_response.status_code == 201
    source_id = source_response.json()["id"]

    app.dependency_overrides[job_source_connector_dependency] = lambda: FakeJobSourceConnector(
        jobs=[_greenhouse_posting("1"), _greenhouse_posting("2")]
    )
    baseline_import = client.post(f"/api/v1/job-sources/{source_id}/imports")
    assert baseline_import.status_code == 201
    assert baseline_import.json()["status"] == "succeeded"

    app.dependency_overrides[job_source_connector_dependency] = lambda: FakeJobSourceConnector(
        jobs=[_greenhouse_posting("1")],
        job_failures=[
            JobSourceItemFailure(
                external_id="broken",
                message="Greenhouse job payload is missing title.",
            )
        ],
    )
    partial_import = client.post(f"/api/v1/job-sources/{source_id}/imports")
    assert partial_import.status_code == 201
    assert partial_import.json()["status"] == "partial"
    assert partial_import.json()["jobs_failed"] == 1
    assert partial_import.json()["jobs_closed"] == 0
    assert "missing title" in partial_import.json()["error_message"]

    disabled_response = client.post(f"/api/v1/job-sources/{source_id}/disable")
    assert disabled_response.status_code == 200
    disabled_import = client.post(f"/api/v1/job-sources/{source_id}/imports")
    assert disabled_import.status_code == 409
    assert disabled_import.json()["error"]["code"] == "job_source_disabled"

    enabled_response = client.post(f"/api/v1/job-sources/{source_id}/enable")
    assert enabled_response.status_code == 200

    app.dependency_overrides[job_source_connector_dependency] = lambda: FakeJobSourceConnector(
        error=JobSourceProviderError("provider unavailable")
    )
    failed_import = client.post(f"/api/v1/job-sources/{source_id}/imports")
    assert failed_import.status_code == 201
    assert failed_import.json()["status"] == "failed"
    assert "provider unavailable" in failed_import.json()["error_message"]

    app.dependency_overrides.pop(job_source_connector_dependency, None)


def test_saved_search_api_crud_run_and_discovery_filter(client: TestClient) -> None:
    _create_candidate(client)
    _verify_fact(
        client,
        _create_fact(
            client,
            statement="Led platform engineering with Kubernetes and developer experience scope.",
            evidence_tags=["platform_engineering", "developer_experience", "cloud", "kubernetes"],
        )["id"],
    )

    fake_connector = FakeJobSourceConnector(
        jobs=[
            _greenhouse_posting("strong", location_text="Remote United States"),
            _greenhouse_posting(
                "weak",
                title="Finance Operations Manager",
                description="Own finance operations reporting and vendor invoices.",
                location_text="New York, NY",
                workplace_type=WorkplaceType.ONSITE,
            ),
        ]
    )
    app = cast(Any, client.app)
    app.dependency_overrides[job_source_connector_dependency] = lambda: fake_connector

    source_response = client.post(
        "/api/v1/job-sources",
        json={
            "provider": "greenhouse",
            "display_name": "Acme Greenhouse",
            "company_name": "Acme",
            "board_token": "acme-search",
            "source_url": "https://boards.greenhouse.io/acme",
            "enabled": True,
        },
    )
    assert source_response.status_code == 201
    source_id = source_response.json()["id"]

    import_response = client.post(f"/api/v1/job-sources/{source_id}/imports")
    assert import_response.status_code == 201

    create_response = client.post(
        "/api/v1/job-searches",
        json={
            "name": "Platform roles",
            "enabled": True,
            "title_include_patterns": ["platform engineering"],
            "title_exclude_patterns": ["finance"],
            "target_domains": ["platform_engineering"],
            "target_seniority_levels": ["director"],
            "allowed_locations": [],
            "allowed_remote_geographies": ["United States"],
            "allowed_workplace_types": ["remote"],
            "minimum_score_threshold": 70,
        },
    )
    assert create_response.status_code == 201
    search_id = create_response.json()["id"]

    list_response = client.get("/api/v1/job-searches")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    update_response = client.put(
        f"/api/v1/job-searches/{search_id}",
        json={
            "name": "Platform roles refined",
            "enabled": True,
            "title_include_patterns": ["platform engineering"],
            "title_exclude_patterns": ["finance"],
            "target_domains": ["platform_engineering"],
            "target_seniority_levels": ["director"],
            "allowed_locations": [],
            "allowed_remote_geographies": ["United States"],
            "allowed_workplace_types": ["remote"],
            "minimum_score_threshold": 72,
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Platform roles refined"

    disable_response = client.post(f"/api/v1/job-searches/{search_id}/disable")
    assert disable_response.status_code == 200
    assert disable_response.json()["enabled"] is False
    enable_response = client.post(f"/api/v1/job-searches/{search_id}/enable")
    assert enable_response.status_code == 200
    assert enable_response.json()["enabled"] is True

    run_response = client.post(f"/api/v1/job-searches/{search_id}/runs")
    assert run_response.status_code == 201
    assert run_response.json()["status"] == "completed"
    run_id = run_response.json()["id"]

    runs_response = client.get(
        "/api/v1/job-search-runs",
        params={"search_definition_id": search_id},
    )
    assert runs_response.status_code == 200
    assert len(runs_response.json()) == 1

    match_response = client.get(f"/api/v1/job-search-runs/{run_id}/matches")
    assert match_response.status_code == 200
    assert len(match_response.json()["matches"]) == 2
    assert sum(item["matched"] for item in match_response.json()["matches"]) == 1

    filtered_discovery = client.get(
        "/api/v1/discovered-leads",
        params={"search_definition_id": search_id},
    )
    assert filtered_discovery.status_code == 200
    leads = filtered_discovery.json()
    assert len(leads) == 1
    assert leads[0]["job"]["external_id"].endswith(":strong")

    disabled_run = client.post(f"/api/v1/job-searches/{search_id}/disable")
    assert disabled_run.status_code == 200
    disabled_run_attempt = client.post(f"/api/v1/job-searches/{search_id}/runs")
    assert disabled_run_attempt.status_code == 409
    assert disabled_run_attempt.json()["error"]["code"] == "job_search_definition_disabled"

    app.dependency_overrides.pop(job_source_connector_dependency, None)
