from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ai_job_finder.api.dependencies import (
    greenhouse_board_validator_dependency,
    job_discovery_provider_dependency,
    job_source_connector_dependency,
    public_page_fetcher_dependency,
)
from ai_job_finder.application.job_discovery.query_generation import generate_job_discovery_queries
from ai_job_finder.application.job_searches import get_job_search_definition
from ai_job_finder.application.services import (
    create_candidate_profile,
    create_career_fact,
    transition_career_fact,
)
from ai_job_finder.domain.enums import (
    CareerFactCategory,
    CareerFactLifecycle,
    EvidenceTag,
    JobSourceProvider,
    ProvenanceType,
    RemotePreference,
    WorkplaceType,
)
from ai_job_finder.domain.job_discovery import DiscoveredJobCandidate
from ai_job_finder.domain.job_sources import NormalizedJobPosting
from ai_job_finder.domain.source_detection import PublicPage
from ai_job_finder.infrastructure.database.models import JobLeadModel, JobSourceConfigurationModel
from ai_job_finder.infrastructure.job_discovery.fake import FakeJobDiscoveryProvider
from ai_job_finder.infrastructure.job_sources.fake import FakeJobSourceConnector


class FakeFetcher:
    def __init__(self, pages: dict[str, PublicPage]) -> None:
        self.pages = pages

    def fetch(self, url: str) -> PublicPage:
        return self.pages[url]


class CountingFetcher(FakeFetcher):
    def __init__(self, pages: dict[str, PublicPage]) -> None:
        super().__init__(pages)
        self.calls: list[str] = []

    def fetch(self, url: str) -> PublicPage:
        self.calls.append(url)
        return super().fetch(url)


def _seed_candidate(session: Session) -> None:
    candidate = create_candidate_profile(
        session,
        full_name="Jordan Lee",
        preferred_locations=["Remote"],
        acceptable_remote_geographies=["United States"],
        remote_preference=RemotePreference.FLEXIBLE.value,
        target_levels=["director"],
        target_functions=["platform engineering"],
    )
    fact = create_career_fact(
        session,
        candidate_profile_id=candidate.id,
        category=CareerFactCategory.PLATFORM.value,
        source_organization="Example Cloud",
        statement="Built a developer platform.",
        metric="40% faster delivery",
        technologies=["Python", "Kubernetes"],
        leadership_scope="30 engineers",
        business_outcome="Faster delivery",
        approved_wording="Built a developer platform with measurable impact.",
        evidence_tags=[
            EvidenceTag.PLATFORM_ENGINEERING.value,
            EvidenceTag.DEVELOPER_EXPERIENCE.value,
            EvidenceTag.CLOUD.value,
        ],
        provenance_type=ProvenanceType.PROJECT_NOTES.value,
        source_reference="packet",
    )
    transition_career_fact(
        session,
        fact_id=fact.id,
        lifecycle_status=CareerFactLifecycle.VERIFIED.value,
    )


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


