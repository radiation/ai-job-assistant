from __future__ import annotations

from html import unescape
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from ai_job_finder.application.job_searches import get_job_search_definition


def _saved_search_form_data(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "name": "Platform roles",
        "title_include_patterns": "platform engineering",
        "title_exclude_patterns": "finance",
        "target_domains": ["platform_engineering"],
        "target_seniority_levels": ["director"],
        "allowed_locations": "",
        "allowed_remote_geographies": "United States",
        "allowed_workplace_types": ["remote"],
        "minimum_score_threshold": "70",
    }
    values.update(overrides)
    return values


def _checked_input(name: str, value: str) -> str:
    return f'name="{name}" value="{value}" checked'


def test_saved_search_create_form_renders_canonical_options(client: TestClient) -> None:
    response = client.get("/job-searches/new")

    html = unescape(response.text)

    assert response.status_code == 200
    assert 'name="target_domains" value="platform_engineering"' in html
    assert 'name="target_domains" value="developer_experience"' in html
    assert "Platform Engineering" in html
    assert "Developer Experience" in html
    assert 'name="target_seniority_levels" value="director"' in html
    assert 'name="target_seniority_levels" value="senior_director"' in html
    assert "Director" in html
    assert "Senior Director" in html
    assert 'name="allowed_workplace_types" value="remote"' in html
    assert 'name="allowed_workplace_types" value="hybrid"' in html
    assert 'name="allowed_workplace_types" value="onsite"' in html
    assert "Remote" in html
    assert "Hybrid" in html
    assert "Onsite" in html


def test_invalid_saved_search_submission_renders_actionable_errors_and_preserves_values(
    client: TestClient,
) -> None:
    response = client.post(
        "/job-searches",
        data=_saved_search_form_data(
            title_include_patterns="platform engineering\nexecutive platform",
            target_domains=["foo"],
            target_seniority_levels=["nope"],
            allowed_locations="Seattle, WA\nNew York, NY",
            allowed_workplace_types=["bar"],
            minimum_score_threshold="101",
        ),
    )

    html = unescape(response.text)

    assert response.status_code == 422
    assert "New Saved Search" in html
    assert "Review the highlighted fields." in html
    assert 'Target domain "foo" is not valid.' in html
    assert 'Target seniority level "nope" is not valid.' in html
    assert 'Allowed workplace type "bar" is not valid.' in html
    assert "Minimum score threshold must be between 0 and 100." in html
    assert 'value="Platform roles"' in html
    assert 'value="101"' in html
    assert "platform engineering\nexecutive platform" in html
    assert "Seattle, WA\nNew York, NY" in html
    assert '<form method="post" action="/job-searches" class="stacked-form">' in html


def test_valid_saved_search_accepts_blank_optional_multivalue_fields(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    response = client.post(
        "/job-searches",
        data=_saved_search_form_data(
            title_include_patterns="",
            title_exclude_patterns="",
            allowed_locations="",
            allowed_remote_geographies="",
            allowed_workplace_types="",
        ),
        follow_redirects=False,
    )

    assert response.status_code == 303

    search_id = UUID(response.headers["location"].split("/job-searches/")[1])
    with session_factory() as session:
        search = get_job_search_definition(session, search_id)

    assert search.title_include_patterns == []
    assert search.title_exclude_patterns == []
    assert search.allowed_locations == []
    assert search.allowed_remote_geographies == []
    assert search.allowed_workplace_types == []
    assert search.target_domains == ["platform_engineering"]
    assert search.target_seniority_levels == ["director"]
    assert search.minimum_score_threshold == 70.0


def test_saved_search_creation_with_rendered_canonical_values_succeeds(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    response = client.post(
        "/job-searches",
        data=_saved_search_form_data(
            target_domains=["platform_engineering"],
            target_seniority_levels=["director"],
            allowed_workplace_types=["remote", "hybrid"],
        ),
        follow_redirects=False,
    )

    assert response.status_code == 303

    search_id = UUID(response.headers["location"].split("/job-searches/")[1])
    with session_factory() as session:
        search = get_job_search_definition(session, search_id)

    assert search.target_domains == ["platform_engineering"]
    assert search.target_seniority_levels == ["director"]
    assert search.allowed_workplace_types == ["remote", "hybrid"]


def test_saved_search_edit_form_keeps_existing_canonical_options_selected(
    client: TestClient,
) -> None:
    create_response = client.post(
        "/job-searches",
        data=_saved_search_form_data(
            target_domains=["platform_engineering", "developer_experience"],
            target_seniority_levels=["director", "senior_director"],
            allowed_workplace_types=["remote", "hybrid"],
        ),
        follow_redirects=False,
    )
    assert create_response.status_code == 303

    detail_response = client.get(create_response.headers["location"])
    html = unescape(detail_response.text)

    assert detail_response.status_code == 200
    assert _checked_input("target_domains", "platform_engineering") in html
    assert _checked_input("target_domains", "developer_experience") in html
    assert _checked_input("target_seniority_levels", "director") in html
    assert _checked_input("target_seniority_levels", "senior_director") in html
    assert _checked_input("allowed_workplace_types", "remote") in html
    assert _checked_input("allowed_workplace_types", "hybrid") in html


def test_saved_search_validation_redisplay_keeps_selected_canonical_options(
    client: TestClient,
) -> None:
    response = client.post(
        "/job-searches",
        data=_saved_search_form_data(
            target_domains=["platform_engineering"],
            target_seniority_levels=["director"],
            allowed_workplace_types=["remote"],
            minimum_score_threshold="101",
        ),
    )

    html = unescape(response.text)

    assert response.status_code == 422
    assert "Minimum score threshold must be between 0 and 100." in html
    assert _checked_input("target_domains", "platform_engineering") in html
    assert _checked_input("target_seniority_levels", "director") in html
    assert _checked_input("allowed_workplace_types", "remote") in html
