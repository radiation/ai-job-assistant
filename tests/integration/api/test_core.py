from __future__ import annotations

from typing import Any, cast

from fastapi.testclient import TestClient

from ai_job_finder.domain.enums import JobSourceProvider, WorkplaceType
from ai_job_finder.domain.job_sources import NormalizedJobPosting


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
) -> NormalizedJobPosting:
    return NormalizedJobPosting(
        provider=JobSourceProvider.GREENHOUSE,
        company_name="Acme",
        title=title,
        location_text="Remote",
        workplace_type=WorkplaceType.REMOTE,
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


def test_entity_creation_and_retrieval_flow(client: TestClient) -> None:
    candidate = _create_candidate(client)
    fact = _create_fact(client)
    verified_fact = _verify_fact(client, fact["id"])
    assert verified_fact["lifecycle_status"] == "verified"

    job_id = _create_job(client)
    evaluation_response = client.post(
        f"/api/v1/job-leads/{job_id}/evaluations",
        json={"candidate_profile_id": candidate["id"]},
    )

    assert evaluation_response.status_code == 201
    assert evaluation_response.json()["scoring_version"] == "candidate_evidence_v2"
    assert "Matched verified evidence:" in evaluation_response.json()["explanation"]

    latest_response = client.get(f"/api/v1/job-leads/{job_id}/evaluations/latest")
    assert latest_response.status_code == 200
    assert latest_response.json()["job_lead_id"] == job_id

    history_response = client.get(f"/api/v1/job-leads/{job_id}/evaluations")
    assert history_response.status_code == 200
    assert [evaluation["id"] for evaluation in history_response.json()] == [
        evaluation_response.json()["id"]
    ]


def test_api_validation_and_error_shapes(client: TestClient) -> None:
    invalid_response = client.post(
        "/api/v1/candidate-profile",
        json={
            "full_name": "",
            "preferred_locations": [],
            "remote_preference": "remote_only",
            "target_levels": [],
            "target_functions": [],
        },
    )
    assert invalid_response.status_code == 422
    assert invalid_response.json()["error"]["code"] == "validation_error"

    missing_candidate = client.get("/api/v1/candidate-profile")
    assert missing_candidate.status_code == 404
    assert missing_candidate.json()["error"]["code"] == "not_found"

    _create_candidate(client)
    invalid_fact = client.post(
        "/api/v1/career-facts",
        json={
            "category": "platform",
            "source_organization": "Example",
            "statement": "Built platform",
            "metric": None,
            "technologies": ["Python"],
            "leadership_scope": None,
            "business_outcome": None,
            "approved_wording": "Built platform",
            "evidence_tags": ["not_a_tag"],
            "provenance_type": "project_notes",
            "source_reference": "doc",
        },
    )
    assert invalid_fact.status_code == 422
    assert invalid_fact.json()["error"]["code"] == "validation_error"
