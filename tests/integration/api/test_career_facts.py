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


def test_career_fact_list_filters_and_verified_edit_behavior(client: TestClient) -> None:
    _create_candidate(client)
    platform_fact = _create_fact(client)
    leadership_fact = _create_fact(
        client,
        category="leadership",
        source_organization="Northstar",
        statement="Directed platform managers globally",
        evidence_tags=["people_leadership", "manager_of_managers", "global_operations"],
    )

    archived_response = client.post(
        f"/api/v1/career-facts/{leadership_fact['id']}/transitions",
        json={"lifecycle_status": "archived"},
    )
    assert archived_response.status_code == 200

    default_list = client.get("/api/v1/career-facts")
    assert default_list.status_code == 200
    assert {fact["id"] for fact in default_list.json()} == {platform_fact["id"]}

    archived_list = client.get("/api/v1/career-facts?lifecycle_status=archived")
    assert archived_list.status_code == 200
    assert [fact["id"] for fact in archived_list.json()] == [leadership_fact["id"]]

    category_list = client.get("/api/v1/career-facts?category=platform")
    assert category_list.status_code == 200
    assert [fact["id"] for fact in category_list.json()] == [platform_fact["id"]]

    tag_list = client.get("/api/v1/career-facts?evidence_tag=platform_engineering")
    assert tag_list.status_code == 200
    assert [fact["id"] for fact in tag_list.json()] == [platform_fact["id"]]

    verified_fact = _verify_fact(client, platform_fact["id"])
    assert verified_fact["verified_at"] is not None

    update_response = client.put(
        f"/api/v1/career-facts/{platform_fact['id']}",
        json={
            "category": "platform",
            "source_organization": "Example",
            "statement": "Built platform and internal developer portal",
            "metric": "40% faster",
            "technologies": ["Python", "Kubernetes"],
            "leadership_scope": "30 engineers",
            "business_outcome": "Faster delivery",
            "approved_wording": (
                "Built platform and internal developer portal with measurable impact"
            ),
            "evidence_tags": ["platform_engineering", "developer_experience"],
            "provenance_type": "project_notes",
            "source_reference": "scorecard",
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["lifecycle_status"] == "draft"
    assert update_response.json()["verified_at"] is None


def test_invalid_lifecycle_transition_returns_conflict(client: TestClient) -> None:
    _create_candidate(client)
    fact = _create_fact(client)
    client.post(
        f"/api/v1/career-facts/{fact['id']}/transitions",
        json={"lifecycle_status": "archived"},
    )

    invalid_transition = client.post(
        f"/api/v1/career-facts/{fact['id']}/transitions",
        json={"lifecycle_status": "verified"},
    )
    assert invalid_transition.status_code == 409
    assert invalid_transition.json()["error"]["code"] == "invalid_career_fact_transition"
