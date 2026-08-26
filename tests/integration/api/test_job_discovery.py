from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from ai_job_finder.api.dependencies import (
    greenhouse_board_validator_dependency,
    job_discovery_provider_dependency,
    job_source_connector_dependency,
    public_page_fetcher_dependency,
)
from ai_job_finder.application.job_discovery.query_generation import generate_job_discovery_queries
from ai_job_finder.application.job_searches import get_job_search_definition
from ai_job_finder.domain.enums import JobSourceProvider, WorkplaceType
from ai_job_finder.domain.job_discovery import DiscoveredJobCandidate
from ai_job_finder.domain.job_sources import NormalizedJobPosting
from ai_job_finder.domain.source_detection import PublicPage
from ai_job_finder.infrastructure.job_discovery.fake import FakeJobDiscoveryProvider
from ai_job_finder.infrastructure.job_sources.fake import FakeJobSourceConnector


class FakeFetcher:
    def __init__(self, pages: dict[str, PublicPage]) -> None:
        self.pages = pages

    def fetch(self, url: str) -> PublicPage:
        return self.pages[url]


def _create_candidate(client: TestClient) -> None:
    response = client.post(
        "/api/v1/candidate-profile",
        json={
            "full_name": "Jordan Lee",
            "preferred_locations": ["Remote"],
            "acceptable_remote_geographies": ["United States"],
            "remote_preference": "flexible",
            "target_levels": ["director"],
            "target_functions": ["platform engineering"],
        },
    )
    assert response.status_code == 201
    fact = client.post(
        "/api/v1/career-facts",
        json={
            "category": "platform",
            "source_organization": "Example Cloud",
            "statement": "Built a developer platform.",
            "metric": "40% faster delivery",
            "technologies": ["Python", "Kubernetes"],
            "leadership_scope": "30 engineers",
            "business_outcome": "Faster delivery",
            "approved_wording": "Built a developer platform with measurable impact.",
            "evidence_tags": ["platform_engineering", "developer_experience", "cloud"],
            "provenance_type": "project_notes",
            "source_reference": "packet",
        },
    )
    assert fact.status_code == 201
    verify = client.post(
        f"/api/v1/career-facts/{fact.json()['id']}/transitions",
        json={"lifecycle_status": "verified"},
    )
    assert verify.status_code == 200


def _posting(external_id: str, title: str) -> NormalizedJobPosting:
    return NormalizedJobPosting(
        provider=JobSourceProvider.GREENHOUSE,
        company_name="Acme",
        title=title,
        location_text="Remote United States",
        workplace_type=WorkplaceType.REMOTE,
        description_raw="Lead platform engineering with Kubernetes and cloud reliability.",
        description_normalized="Lead platform engineering with Kubernetes and cloud reliability.",
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


def _page(url: str) -> PublicPage:
    return PublicPage(
        requested_url=url,
        final_url=url,
        content_type="text/html",
        text="https://boards-api.greenhouse.io/v1/boards/acme/jobs",
    )


def test_job_discovery_api_run_list_detail_and_observations(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    _create_candidate(client)

    source_response = client.post(
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
    assert source_response.status_code == 201

    search_response = client.post(
        "/api/v1/job-searches",
        json={
            "name": "Platform roles",
            "enabled": True,
            "title_include_patterns": ["Director Platform Engineering"],
            "title_exclude_patterns": ["finance"],
            "target_domains": ["platform_engineering"],
            "target_seniority_levels": ["director"],
            "allowed_locations": [],
            "allowed_remote_geographies": ["United States"],
            "allowed_workplace_types": ["remote"],
            "minimum_score_threshold": 70,
        },
    )
    assert search_response.status_code == 201
    search_id = search_response.json()["id"]

    with session_factory() as session:
        search = get_job_search_definition(session, UUID(search_id))
        queries = generate_job_discovery_queries(
            search.to_snapshot(), max_queries=6, result_limit=5
        )

    url_one = "https://boards.greenhouse.io/acme/jobs/strong"
    url_two = "https://boards.greenhouse.io/acme/jobs/weak"
    provider = FakeJobDiscoveryProvider(
        results_by_query={
            queries[0].rendered_query: [
                DiscoveredJobCandidate(
                    discovered_url=url_one,
                    provider_name="fake",
                    query_identifier=queries[0].stable_query_id,
                    rank=1,
                    title_hint="Director, Platform Engineering",
                    company_hint="Acme",
                ),
                DiscoveredJobCandidate(
                    discovered_url=url_two,
                    provider_name="fake",
                    query_identifier=queries[0].stable_query_id,
                    rank=2,
                    title_hint="Finance Operations Manager",
                    company_hint="Acme",
                ),
            ]
        }
    )
    connector = FakeJobSourceConnector(
        jobs=[
            _posting("strong", "Director, Platform Engineering"),
            _posting("weak", "Finance Operations Manager"),
        ],
        valid_tokens={"acme"},
    )

    app = cast(Any, client.app)
    app.dependency_overrides[job_discovery_provider_dependency] = lambda: provider
    app.dependency_overrides[job_source_connector_dependency] = lambda: connector
    app.dependency_overrides[greenhouse_board_validator_dependency] = lambda: connector
    app.dependency_overrides[public_page_fetcher_dependency] = lambda: FakeFetcher(
        {url_one: _page(url_one), url_two: _page(url_two)}
    )

    run_response = client.post(f"/api/v1/job-searches/{search_id}/discovery-runs")
    assert run_response.status_code == 201
    assert run_response.json()["status"] == "completed"
    run_id = run_response.json()["id"]

    list_response = client.get(f"/api/v1/job-searches/{search_id}/discovery-runs")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    detail_response = client.get(f"/api/v1/job-discovery-runs/{run_id}")
    assert detail_response.status_code == 200
    assert len(detail_response.json()["queries"]) >= 1

    observations_response = client.get(f"/api/v1/job-discovery-runs/{run_id}/observations")
    assert observations_response.status_code == 200
    observations = observations_response.json()
    assert len(observations) == 2
    assert sum(1 for item in observations if item["matched"]) == 1
    assert {item["processing_status"] for item in observations} == {"imported"}

    openapi_response = client.get("/openapi.json")
    assert openapi_response.status_code == 200
    assert (
        "/api/v1/job-searches/{search_definition_id}/discovery-runs"
        in openapi_response.json()["paths"]
    )
    assert "/api/v1/job-discovery-runs/{run_id}" in openapi_response.json()["paths"]

    app.dependency_overrides.pop(job_discovery_provider_dependency, None)
    app.dependency_overrides.pop(job_source_connector_dependency, None)
    app.dependency_overrides.pop(greenhouse_board_validator_dependency, None)
    app.dependency_overrides.pop(public_page_fetcher_dependency, None)
