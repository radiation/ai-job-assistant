from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

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
from ai_job_finder.domain.job_sources import NormalizedJobPosting
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
