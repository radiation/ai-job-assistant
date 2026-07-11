from __future__ import annotations

from typing import Any, cast

from fastapi.testclient import TestClient


def _create_candidate(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/api/v1/candidate-profile",
        json={
            "full_name": "Jordan Lee",
            "preferred_locations": ["Seattle", "Remote"],
            "remote_preference": "flexible",
            "target_levels": ["director"],
            "target_functions": ["platform engineering"],
        },
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


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


def test_evaluation_allows_draft_only_facts_and_excludes_archived(client: TestClient) -> None:
    candidate = _create_candidate(client)
    draft_fact = _create_fact(client)

    job_id = _create_job(client, external_id="job-2")
    evaluation_response = client.post(
        f"/api/v1/job-leads/{job_id}/evaluations",
        json={"candidate_profile_id": candidate["id"]},
    )
    assert evaluation_response.status_code == 201
    assert (
        "No verified evidence matched the job signals." in evaluation_response.json()["explanation"]
    )
    assert "No verified career facts are available yet" in evaluation_response.json()["explanation"]

    archived_fact = _verify_fact(client, draft_fact["id"])
    assert archived_fact["lifecycle_status"] == "verified"
    archive_response = client.post(
        f"/api/v1/career-facts/{draft_fact['id']}/transitions",
        json={"lifecycle_status": "archived"},
    )
    assert archive_response.status_code == 200

    archived_only_response = client.post(
        f"/api/v1/job-leads/{job_id}/evaluations",
        json={"candidate_profile_id": candidate["id"]},
    )
    assert archived_only_response.status_code == 201
    assert (
        "No verified evidence matched the job signals."
        in archived_only_response.json()["explanation"]
    )


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


def test_job_lead_lookup_update_and_evaluation_history(client: TestClient) -> None:
    candidate = _create_candidate(client)
    fact = _verify_fact(client, _create_fact(client)["id"])
    assert fact["lifecycle_status"] == "verified"

    job_id = _create_job(client, external_id="bootstrap-strong-platform")

    lookup_response = client.get(
        "/api/v1/job-leads",
        params={"source": "manual", "external_id": "bootstrap-strong-platform"},
    )
    assert lookup_response.status_code == 200
    assert [job["id"] for job in lookup_response.json()] == [job_id]

    update_response = client.put(
        f"/api/v1/job-leads/{job_id}",
        json={
            "source_url": "https://example.com/job/1",
            "company_name": "Northstar",
            "title": "Senior Director, Platform Engineering",
            "location_text": "Seattle, WA",
            "workplace_type": "hybrid",
            "description_raw": "Lead platform engineering strategy.",
            "description_normalized": (
                "Lead platform engineering strategy, developer experience, and self-service "
                "infrastructure with Kubernetes, CI/CD, and observability."
            ),
            "compensation_text": "$260k",
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["title"] == "Senior Director, Platform Engineering"

    first_evaluation = client.post(
        f"/api/v1/job-leads/{job_id}/evaluations",
        json={"candidate_profile_id": candidate["id"]},
    )
    assert first_evaluation.status_code == 201

    second_evaluation = client.post(
        f"/api/v1/job-leads/{job_id}/evaluations",
        json={"candidate_profile_id": candidate["id"]},
    )
    assert second_evaluation.status_code == 201
    assert second_evaluation.json()["id"] != first_evaluation.json()["id"]

    history_response = client.get(f"/api/v1/job-leads/{job_id}/evaluations")
    assert history_response.status_code == 200
    assert len(history_response.json()) == 2
    assert history_response.json()[0]["id"] == second_evaluation.json()["id"]
    assert history_response.json()[1]["id"] == first_evaluation.json()["id"]