def _posting_for_board(
    board_token: str,
    company_name: str,
    external_id: str,
    title: str,
) -> NormalizedJobPosting:
    return NormalizedJobPosting(
        provider=JobSourceProvider.GREENHOUSE,
        company_name=company_name,
        title=title,
        location_text="Remote United States",
        workplace_type=WorkplaceType.REMOTE,
        description_raw="Lead platform engineering with Kubernetes and cloud reliability.",
        description_normalized="Lead platform engineering with Kubernetes and cloud reliability.",
        compensation_text="$200k",
        source_url=f"https://boards.greenhouse.io/{board_token}/jobs/{external_id}",
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


def _page_for_token(url: str, token: str) -> PublicPage:
    return PublicPage(
        requested_url=url,
        final_url=url,
        content_type="text/html",
        text=f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
    )


def test_job_discovery_web_run_history_and_detail(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)

    source_create = client.post(
        "/job-sources",
        data={
            "display_name": "Acme Greenhouse",
            "company_name": "Acme",
            "board_token": "acme",
            "source_url": "https://boards.greenhouse.io/acme",
        },
        follow_redirects=False,
    )
    assert source_create.status_code == 303

    search_create = client.post(
        "/job-searches",
        data={
            "name": "Platform roles",
            "title_include_patterns": "Director Platform Engineering",
            "title_exclude_patterns": "finance",
            "target_domains": "platform_engineering",
            "target_seniority_levels": "director",
            "allowed_locations": "",
            "allowed_remote_geographies": "United States",
            "allowed_workplace_types": "remote",
            "minimum_score_threshold": "70",
        },
        follow_redirects=False,
    )
    assert search_create.status_code == 303
    search_id = search_create.headers["location"].split("/job-searches/")[1]

    with session_factory() as session:
        search = get_job_search_definition(session, UUID(search_id))
        queries = generate_job_discovery_queries(
            search.to_snapshot(), max_queries=6, result_limit=5
        )

    url_one = "https://boards.greenhouse.io/acme/jobs/strong"
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
                )
            ]
        }
    )
    connector = FakeJobSourceConnector(
        jobs=[_posting("strong", "Director, Platform Engineering")],
        valid_tokens={"acme"},
    )
    app = cast(Any, client.app)
    app.dependency_overrides[job_discovery_provider_dependency] = lambda: provider
    app.dependency_overrides[job_source_connector_dependency] = lambda: connector
    app.dependency_overrides[greenhouse_board_validator_dependency] = lambda: connector
    app.dependency_overrides[public_page_fetcher_dependency] = lambda: FakeFetcher(
        {url_one: _page(url_one)}
    )

    run_response = client.post(
        f"/job-searches/{search_id}/discovery-runs",
        follow_redirects=False,
    )
    assert run_response.status_code == 303

    detail_response = client.get(run_response.headers["location"])
    assert detail_response.status_code == 200
    assert "Manual discovery run details." in detail_response.text
    assert "Search phase" in detail_response.text
    assert "Discovery phase" in detail_response.text
    assert "Import phase" in detail_response.text
    assert "Top matched jobs" in detail_response.text
    assert "Surfaced in /discover" in detail_response.text
    assert "Director, Platform Engineering" in detail_response.text
    assert "Matched" in detail_response.text

    search_detail = client.get(f"/job-searches/{search_id}")
    assert search_detail.status_code == 200
    assert "Discovery history" in search_detail.text
    assert "Run discovery" in search_detail.text

    app.dependency_overrides.pop(job_discovery_provider_dependency, None)
    app.dependency_overrides.pop(job_source_connector_dependency, None)
    app.dependency_overrides.pop(greenhouse_board_validator_dependency, None)
    app.dependency_overrides.pop(public_page_fetcher_dependency, None)


