from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ai_job_finder.application.services import (
    create_candidate_profile,
    create_career_fact,
    create_job_evaluation,
    create_job_lead,
    transition_career_fact,
)
from ai_job_finder.domain.common import new_uuid, utc_now
from ai_job_finder.domain.enums import (
    CareerFactCategory,
    CareerFactLifecycle,
    EvidenceTag,
    JobLeadSource,
    ProvenanceType,
    RemotePreference,
    WorkplaceType,
)
from ai_job_finder.domain.errors import SingleCandidateViolationError
from ai_job_finder.infrastructure.database.models import (
    CandidateProfileModel,
    CareerFactModel,
    JobEvaluationModel,
)


def test_job_lead_uniqueness_constraint(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        create_job_lead(
            session,
            source=JobLeadSource.MANUAL.value,
            source_url=None,
            external_id="duplicate-id",
            company_name="Example",
            title="Director",
            location_text=None,
            workplace_type=WorkplaceType.REMOTE.value,
            description_raw="raw",
            description_normalized="normalized",
            compensation_text=None,
        )
        with pytest.raises(IntegrityError):
            create_job_lead(
                session,
                source=JobLeadSource.MANUAL.value,
                source_url=None,
                external_id="duplicate-id",
                company_name="Example",
                title="Director",
                location_text=None,
                workplace_type=WorkplaceType.REMOTE.value,
                description_raw="raw",
                description_normalized="normalized",
                compensation_text=None,
            )


def test_candidate_single_active_constraint(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        session.add_all(
            [
                CandidateProfileModel(
                    id=new_uuid(),
                    full_name="Jordan Lee",
                    preferred_locations=["Seattle"],
                    remote_preference=RemotePreference.FLEXIBLE.value,
                    target_levels=["director"],
                    target_functions=["platform engineering"],
                    is_active=True,
                    created_at=utc_now(),
                    updated_at=utc_now(),
                ),
                CandidateProfileModel(
                    id=new_uuid(),
                    full_name="Taylor Smith",
                    preferred_locations=["Boston"],
                    remote_preference=RemotePreference.REMOTE_ONLY.value,
                    target_levels=["director"],
                    target_functions=["ai platform"],
                    is_active=True,
                    created_at=utc_now(),
                    updated_at=utc_now(),
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_foreign_key_behavior_on_missing_candidate(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        fact = CareerFactModel(
            id=new_uuid(),
            candidate_profile_id=UUID("00000000-0000-0000-0000-000000000000"),
            category=CareerFactCategory.PLATFORM.value,
            source_organization=None,
            statement="fact",
            metric=None,
            technologies=[],
            leadership_scope=None,
            business_outcome=None,
            approved_wording="fact",
            lifecycle_status=CareerFactLifecycle.DRAFT.value,
            evidence_tags=[],
            provenance_type=ProvenanceType.OTHER.value,
            source_reference="doc",
            verified_at=None,
            archived_at=None,
            created_at=utc_now(),
            updated_at=utc_now(),
        )

        session.add(fact)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_candidate_creation_and_fetch(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        candidate = create_candidate_profile(
            session,
            full_name="Jordan Lee",
            preferred_locations=["Seattle"],
            remote_preference=RemotePreference.FLEXIBLE.value,
            target_levels=["director"],
            target_functions=["platform engineering"],
        )

        session.refresh(candidate)
        assert candidate.full_name == "Jordan Lee"


def test_single_candidate_service_invariant(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        create_candidate_profile(
            session,
            full_name="Jordan Lee",
            preferred_locations=["Seattle"],
            remote_preference=RemotePreference.FLEXIBLE.value,
            target_levels=["director"],
            target_functions=["platform engineering"],
        )
        with pytest.raises(SingleCandidateViolationError):
            create_candidate_profile(
                session,
                full_name="Taylor Smith",
                preferred_locations=["Boston"],
                remote_preference=RemotePreference.REMOTE_ONLY.value,
                target_levels=["director"],
                target_functions=["ai platform"],
            )


def test_draft_and_archived_facts_are_excluded_from_evaluation(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        candidate = create_candidate_profile(
            session,
            full_name="Jordan Lee",
            preferred_locations=["Seattle"],
            remote_preference=RemotePreference.FLEXIBLE.value,
            target_levels=["director"],
            target_functions=["platform engineering"],
        )
        fact = create_career_fact(
            session,
            candidate_profile_id=candidate.id,
            category=CareerFactCategory.PLATFORM.value,
            source_organization="Example",
            statement="Built platform",
            metric="40% faster",
            technologies=["Python"],
            leadership_scope="30 engineers",
            business_outcome="Faster delivery",
            approved_wording="Built platform",
            evidence_tags=[EvidenceTag.PLATFORM_ENGINEERING.value],
            provenance_type=ProvenanceType.PROJECT_NOTES.value,
            source_reference="doc",
        )
        fact = transition_career_fact(
            session,
            fact_id=fact.id,
            lifecycle_status=CareerFactLifecycle.VERIFIED.value,
        )
        transition_career_fact(
            session,
            fact_id=fact.id,
            lifecycle_status=CareerFactLifecycle.ARCHIVED.value,
        )
        job = create_job_lead(
            session,
            source=JobLeadSource.MANUAL.value,
            source_url=None,
            external_id="job-3",
            company_name="Northstar",
            title="Director, Platform Engineering",
            location_text="Seattle, WA",
            workplace_type=WorkplaceType.HYBRID.value,
            description_raw="Own platform strategy.",
            description_normalized="Own platform strategy.",
            compensation_text=None,
        )

        evaluation = create_job_evaluation(
            session, job_lead_id=job.id, candidate_profile_id=candidate.id
        )

        assert "No verified evidence matched the job signals." in evaluation.explanation


def test_previous_evaluation_history_is_preserved(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        candidate = create_candidate_profile(
            session,
            full_name="Jordan Lee",
            preferred_locations=["Seattle"],
            remote_preference=RemotePreference.FLEXIBLE.value,
            target_levels=["director"],
            target_functions=["platform engineering"],
        )
        fact = create_career_fact(
            session,
            candidate_profile_id=candidate.id,
            category=CareerFactCategory.PLATFORM.value,
            source_organization="Example",
            statement="Built platform",
            metric="40% faster",
            technologies=["Python", "Kubernetes"],
            leadership_scope="30 engineers",
            business_outcome="Faster delivery",
            approved_wording="Built platform",
            evidence_tags=[EvidenceTag.PLATFORM_ENGINEERING.value, EvidenceTag.CLOUD.value],
            provenance_type=ProvenanceType.PROJECT_NOTES.value,
            source_reference="doc",
        )
        transition_career_fact(
            session,
            fact_id=fact.id,
            lifecycle_status=CareerFactLifecycle.VERIFIED.value,
        )
        job = create_job_lead(
            session,
            source=JobLeadSource.MANUAL.value,
            source_url=None,
            external_id="job-4",
            company_name="Northstar",
            title="Director, Platform Engineering",
            location_text="Seattle, WA",
            workplace_type=WorkplaceType.HYBRID.value,
            description_raw="Own platform strategy.",
            description_normalized="Own platform strategy and developer platform roadmap.",
            compensation_text=None,
        )
        legacy_evaluation = JobEvaluationModel(
            id=new_uuid(),
            candidate_profile_id=candidate.id,
            job_lead_id=job.id,
            scoring_version="foundation_v1",
            leadership_scope_score=40,
            technical_alignment_score=0,
            location_score=70,
            level_score=100,
            platform_ownership_score=45,
            referral_priority_score=0,
            overall_score=65.0,
            recommendation="recommend",
            explanation="Legacy evaluation",
            evaluated_at=utc_now(),
        )
        session.add(legacy_evaluation)
        session.commit()

        current_evaluation = create_job_evaluation(
            session,
            job_lead_id=job.id,
            candidate_profile_id=candidate.id,
        )
        stored = session.query(JobEvaluationModel).filter_by(job_lead_id=job.id).all()

        assert current_evaluation.scoring_version == "candidate_evidence_v2"
        assert {evaluation.scoring_version for evaluation in stored} == {
            "foundation_v1",
            "candidate_evidence_v2",
        }
