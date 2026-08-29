from __future__ import annotations

from fastapi.testclient import TestClient


def test_saved_search_api_validation_errors_remain_structured(client: TestClient) -> None:
    response = client.post(
        "/api/v1/job-searches",
        json={
            "name": "Platform roles",
            "enabled": True,
            "title_include_patterns": [],
            "title_exclude_patterns": [],
            "target_domains": ["foo"],
            "target_seniority_levels": ["nope"],
            "allowed_locations": [],
            "allowed_remote_geographies": [],
            "allowed_workplace_types": ["bar"],
            "minimum_score_threshold": 101,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["message"] == "Request validation failed."

    details = response.json()["error"]["details"]
    assert any(item["loc"] == ["body", "target_domains", 0] for item in details)
    assert any(item["loc"] == ["body", "target_seniority_levels", 0] for item in details)
    assert any(item["loc"] == ["body", "allowed_workplace_types", 0] for item in details)
    assert any(item["loc"] == ["body", "minimum_score_threshold"] for item in details)


def test_saved_search_api_configures_daily_discovery_schedule(client: TestClient) -> None:
    create_response = client.post(
        "/api/v1/job-searches",
        json={
            "name": "Platform roles",
            "enabled": True,
            "title_include_patterns": ["platform engineering"],
            "title_exclude_patterns": [],
            "target_domains": ["platform_engineering"],
            "target_seniority_levels": ["director"],
            "allowed_locations": [],
            "allowed_remote_geographies": ["United States"],
            "allowed_workplace_types": ["remote"],
            "minimum_score_threshold": 70,
        },
    )
    assert create_response.status_code == 201

    schedule_response = client.put(
        f"/api/v1/job-searches/{create_response.json()['id']}/discovery-schedule",
        json={"enabled": True, "cadence": "daily"},
    )

    assert schedule_response.status_code == 200
    assert schedule_response.json()["scheduled_discovery_enabled"] is True
    assert schedule_response.json()["scheduled_discovery_cadence"] == "daily"
    assert schedule_response.json()["next_scheduled_discovery_at"] is not None
