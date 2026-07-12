from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError
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
from ai_job_finder.domain.common import new_uuid, utc_now
from ai_job_finder.domain.enums import (
    CareerFactCategory,
    CareerFactLifecycle,
    EvidenceTag,
    JobLeadSource,
    JobSourceProvider,
    ProvenanceType,
    RemotePreference,
    SourcePostingStatus,
    WorkplaceType,
)
from ai_job_finder.domain.errors import SingleCandidateViolationError
from ai_job_finder.domain.job_sources import NormalizedJobPosting
from ai_job_finder.infrastructure.database.models import (
    CandidateProfileModel,
    CareerFactModel,
    JobEvaluationModel,
    JobImportRunModel,
    JobLeadModel,
    JobSourceConfigurationModel,
    JobSourceObservationModel,
)
from ai_job_finder.infrastructure.job_sources.fake import FakeJobSourceConnector


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


def _import_posting(
    external_id: str, *, title: str = "Director, Platform Engineering"
) -> NormalizedJobPosting:
    return NormalizedJobPosting(
        provider=JobSourceProvider.GREENHOUSE,
        company_name="Acme",
        title=title,
        location_text="Remote",
        workplace_type=WorkplaceType.REMOTE,
        description_raw="Lead platform engineering with Kubernetes and cloud reliability.",
        description_normalized="Lead platform engineering with Kubernetes and cloud reliability.",
        compensation_text=None,
        source_url=f"https://boards.greenhouse.io/acme/jobs/{external_id}",
        external_id=external_id,
        internal_job_id=f"req-{external_id}",
        source_updated_at=datetime(2026, 1, 2, tzinfo=UTC),
        raw_payload={"id": external_id},
    )


def test_job_source_uniqueness_constraint(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        session.add_all(
            [
                JobSourceConfigurationModel(
                    id=new_uuid(),
                    provider=JobSourceProvider.GREENHOUSE.value,
                    display_name="Acme",
                    company_name="Acme",
                    board_token="acme",
                    source_url=None,
                    enabled=True,
                    created_at=utc_now(),
                    updated_at=utc_now(),
                ),
                JobSourceConfigurationModel(
                    id=new_uuid(),
                    provider=JobSourceProvider.GREENHOUSE.value,
                    display_name="Acme Duplicate",
                    company_name="Acme",
                    board_token="acme",
                    source_url=None,
                    enabled=True,
                    created_at=utc_now(),
                    updated_at=utc_now(),
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_job_source_observation_linkage_idempotency_closure_and_reactivation(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        candidate = create_candidate_profile(
            session,
            full_name="Jordan Lee",
            preferred_locations=["Remote"],
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
            metric=None,
            technologies=["Kubernetes"],
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
        source = create_job_source_configuration(
            session,
            provider=JobSourceProvider.GREENHOUSE.value,
            display_name="Acme",
            company_name="Acme",
            board_token="acme",
            source_url=None,
        )

        first_run = run_job_source_import(
            session,
            source_id=source.id,
            connector=FakeJobSourceConnector(jobs=[_import_posting("1"), _import_posting("2")]),
        )
        second_run = run_job_source_import(
            session,
            source_id=source.id,
            connector=FakeJobSourceConnector(jobs=[_import_posting("1"), _import_posting("2")]),
        )
        close_run = run_job_source_import(
            session,
            source_id=source.id,
            connector=FakeJobSourceConnector(jobs=[_import_posting("1")]),
        )
        reactivate_run = run_job_source_import(
            session,
            source_id=source.id,
            connector=FakeJobSourceConnector(jobs=[_import_posting("1"), _import_posting("2")]),
        )

        observations = list(session.query(JobSourceObservationModel).all())
        jobs = list(session.query(JobLeadModel).all())
        evaluations = list(session.query(JobEvaluationModel).all())
        assert first_run.jobs_created == 2
        assert second_run.jobs_unchanged == 2
        assert close_run.jobs_closed == 1
        assert reactivate_run.jobs_updated == 1
        assert len(observations) == 2
        assert len(jobs) == 2
        assert len(evaluations) == 2
        assert all(observation.job_lead_id for observation in observations)
        assert {job.source_posting_status for job in jobs} == {SourcePostingStatus.OPEN.value}


def test_running_import_uniqueness_is_per_source(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        first_source = create_job_source_configuration(
            session,
            provider=JobSourceProvider.GREENHOUSE.value,
            display_name="Acme",
            company_name="Acme",
            board_token="acme-a",
            source_url=None,
        )
        second_source = create_job_source_configuration(
            session,
            provider=JobSourceProvider.GREENHOUSE.value,
            display_name="Acme EU",
            company_name="Acme",
            board_token="acme-b",
            source_url=None,
        )

        session.add_all(
            [
                JobImportRunModel(
                    id=new_uuid(),
                    source_configuration_id=first_source.id,
                    provider=JobSourceProvider.GREENHOUSE.value,
                    status="running",
                    connector_version="fake",
                ),
                JobImportRunModel(
                    id=new_uuid(),
                    source_configuration_id=second_source.id,
                    provider=JobSourceProvider.GREENHOUSE.value,
                    status="running",
                    connector_version="fake",
                ),
            ]
        )
        session.commit()

        session.add(
            JobImportRunModel(
                id=new_uuid(),
                source_configuration_id=first_source.id,
                provider=JobSourceProvider.GREENHOUSE.value,
                status="running",
                connector_version="fake",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
