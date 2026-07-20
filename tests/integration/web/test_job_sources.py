from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from ai_job_finder.api.dependencies import job_source_connector_dependency
from ai_job_finder.application.job_sources import (
    create_job_source_configuration,
    run_job_source_import,
)
from ai_job_finder.application.services import (
    create_candidate_profile,
    create_career_fact,
    create_job_lead,
    transition_career_fact,
)
from ai_job_finder.domain.enums import (
    CareerFactCategory,
    CareerFactLifecycle,
    EvidenceTag,
    JobLeadSource,
    JobSourceProvider,
    ProvenanceType,
    RemotePreference,
    WorkplaceType,
)
from ai_job_finder.domain.job_sources import JobSourceItemFailure, NormalizedJobPosting
from ai_job_finder.infrastructure.database.models import JobLeadModel
from ai_job_finder.infrastructure.job_sources.fake import FakeJobSourceConnector


def _seed_candidate(
    session: Session,
    *,
    verified: bool = True,
    archived: bool = False,
) -> tuple[UUID, UUID]:
    candidate = create_candidate_profile(
        session,
        full_name="Jordan Lee",
        preferred_locations=["Seattle", "Remote"],
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
        statement="Built a platform adopted by engineering.",
        metric="40% faster delivery",
        technologies=["Python", "Kubernetes"],
        leadership_scope="30 engineers",
        business_outcome="Faster delivery",
        approved_wording="Built a platform adopted by engineering with measurable impact.",
        evidence_tags=[EvidenceTag.PLATFORM_ENGINEERING.value, EvidenceTag.CLOUD.value],
        provenance_type=ProvenanceType.PROJECT_NOTES.value,
        source_reference="review packet",
    )
    if verified:
        fact = transition_career_fact(
            session,
            fact_id=fact.id,
            lifecycle_status=CareerFactLifecycle.VERIFIED.value,
        )
    if archived:
        fact = transition_career_fact(
            session,
            fact_id=fact.id,
            lifecycle_status=CareerFactLifecycle.ARCHIVED.value,
        )
    return candidate.id, fact.id


def _seed_job(session: Session, *, external_id: str = "job-1") -> UUID:
    job = create_job_lead(
        session,
        source=JobLeadSource.MANUAL.value,
        source_url="https://example.com/jobs/1",
        external_id=external_id,
        company_name="Northstar",
        title="Director, Platform Engineering",
        location_text="Seattle, WA",
        workplace_type=WorkplaceType.HYBRID.value,
        description_raw="Own platform strategy and roadmap.",
        description_normalized=(
            "Own platform strategy and roadmap with Kubernetes, CI/CD, and reliability"
        ),
        compensation_text="$250k",
    )
    return job.id


def _greenhouse_posting(
    external_id: str,
    *,
    company_name: str = "Acme",
    title: str = "Director, Platform Engineering",
    location_text: str = "Remote",
    workplace_type: WorkplaceType = WorkplaceType.REMOTE,
    description: str = "Lead platform engineering with Kubernetes and cloud reliability.",
    raw_description: str | None = None,
) -> NormalizedJobPosting:
    return NormalizedJobPosting(
        provider=JobSourceProvider.GREENHOUSE,
        company_name=company_name,
        title=title,
        location_text=location_text,
        workplace_type=workplace_type,
        description_raw=raw_description or description,
        description_normalized=description,
        compensation_text="$200k",
        source_url=(
            f"https://boards.greenhouse.io/{company_name.casefold().replace(' ', '-')}/jobs/"
            f"{external_id}"
        ),
        external_id=external_id,
        internal_job_id=f"req-{external_id}",
        source_updated_at=None,
        raw_payload={"id": external_id},
    )


