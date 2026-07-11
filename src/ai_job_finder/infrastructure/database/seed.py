from __future__ import annotations

from sqlalchemy.orm import Session

from ai_job_finder.application.services import (
    create_candidate_profile,
    create_career_fact,
    create_job_evaluation,
    create_job_lead,
    transition_career_fact,
)
from ai_job_finder.domain.enums import (
    CareerFactCategory,
    EvidenceTag,
    JobLeadSource,
    ProvenanceType,
    RemotePreference,
    WorkplaceType,
)
from ai_job_finder.infrastructure.database.session import get_session_factory


def seed_development_data(session: Session) -> None:
    candidate = create_candidate_profile(
        session,
        full_name="Alex Morgan",
        preferred_locations=["Seattle", "San Francisco", "Remote"],
        remote_preference=RemotePreference.FLEXIBLE.value,
        target_levels=["director", "senior director"],
        target_functions=["platform engineering", "infrastructure"],
    )

    platform_fact = create_career_fact(
        session,
        candidate_profile_id=candidate.id,
        category=CareerFactCategory.PLATFORM.value,
        source_organization="Example Cloud",
        statement="Built a developer platform adopted by 400 engineers.",
        metric="400 engineers onboarded",
        technologies=["Kubernetes", "Python", "Backstage"],
        leadership_scope="Led 4 managers and 28 engineers",
        business_outcome="Reduced deployment lead time by 60%",
        approved_wording=(
            "Built a developer platform adopted by 400 engineers, reducing "
            "deployment lead time by 60%."
        ),
        evidence_tags=[
            EvidenceTag.PLATFORM_ENGINEERING.value,
            EvidenceTag.DEVELOPER_EXPERIENCE.value,
            EvidenceTag.CLOUD.value,
            EvidenceTag.KUBERNETES.value,
            EvidenceTag.CI_CD.value,
        ],
        provenance_type=ProvenanceType.PERFORMANCE_REVIEW.value,
        source_reference="board packet FY25 / platform adoption dashboard",
    )

    leadership_fact = create_career_fact(
        session,
        candidate_profile_id=candidate.id,
        category=CareerFactCategory.LEADERSHIP.value,
        source_organization="Example Cloud",
        statement=(
            "Owned platform strategy across infrastructure, developer productivity, "
            "and reliability."
        ),
        metric=None,
        technologies=["AWS", "Terraform"],
        leadership_scope="Directed a 45-person organization",
        business_outcome="Increased service availability to 99.95%",
        approved_wording=(
            "Directed a 45-person platform organization spanning infrastructure, "
            "developer productivity, and reliability."
        ),
        evidence_tags=[
            EvidenceTag.PEOPLE_LEADERSHIP.value,
            EvidenceTag.MANAGER_OF_MANAGERS.value,
            EvidenceTag.RELIABILITY.value,
            EvidenceTag.INFRASTRUCTURE.value,
            EvidenceTag.HIGH_SCALE.value,
        ],
        provenance_type=ProvenanceType.PROJECT_NOTES.value,
        source_reference="leadership review summary",
    )

    transition_career_fact(
        session,
        fact_id=platform_fact.id,
        lifecycle_status="verified",
    )
    transition_career_fact(
        session,
        fact_id=leadership_fact.id,
        lifecycle_status="verified",
    )

    job = create_job_lead(
        session,
        source=JobLeadSource.MANUAL.value,
        source_url="https://example.com/jobs/director-platform-engineering",
        external_id="director-platform-001",
        company_name="Northstar Systems",
        title="Director, Platform Engineering",
        location_text="Seattle, WA",
        workplace_type=WorkplaceType.HYBRID.value,
        description_raw=(
            "Own the developer platform strategy, roadmap, and teams building "
            "self-service infrastructure."
        ),
        description_normalized=(
            "Own the developer platform strategy, roadmap, and teams building "
            "self-service infrastructure across the engineering organization."
        ),
        compensation_text="$260,000 - $310,000 + equity",
    )

    create_job_evaluation(session, job_lead_id=job.id, candidate_profile_id=candidate.id)


def main() -> None:
    with get_session_factory()() as session:
        seed_development_data(session)
