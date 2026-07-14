from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

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
from ai_job_finder.domain.job_sources import NormalizedJobPosting


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


def test_candidate_first_run_setup_and_validation(client: TestClient) -> None:
    response = client.get("/candidate")
    assert response.status_code == 200
    assert "First-run candidate setup" in response.text

    invalid_response = client.post(
        "/candidate",
        data={
            "full_name": "",
            "preferred_locations": "Seattle",
            "acceptable_remote_geographies": "United States",
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
            "acceptable_remote_geographies": "United States\nCanada",
            "remote_preference": "hybrid",
            "target_levels": "director\nsenior director",
            "target_functions": "platform engineering\ninfrastructure",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Candidate profile updated" in response.text
    assert "New York" in response.text
    assert "Canada" in response.text


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