def test_job_sources_and_discover_pages(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as session:
        _seed_candidate(session)

    fake_connector = FakeJobSourceConnector(
        jobs=[
            _greenhouse_posting("review-1"),
            _greenhouse_posting(
                "eligible-1",
                company_name="Northstar",
                title=(
                    "Senior Director of Platform Engineering, Reliability, and Developer "
                    "Productivity"
                ),
                location_text=(
                    "Remote United States with quarterly travel to Seattle, WA and "
                    "Bay Area planning sessions"
                ),
                workplace_type=WorkplaceType.REMOTE,
                description=(
                    "Lead an internal platform portfolio across cloud infrastructure, CI/CD, "
                    "developer experience, and service reliability."
                ),
            ),
            _greenhouse_posting(
                "ineligible-1",
                company_name="East Coast Systems",
                title="VP, Infrastructure and Developer Experience",
                location_text="New York, NY metropolitan area with weekly onsite leadership",
                workplace_type=WorkplaceType.ONSITE,
                description=(
                    "Own infrastructure strategy and onsite leadership for platform and "
                    "workplace systems."
                ),
            ),
        ]
    )
    app = cast(Any, client.app)
    app.dependency_overrides[job_source_connector_dependency] = lambda: fake_connector

    new_page = client.get("/job-sources/new")
    assert new_page.status_code == 200
    assert "New Job Source" in new_page.text

    create_response = client.post(
        "/job-sources",
        data={
            "display_name": "Acme Greenhouse",
            "company_name": "Acme",
            "board_token": "acme",
            "source_url": "https://boards.greenhouse.io/acme",
        },
        follow_redirects=False,
    )
    assert create_response.status_code == 303

    detail_response = client.get(create_response.headers["location"])
    assert detail_response.status_code == 200
    assert "Sync now" in detail_response.text

    source_id = create_response.headers["location"].split("/job-sources/")[1].split("?")[0]
    sync_response = client.post(f"/job-sources/{source_id}/sync", follow_redirects=False)
    assert sync_response.status_code == 303
    assert sync_response.headers["location"].startswith("/job-import-runs/")

    run_response = client.get(sync_response.headers["location"])
    assert run_response.status_code == 200
    assert "Succeeded" in run_response.text

    with session_factory() as session:
        review_job = (
            session.query(JobLeadModel).filter(JobLeadModel.external_id.endswith(":review-1")).one()
        )
        review_job_id = review_job.id

    discover_response = client.get("/discover")
    assert discover_response.status_code == 200
    assert "Discovered jobs" in discover_response.text
    assert "Queue filters" in discover_response.text
    assert "Total discovered" in discover_response.text
    assert "Currently shown" in discover_response.text
    assert "Needs review" in discover_response.text
    assert "Ineligible" in discover_response.text
    assert "Matching the current source and search filters." not in discover_response.text
    assert "Rows visible in this review queue." not in discover_response.text
    assert "Jobs with location follow-up still required." not in discover_response.text
    assert "Hidden by default until explicitly filtered in." not in discover_response.text
    assert "Director, Platform Engineering" in discover_response.text
    assert (
        "Senior Director of Platform Engineering, Reliability, and Developer "
        "Productivity" in discover_response.text
    )
    assert (
        "Remote United States with quarterly travel to Seattle, WA and Bay Area "
        "planning sessions" in discover_response.text
    )
    assert "Remote" in discover_response.text
    assert "Greenhouse" in discover_response.text
    assert "Updated Jul" in discover_response.text
    assert "Needs Review" in discover_response.text
    assert "Fit" in discover_response.text
    assert 'aria-label="Fit score ' in discover_response.text
    assert "badge-recommendation" not in discover_response.text
    assert "Job requisition" in discover_response.text
    assert "Eligibility summary" in discover_response.text
    assert "Source status" in discover_response.text
    assert "Observed" in discover_response.text
    assert "Last refreshed" in discover_response.text
    assert (
        "Lead platform engineering with Kubernetes and cloud reliability." in discover_response.text
    )
    assert "View match analysis" in discover_response.text
    assert "Open source posting" in discover_response.text
    assert "Matched verified evidence:" not in discover_response.text
    assert "Positive signals:" not in discover_response.text
    assert "Concerns:" not in discover_response.text
    assert "Missing evidence:" not in discover_response.text
    assert "East Coast Systems" not in discover_response.text

    filtered_discover_response = client.get("/discover?location_eligibility=needs_review")
    assert filtered_discover_response.status_code == 200
    assert "Director, Platform Engineering" in filtered_discover_response.text
    assert "East Coast Systems" not in filtered_discover_response.text

    ineligible_discover_response = client.get("/discover?location_eligibility=ineligible")
    assert ineligible_discover_response.status_code == 200
    assert "East Coast Systems" in ineligible_discover_response.text
    assert (
        "New York, NY metropolitan area with weekly onsite leadership"
        in ineligible_discover_response.text
    )

    status_response = client.post(
        f"/discover/jobs/{review_job_id}/status",
        data={
            "posting_status": "reviewing",
            "return_to": "/discover?location_eligibility=needs_review",
        },
        follow_redirects=False,
    )
    assert status_response.status_code == 303
    assert status_response.headers["location"] == "/discover?location_eligibility=needs_review"

    with session_factory() as session:
        updated_job = session.get(JobLeadModel, review_job_id)
        assert updated_job is not None
        assert updated_job.posting_status == "reviewing"

    app.dependency_overrides.pop(job_source_connector_dependency, None)


def test_saved_search_pages_and_discovery_filter(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as session:
        _seed_candidate(session)

    fake_connector = FakeJobSourceConnector(
        jobs=[
            _greenhouse_posting("strong", location_text="Remote United States"),
            _greenhouse_posting(
                "weak",
                company_name="LedgerWorks",
                title="Finance Operations Manager",
                location_text="New York, NY",
                workplace_type=WorkplaceType.ONSITE,
                description="Own finance operations reporting and vendor invoices.",
            ),
        ]
    )
    app = cast(Any, client.app)
    app.dependency_overrides[job_source_connector_dependency] = lambda: fake_connector

    source_create = client.post(
        "/job-sources",
        data={
            "display_name": "Acme Greenhouse",
            "company_name": "Acme",
            "board_token": "acme-search-web",
            "source_url": "https://boards.greenhouse.io/acme",
        },
        follow_redirects=False,
    )
    source_id = source_create.headers["location"].split("/job-sources/")[1].split("?")[0]
    sync_response = client.post(f"/job-sources/{source_id}/sync", follow_redirects=False)
    assert sync_response.status_code == 303

    search_new = client.get("/job-searches/new")
    assert search_new.status_code == 200
    assert "New Saved Search" in search_new.text

    create_search = client.post(
        "/job-searches",
        data={
            "name": "Platform roles",
            "title_include_patterns": "platform engineering",
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
    assert create_search.status_code == 303

    detail = client.get(create_search.headers["location"])
    assert detail.status_code == 200
    assert "Run now" in detail.text

    search_id = create_search.headers["location"].split("/job-searches/")[1]
    run_response = client.post(f"/job-searches/{search_id}/runs", follow_redirects=False)
    assert run_response.status_code == 303

    run_detail = client.get(run_response.headers["location"])
    assert run_detail.status_code == 200
    assert "Matched jobs" in run_detail.text
    assert "Director, Platform Engineering" in run_detail.text
    assert "Finance Operations Manager" in run_detail.text

    filtered_discover = client.get(f"/discover?search_definition_id={search_id}")
    assert filtered_discover.status_code == 200
    assert "Director, Platform Engineering" in filtered_discover.text
    assert "Finance Operations Manager" not in filtered_discover.text

    app.dependency_overrides.pop(job_source_connector_dependency, None)


def test_empty_job_sources_page(client: TestClient) -> None:
    response = client.get("/job-sources")

    assert response.status_code == 200
    assert "No job sources configured" in response.text


def test_job_source_partial_run_detail_and_invalid_discover_filters(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        source = create_job_source_configuration(
            session,
            provider=JobSourceProvider.GREENHOUSE.value,
            display_name="Acme Greenhouse",
            company_name="Acme",
            board_token="acme-partial-web",
            source_url="https://boards.greenhouse.io/acme",
        )
        run_job_source_import(
            session,
            source_id=source.id,
            connector=FakeJobSourceConnector(
                jobs=[_greenhouse_posting("1"), _greenhouse_posting("2")]
            ),
        )
        partial_run_id = run_job_source_import(
            session,
            source_id=source.id,
            connector=FakeJobSourceConnector(
                jobs=[_greenhouse_posting("1")],
                job_failures=[
                    JobSourceItemFailure(
                        external_id="broken",
                        message="Greenhouse job payload is missing title.",
                    )
                ],
            ),
        ).id

    run_response = client.get(f"/job-import-runs/{partial_run_id}")
    assert run_response.status_code == 200
    assert "Partial" in run_response.text
    assert "Greenhouse job payload is missing title." in run_response.text

    invalid_source_response = client.get("/discover?source_id=not-a-uuid")
    assert invalid_source_response.status_code == 422
    assert "Invalid filter" in invalid_source_response.text

    invalid_score_response = client.get("/discover?minimum_score=not-a-number")
    assert invalid_score_response.status_code == 422
    assert "Invalid filter" in invalid_score_response.text


def test_discover_empty_state_for_unmatched_filters(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        source = create_job_source_configuration(
            session,
            provider=JobSourceProvider.GREENHOUSE.value,
            display_name="Acme Greenhouse",
            company_name="Acme",
            board_token="acme-empty-filter",
            source_url="https://boards.greenhouse.io/acme",
        )
        run_job_source_import(
            session,
            source_id=source.id,
            connector=FakeJobSourceConnector(jobs=[_greenhouse_posting("empty-filter-1")]),
        )

    response = client.get("/discover?company=Nope")

    assert response.status_code == 200
    assert "No matching discovered leads" in response.text
    assert "Reset filters" in response.text


def test_discover_status_update_rejects_invalid_status_and_missing_job(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        job_id = _seed_job(session)

    invalid_status_response = client.post(
        f"/discover/jobs/{job_id}/status",
        data={
            "posting_status": "not-a-real-status",
            "return_to": "/discover",
        },
        follow_redirects=False,
    )
    assert invalid_status_response.status_code == 422
    assert "Invalid filter" in invalid_status_response.text
    assert "Select a valid posting status." in invalid_status_response.text

    missing_job_response = client.post(
        "/discover/jobs/00000000-0000-0000-0000-000000000404/status",
        data={
            "posting_status": "reviewing",
            "return_to": "/discover",
        },
        follow_redirects=False,
    )
    assert missing_job_response.status_code == 404
    assert "Job lead not found" in missing_job_response.text