def test_job_discovery_web_auto_creates_unknown_greenhouse_source(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)

    search_create = client.post(
        "/job-searches",
        data={
            "name": "Platform roles auto source",
            "title_include_patterns": "Director Platform Engineering",
            "title_exclude_patterns": "finance",
            "target_domains": "platform_engineering",
            "target_seniority_levels": "director",
            "allowed_locations": "",
            "allowed_remote_geographies": "United States",
            "allowed_workplace_types": "remote",
            "minimum_score_threshold": "70",
        },
        follow_redirects=False,
    )
    assert search_create.status_code == 303
    search_id = search_create.headers["location"].split("/job-searches/")[1]

    with session_factory() as session:
        search = get_job_search_definition(session, UUID(search_id))
        queries = generate_job_discovery_queries(
            search.to_snapshot(), max_queries=6, result_limit=5
        )

    strong_url = "https://boards.greenhouse.io/beta/jobs/strong"
    weak_url = "https://boards.greenhouse.io/beta/jobs/weak"
    provider = FakeJobDiscoveryProvider(
        results_by_query={
            queries[0].rendered_query: [
                DiscoveredJobCandidate(
                    discovered_url=strong_url,
                    provider_name="fake",
                    query_identifier=queries[0].stable_query_id,
                    rank=1,
                    title_hint="Director, Platform Engineering",
                    company_hint="Beta",
                ),
                DiscoveredJobCandidate(
                    discovered_url=weak_url,
                    provider_name="fake",
                    query_identifier=queries[0].stable_query_id,
                    rank=2,
                    title_hint="Finance Operations Manager",
                    company_hint="Beta",
                ),
            ]
        }
    )
    connector = FakeJobSourceConnector(
        jobs=[
            _posting_for_board("beta", "Beta", "strong", "Director, Platform Engineering"),
            _posting_for_board("beta", "Beta", "weak", "Finance Operations Manager"),
        ],
        valid_tokens={"beta"},
    )
    app = cast(Any, client.app)
    app.dependency_overrides[job_discovery_provider_dependency] = lambda: provider
    app.dependency_overrides[job_source_connector_dependency] = lambda: connector
    app.dependency_overrides[greenhouse_board_validator_dependency] = lambda: connector
    app.dependency_overrides[public_page_fetcher_dependency] = lambda: FakeFetcher(
        {
            strong_url: _page_for_token(strong_url, "beta"),
            weak_url: _page_for_token(weak_url, "beta"),
        }
    )

    run_response = client.post(
        f"/job-searches/{search_id}/discovery-runs",
        follow_redirects=False,
    )
    assert run_response.status_code == 303

    detail_response = client.get(run_response.headers["location"])
    assert detail_response.status_code == 200
    assert "Director, Platform Engineering" in detail_response.text
    assert "Finance Operations Manager" in detail_response.text
    assert "Imported" in detail_response.text

    discover_response = client.get("/discover")
    assert discover_response.status_code == 200
    assert "Director, Platform Engineering" in discover_response.text

    with session_factory() as session:
        assert len(list(session.scalars(select(JobSourceConfigurationModel)))) == 1
        assert len(list(session.scalars(select(JobLeadModel)))) == 2

    app.dependency_overrides.pop(job_discovery_provider_dependency, None)
    app.dependency_overrides.pop(job_source_connector_dependency, None)
    app.dependency_overrides.pop(greenhouse_board_validator_dependency, None)
    app.dependency_overrides.pop(public_page_fetcher_dependency, None)


def test_job_discovery_web_shows_aggregator_exclusion_reason(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)

    search_create = client.post(
        "/job-searches",
        data={
            "name": "Platform roles aggregators",
            "title_include_patterns": "Director Platform Engineering",
            "title_exclude_patterns": "finance",
            "target_domains": "platform_engineering",
            "target_seniority_levels": "director",
            "allowed_locations": "",
            "allowed_remote_geographies": "United States",
            "allowed_workplace_types": "remote",
            "minimum_score_threshold": "70",
        },
        follow_redirects=False,
    )
    assert search_create.status_code == 303
    search_id = search_create.headers["location"].split("/job-searches/")[1]

    with session_factory() as session:
        search = get_job_search_definition(session, UUID(search_id))
        queries = generate_job_discovery_queries(
            search.to_snapshot(), max_queries=6, result_limit=5
        )

    aggregator_url = "https://www.indeed.com/viewjob?jk=123"
    provider = FakeJobDiscoveryProvider(
        results_by_query={
            queries[0].rendered_query: [
                DiscoveredJobCandidate(
                    discovered_url=aggregator_url,
                    provider_name="fake",
                    query_identifier=queries[0].stable_query_id,
                    rank=1,
                    title_hint="Director, Platform Engineering",
                )
            ]
        }
    )
    fetcher = CountingFetcher({})
    app = cast(Any, client.app)
    app.dependency_overrides[job_discovery_provider_dependency] = lambda: provider
    app.dependency_overrides[job_source_connector_dependency] = lambda: FakeJobSourceConnector()
    app.dependency_overrides[greenhouse_board_validator_dependency] = lambda: (
        FakeJobSourceConnector()
    )
    app.dependency_overrides[public_page_fetcher_dependency] = lambda: fetcher

    run_response = client.post(
        f"/job-searches/{search_id}/discovery-runs",
        follow_redirects=False,
    )
    assert run_response.status_code == 303

    detail_response = client.get(run_response.headers["location"])
    assert detail_response.status_code == 200
    assert "unsupported" in detail_response.text.casefold()
    assert "indeed.com" in detail_response.text
    assert fetcher.calls == []

    app.dependency_overrides.pop(job_discovery_provider_dependency, None)
    app.dependency_overrides.pop(job_source_connector_dependency, None)
    app.dependency_overrides.pop(greenhouse_board_validator_dependency, None)
    app.dependency_overrides.pop(public_page_fetcher_dependency, None)
