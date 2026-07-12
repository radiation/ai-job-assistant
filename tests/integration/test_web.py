from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from ai_job_finder.api.dependencies import job_source_connector_dependency
from ai_job_finder.application.job_imports import (
    create_job_source_configuration,
    run_job_source_import,
)
from ai_job_finder.application.services import (
    create_candidate_profile,
    create_career_fact,
    create_job_evaluation,
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
    description: str = "Lead platform engineering with Kubernetes and cloud reliability.",
    raw_description: str | None = None,
) -> NormalizedJobPosting:
    return NormalizedJobPosting(
        provider=JobSourceProvider.GREENHOUSE,
        company_name="Acme",
        title="Director, Platform Engineering",
        location_text="Remote",
        workplace_type=WorkplaceType.REMOTE,
        description_raw=raw_description or description,
        description_normalized=description,
        compensation_text="$200k",
        source_url=f"https://boards.greenhouse.io/acme/jobs/{external_id}",
        external_id=external_id,
        internal_job_id=f"req-{external_id}",
        source_updated_at=None,
        raw_payload={"id": external_id},
    )


def test_jobs_rendering(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        candidate_id, _ = _seed_candidate(session)
        job_id = _seed_job(session)
        create_job_evaluation(session, job_lead_id=job_id, candidate_profile_id=candidate_id)

    response = client.get("/jobs")

    assert response.status_code == 200
    assert "Northstar" in response.text
    assert "Director, Platform Engineering" in response.text
    assert "Recommend" in response.text or "Strong Recommend" in response.text


def test_empty_job_list(client: TestClient) -> None:
    response = client.get("/jobs")

    assert response.status_code == 200
    assert "No job leads yet" in response.text


def test_job_detail(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        candidate_id, _ = _seed_candidate(session)
        job_id = _seed_job(session)
        create_job_evaluation(session, job_lead_id=job_id, candidate_profile_id=candidate_id)

    response = client.get(f"/jobs/{job_id}")

    assert response.status_code == 200
    assert "Normalized job description" in response.text
    assert "Matched verified evidence:" in response.text


def test_unknown_job_handling(client: TestClient) -> None:
    response = client.get("/jobs/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert "Job lead not found" in response.text


def test_new_job_validation(client: TestClient) -> None:
    response = client.post(
        "/jobs",
        data={
            "source": "manual",
            "company_name": "",
            "title": "",
            "location_text": "",
            "workplace_type": "",
            "description_raw": "",
            "compensation_text": "",
            "source_url": "",
            "external_id": "",
        },
    )

    assert response.status_code == 422
    assert "String should have at least 1 character" in response.text


def test_successful_job_creation_redirect(client: TestClient) -> None:
    response = client.post(
        "/jobs",
        data={
            "source": "manual",
            "company_name": "Northstar",
            "title": "Director, Platform Engineering",
            "location_text": "Seattle, WA",
            "workplace_type": "hybrid",
            "description_raw": "Own platform strategy.",
            "compensation_text": "$250k",
            "source_url": "https://example.com/jobs/1",
            "external_id": "job-1",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/jobs/")


def test_status_htmx_success(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        job_id = _seed_job(session)

    response = client.post(
        f"/jobs/{job_id}/status",
        data={"posting_status": "reviewing"},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert "Posting status" in response.text
    assert "Reviewing" in response.text


def test_invalid_status_transition(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as session:
        job_id = _seed_job(session)

    response = client.post(
        f"/jobs/{job_id}/status",
        data={"posting_status": "pursuing"},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 409
    assert "Cannot transition job lead" in response.text


def test_evaluation_trigger_success(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        job_id = _seed_job(session)

    response = client.post(
        f"/jobs/{job_id}/evaluation",
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert "Overall score" in response.text
    assert "Matched verified evidence:" in response.text


def test_evaluation_allows_provisional_result_without_verified_facts(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as session:
        _seed_candidate(session, verified=False)
        job_id = _seed_job(session)

    response = client.post(
        f"/jobs/{job_id}/evaluation",
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert "No verified evidence matched the job signals." in response.text
    assert "No verified career facts are available yet" in response.text


def test_candidate_first_run_setup_and_validation(client: TestClient) -> None:
    response = client.get("/candidate")
    assert response.status_code == 200
    assert "First-run candidate setup" in response.text

    invalid_response = client.post(
        "/candidate",
        data={
            "full_name": "",
            "preferred_locations": "Seattle",
            "remote_preference": "flexible",
            "target_levels": "director",
            "target_functions": "platform engineering",
        },
    )
    assert invalid_response.status_code == 422
    assert "Seattle" in invalid_response.text


def test_candidate_edit_success(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        _seed_candidate(session)

    response = client.post(
        "/candidate/edit",
        data={
            "full_name": "Jordan Lee",
            "preferred_locations": "Seattle\nNew York",
            "remote_preference": "hybrid",
            "target_levels": "director\nsenior director",
            "target_functions": "platform engineering\ninfrastructure",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Candidate profile updated" in response.text
    assert "New York" in response.text


def test_career_fact_create_form_and_detail(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as session:
        _seed_candidate(session, verified=False)

    new_page = client.get("/career-facts/new")
    assert new_page.status_code == 200
    assert "Create career fact" in new_page.text

    created = client.post(
        "/career-facts",
        data={
            "category": "platform",
            "source_organization": "Example Cloud",
            "statement": "Built internal platform",
            "metric": "40% faster",
            "technologies": "Python\nKubernetes",
            "leadership_scope": "30 engineers",
            "business_outcome": "Faster delivery",
            "approved_wording": "Built internal platform with measurable impact",
            "evidence_tags": ["platform_engineering", "cloud"],
            "provenance_type": "project_notes",
            "source_reference": "review packet",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303

    detail = client.get(created.headers["location"])
    assert detail.status_code == 200
    assert "Built internal platform" in detail.text
    assert "Project Notes" in detail.text


def test_fact_list_filters_and_archived_visibility(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as session:
        candidate_id, _first_fact_id = _seed_candidate(session)
        second_fact = create_career_fact(
            session,
            candidate_profile_id=candidate_id,
            category=CareerFactCategory.LEADERSHIP.value,
            source_organization="Northstar",
            statement="Managed managers globally",
            metric=None,
            technologies=["Terraform"],
            leadership_scope="4 managers",
            business_outcome="Improved reliability",
            approved_wording="Managed managers globally with measurable reliability gains",
            evidence_tags=[
                EvidenceTag.PEOPLE_LEADERSHIP.value,
                EvidenceTag.GLOBAL_OPERATIONS.value,
            ],
            provenance_type=ProvenanceType.PERFORMANCE_REVIEW.value,
            source_reference="review summary",
        )
        transition_career_fact(
            session,
            fact_id=second_fact.id,
            lifecycle_status=CareerFactLifecycle.ARCHIVED.value,
        )

    default_list = client.get("/career-facts")
    assert default_list.status_code == 200
    assert "Managed managers globally" not in default_list.text
    assert "Built a platform adopted by engineering." in default_list.text

    archived_list = client.get("/career-facts?lifecycle_status=archived")
    assert archived_list.status_code == 200
    assert "Managed managers globally" in archived_list.text

    tag_list = client.get("/career-facts?evidence_tag=platform_engineering")
    assert tag_list.status_code == 200
    assert "Built a platform adopted by engineering." in tag_list.text


def test_lifecycle_htmx_actions_and_invalid_transition(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as session:
        _, fact_id = _seed_candidate(session, verified=False)

    verify_response = client.post(
        f"/career-facts/{fact_id}/lifecycle",
        data={"lifecycle_status": "verified"},
        headers={"HX-Request": "true"},
    )
    assert verify_response.status_code == 200
    assert "Verified" in verify_response.text

    archive_response = client.post(
        f"/career-facts/{fact_id}/lifecycle",
        data={"lifecycle_status": "archived"},
        headers={"HX-Request": "true"},
    )
    assert archive_response.status_code == 200
    assert "Archived" in archive_response.text

    invalid_response = client.post(
        f"/career-facts/{fact_id}/lifecycle",
        data={"lifecycle_status": "verified"},
        headers={"HX-Request": "true"},
    )
    assert invalid_response.status_code == 409
    assert "Cannot transition career fact from archived to verified" in invalid_response.text


def test_verified_edit_returns_fact_to_draft(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as session:
        _, fact_id = _seed_candidate(session, verified=True)

    edit_page = client.get(f"/career-facts/{fact_id}/edit")
    assert edit_page.status_code == 200
    assert "returns it to draft" in edit_page.text

    updated = client.post(
        f"/career-facts/{fact_id}/edit",
        data={
            "category": "platform",
            "source_organization": "Example Cloud",
            "statement": "Built a platform and developer portal adopted by engineering.",
            "metric": "40% faster delivery",
            "technologies": "Python\nKubernetes",
            "leadership_scope": "30 engineers",
            "business_outcome": "Faster delivery",
            "approved_wording": (
                "Built a platform and developer portal adopted by engineering with "
                "measurable impact."
            ),
            "evidence_tags": ["platform_engineering", "developer_experience"],
            "provenance_type": "project_notes",
            "source_reference": "review packet",
        },
        follow_redirects=True,
    )
    assert updated.status_code == 200
    assert "Draft" in updated.text
    assert "Career fact updated" in updated.text


def test_job_sources_and_discover_pages(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as session:
        _seed_candidate(session)

    fake_connector = FakeJobSourceConnector(
        jobs=[
            NormalizedJobPosting(
                provider=JobSourceProvider.GREENHOUSE,
                company_name="Acme",
                title="Director, Platform Engineering",
                location_text="Remote",
                workplace_type=WorkplaceType.REMOTE,
                description_raw="Lead platform engineering with Kubernetes and cloud reliability.",
                description_normalized=(
                    "Lead platform engineering with Kubernetes and cloud reliability."
                ),
                compensation_text="$200k",
                source_url="https://boards.greenhouse.io/acme/jobs/1",
                external_id="1",
                internal_job_id="req-1",
                source_updated_at=None,
                raw_payload={"id": "1"},
            )
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

    discover_response = client.get("/discover")
    assert discover_response.status_code == 200
    assert "Director, Platform Engineering" in discover_response.text
    assert "Strong Recommend" in discover_response.text or "Recommend" in discover_response.text

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


def test_greenhouse_job_detail_suppresses_raw_markup(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        source = create_job_source_configuration(
            session,
            provider=JobSourceProvider.GREENHOUSE.value,
            display_name="Acme Greenhouse",
            company_name="Acme",
            board_token="acme-detail",
            source_url="https://boards.greenhouse.io/acme",
        )
        run_job_source_import(
            session,
            source_id=source.id,
            connector=FakeJobSourceConnector(
                jobs=[
                    _greenhouse_posting(
                        "raw-html",
                        description="Visible normalized text",
                        raw_description="<script>alert(1)</script><p>Visible normalized text</p>",
                    )
                ]
            ),
        )
        job = (
            session.query(JobLeadModel).filter(JobLeadModel.external_id.endswith(":raw-html")).one()
        )
        job_id = job.id

    response = client.get(f"/jobs/{job_id}")

    assert response.status_code == 200
    assert (
        "Original Greenhouse markup is retained for provenance and not rendered in the UI."
        in response.text
    )
    assert "<script>alert(1)</script>" not in response.text
    assert "Open source posting" in response.text
    assert 'rel="noopener noreferrer"' in response.text
