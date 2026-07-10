from __future__ import annotations

from fastapi.testclient import TestClient


def test_entity_creation_and_retrieval_flow(client: TestClient) -> None:
    candidate_response = client.post(
        "/api/v1/candidate-profiles",
        json={
            "full_name": "Jordan Lee",
            "preferred_locations": ["Seattle"],
            "remote_preference": "flexible",
            "target_levels": ["director"],
            "target_functions": ["platform engineering"],
        },
    )
    assert candidate_response.status_code == 201
    candidate_id = candidate_response.json()["id"]

    fact_response = client.post(
        f"/api/v1/candidate-profiles/{candidate_id}/career-facts",
        json={
            "category": "platform",
            "source_organization": "Example",
            "statement": "Built platform",
            "metric": "40% faster",
            "technologies": ["Python", "Kubernetes"],
            "leadership_scope": "30 engineers",
            "business_outcome": "Faster delivery",
            "approved_wording": "Built platform with measurable impact",
            "verification_status": "verified",
            "source_reference": "scorecard",
        },
    )
    assert fact_response.status_code == 201

    job_response = client.post(
        "/api/v1/job-leads",
        json={
            "source": "manual",
            "source_url": "https://example.com/job/1",
            "external_id": "job-1",
            "company_name": "Northstar",
            "title": "Director, Platform Engineering",
            "location_text": "Seattle, WA",
            "workplace_type": "hybrid",
            "description_raw": "Own platform strategy and roadmap.",
            "description_normalized": (
                "Own platform strategy and roadmap, lead teams, and build a self-service "
                "developer platform."
            ),
            "compensation_text": "$250k",
        },
    )
    assert job_response.status_code == 201
    job_id = job_response.json()["id"]

    evaluation_response = client.post(
        f"/api/v1/job-leads/{job_id}/evaluations",
        json={"candidate_profile_id": candidate_id},
    )
    assert evaluation_response.status_code == 201
    assert evaluation_response.json()["recommendation"] in {
        "strong_recommend",
        "recommend",
        "hold",
        "decline",
    }

    latest_response = client.get(f"/api/v1/job-leads/{job_id}/evaluations/latest")
    assert latest_response.status_code == 200
    assert latest_response.json()["job_lead_id"] == job_id


def test_api_validation_and_error_shapes(client: TestClient) -> None:
    invalid_response = client.post(
        "/api/v1/candidate-profiles",
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

    missing_response = client.get("/api/v1/job-leads/00000000-0000-0000-0000-000000000000")
    assert missing_response.status_code == 404
    assert missing_response.json()["error"]["code"] == "not_found"


def test_evaluation_requires_verified_fact(client: TestClient) -> None:
    candidate_response = client.post(
        "/api/v1/candidate-profiles",
        json={
            "full_name": "Jordan Lee",
            "preferred_locations": ["Seattle"],
            "remote_preference": "flexible",
            "target_levels": ["director"],
            "target_functions": ["platform engineering"],
        },
    )
    candidate_id = candidate_response.json()["id"]

    client.post(
        f"/api/v1/candidate-profiles/{candidate_id}/career-facts",
        json={
            "category": "platform",
            "source_organization": "Example",
            "statement": "Built platform",
            "metric": None,
            "technologies": ["Python"],
            "leadership_scope": None,
            "business_outcome": None,
            "approved_wording": "Built platform",
            "verification_status": "pending",
            "source_reference": "doc",
        },
    )

    job_response = client.post(
        "/api/v1/job-leads",
        json={
            "source": "manual",
            "source_url": None,
            "external_id": "job-2",
            "company_name": "Northstar",
            "title": "Director, Platform Engineering",
            "location_text": "Seattle, WA",
            "workplace_type": "hybrid",
            "description_raw": "Own platform strategy.",
            "description_normalized": "Own platform strategy and roadmap.",
            "compensation_text": None,
        },
    )
    job_id = job_response.json()["id"]

    evaluation_response = client.post(
        f"/api/v1/job-leads/{job_id}/evaluations",
        json={"candidate_profile_id": candidate_id},
    )
    assert evaluation_response.status_code == 409
    assert evaluation_response.json()["error"]["code"] == "evaluation_precondition_failed"
