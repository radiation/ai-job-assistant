from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from ai_job_finder.application.services import (
    create_candidate_profile,
    create_career_fact,
    create_job_evaluation,
    create_job_lead,
)
from ai_job_finder.domain.enums import (
    CareerFactCategory,
    JobLeadSource,
    RemotePreference,
    VerificationStatus,
    WorkplaceType,
)


def _seed_candidate(session: Session, *, verified: bool = True) -> UUID:
    candidate = create_candidate_profile(
        session,
        full_name="Jordan Lee",
        preferred_locations=["Seattle", "Remote"],
        remote_preference=RemotePreference.FLEXIBLE.value,
        target_levels=["director"],
        target_functions=["platform engineering"],
    )
    create_career_fact(
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
        verification_status=(
            VerificationStatus.VERIFIED.value if verified else VerificationStatus.PENDING.value
        ),
        source_reference="review packet",
    )
    return candidate.id


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
        description_normalized=None,
        compensation_text="$250k",
    )
    return job.id


def test_jobs_rendering(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        candidate_id = _seed_candidate(session)
        job_id = _seed_job(session)
        create_job_evaluation(session, job_lead_id=job_id, candidate_profile_id=candidate_id)

    response = client.get("/jobs")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Northstar" in response.text
    assert "Director, Platform Engineering" in response.text
    assert "Recommend" in response.text or "Strong Recommend" in response.text


def test_empty_job_list(client: TestClient) -> None:
    response = client.get("/jobs")

    assert response.status_code == 200
    assert "No job leads yet" in response.text


def test_job_detail(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        candidate_id = _seed_candidate(session)
        job_id = _seed_job(session)
        create_job_evaluation(session, job_lead_id=job_id, candidate_profile_id=candidate_id)

    response = client.get(f"/jobs/{job_id}")

    assert response.status_code == 200
    assert "Normalized job description" in response.text
    assert "Latest evaluation" in response.text
    assert "Overall score" in response.text


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
    assert response.headers["content-type"].startswith("text/html")
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
    assert "Recommendation" in response.text


def test_evaluation_precondition_failure(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as session:
        _seed_candidate(session, verified=False)
        job_id = _seed_job(session)

    response = client.post(
        f"/jobs/{job_id}/evaluation",
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 409
    assert "At least one verified career fact is required" in response.text


def test_candidate_rendering(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        _seed_candidate(session)

    response = client.get("/candidate")

    assert response.status_code == 200
    assert "Jordan Lee" in response.text
    assert "Platform Engineering" in response.text or "platform engineering" in response.text


def test_career_fact_rendering(client: TestClient, session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        _seed_candidate(session)

    response = client.get("/career-facts")

    assert response.status_code == 200
    assert "Verified facts" in response.text
    assert "40% faster delivery" in response.text
