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


def test_candidate_update_and_single_candidate_invariant(client: TestClient) -> None:
    _create_candidate(client)

    update_response = client.put(
        "/api/v1/candidate-profile",
        json={
            "full_name": "Jordan Lee",
            "preferred_locations": ["Seattle", "New York"],
            "remote_preference": "hybrid",
            "target_levels": ["director", "senior director"],
            "target_functions": ["platform engineering", "infrastructure"],
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["remote_preference"] == "hybrid"

    duplicate_response = client.post(
        "/api/v1/candidate-profile",
        json={
            "full_name": "Taylor Smith",
            "preferred_locations": ["Boston"],
            "remote_preference": "remote_only",
            "target_levels": ["director"],
            "target_functions": ["ai platform"],
        },
    )
    assert duplicate_response.status_code == 409
    assert duplicate_response.json()["error"]["code"] == "single_candidate_violation"
