from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ai_job_finder.application.documents import accept_career_fact_proposal
from ai_job_finder.application.job_searches import (
    create_job_search_definition,
    list_job_search_matches,
    list_job_search_runs,
    run_job_search,
    set_job_search_definition_enabled,
    update_job_search_definition,
)
from ai_job_finder.application.job_sources import (
    create_job_source_configuration,
    run_job_source_import,
)
from ai_job_finder.application.services import (
    create_candidate_profile,
    create_career_fact,
    get_current_candidate_profile,
    retrieve_verified_evidence,
    transition_career_fact,
)
from ai_job_finder.domain.common import new_uuid, utc_now
from ai_job_finder.domain.enums import (
    CareerFactCategory,
    CareerFactLifecycle,
    CareerFactProposalReviewStatus,
    EvidenceTag,
    ExtractionRunStatus,
    JobSourceProvider,
    ProvenanceType,
    RemotePreference,
    SourceDocumentType,
    WorkplaceType,
)
from ai_job_finder.domain.errors import JobSearchDefinitionDisabledError
from ai_job_finder.domain.job_searches import JobSearchRunStatus
from ai_job_finder.domain.job_sources import NormalizedJobPosting
from ai_job_finder.domain.scoring import DEFAULT_SCORING_VERSION
from ai_job_finder.infrastructure.database.base import Base
from ai_job_finder.infrastructure.database.models import (
    CareerFactProposalModel,
    ExtractionRunModel,
    JobEvaluationModel,
    JobLeadModel,
    JobSearchMatchModel,
    SourceDocumentModel,
)
from ai_job_finder.infrastructure.database.session import create_engine_from_url
from ai_job_finder.infrastructure.job_sources.fake import FakeJobSourceConnector


@pytest.fixture()
def session_factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine_from_url("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _seed_candidate(session: Session) -> None:
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
        statement="Built a cloud platform.",
        metric="40% faster delivery",
        technologies=["Python", "Kubernetes"],
        leadership_scope="30 engineers",
        business_outcome="Faster delivery",
        approved_wording="Built a cloud platform with measurable impact.",
        evidence_tags=[
            EvidenceTag.PLATFORM_ENGINEERING.value,
            EvidenceTag.CLOUD.value,
            EvidenceTag.CI_CD.value,
        ],
        provenance_type=ProvenanceType.PROJECT_NOTES.value,
        source_reference="review packet",
    )
    transition_career_fact(
        session,
        fact_id=fact.id,
        lifecycle_status=CareerFactLifecycle.VERIFIED.value,
    )


def _seed_imported_jobs(session: Session) -> None:
    source_id = _create_source(session)
    run_job_source_import(
        session,
        source_id=source_id,
        connector=FakeJobSourceConnector(
            jobs=[
                _posting("strong"),
                _posting(
                    "weak",
                    title="Finance Operations Manager",
                    description="Own finance operations reporting and vendor invoices.",
                    location="New York, NY",
                ),
            ]
        ),
    )


def _posting(
    external_id: str,
    *,
    title: str = "Director, Platform Engineering",
    description: str = "Lead platform engineering with Kubernetes and cloud reliability.",
    location: str = "Remote United States",
) -> NormalizedJobPosting:
    return NormalizedJobPosting(
        provider=JobSourceProvider.GREENHOUSE,
        company_name="Acme",
        title=title,
        location_text=location,
        workplace_type=(
            WorkplaceType.REMOTE
            if location.casefold().startswith("remote")
            else WorkplaceType.ONSITE
        ),
        description_raw=description,
        description_normalized=description,
        compensation_text="$200k - $250k",
        source_url=f"https://boards.greenhouse.io/acme/jobs/{external_id}",
        external_id=external_id,
        internal_job_id=f"req-{external_id}",
        source_updated_at=datetime(2026, 1, 2, tzinfo=UTC),
        departments=["Engineering"],
        offices=[location],
        metadata={"employment_type": "Full-time"},
        raw_payload={"id": external_id},
    )


def _create_source(session: Session) -> UUID:
    source = create_job_source_configuration(
        session,
        provider=JobSourceProvider.GREENHOUSE.value,
        display_name="Acme Greenhouse",
        company_name="Acme",
        board_token="acme",
        source_url="https://boards.greenhouse.io/acme",
    )
    return source.id


def _seed_pending_ai_proposal(session: Session, *, candidate_profile_id: UUID) -> UUID:
    now = utc_now()
    document = SourceDocumentModel(
        id=new_uuid(),
        candidate_profile_id=candidate_profile_id,
        original_filename="resume.txt",
        content_type="text/plain",
        byte_size=32,
        checksum_sha256="a" * 64,
        source_type=SourceDocumentType.RESUME.value,
        storage_key="documents/resume.txt",
        extracted_text="Established AI platform governance.",
        extraction_error=None,
        upload_note=None,
        uploaded_at=now,
        processed_at=now,
        created_at=now,
        updated_at=now,
    )
    extraction_run = ExtractionRunModel(
        id=new_uuid(),
        source_document_id=document.id,
        provider="fake",
        model_id="test-extractor",
        prompt_version="test",
        schema_version="test",
        status=ExtractionRunStatus.SUCCEEDED.value,
        started_at=now,
        completed_at=now,
        input_character_count=32,
        input_token_count=None,
        output_token_count=None,
        chunk_count=1,
        temperature=0.0,
        raw_response=None,
        error_message=None,
        created_at=now,
    )
    proposal = CareerFactProposalModel(
        id=new_uuid(),
        source_document_id=document.id,
        extraction_run_id=extraction_run.id,
        candidate_profile_id=candidate_profile_id,
        proposed_category=CareerFactCategory.TRANSFORMATION.value,
        proposed_source_organization="Example Cloud",
        proposed_statement="Established AI platform governance.",
        proposed_metric=None,
        proposed_technologies=["Python"],
        proposed_leadership_scope=None,
        proposed_business_outcome="Reliable AI delivery",
        proposed_approved_wording="Established AI platform governance.",
        proposed_evidence_tags=[EvidenceTag.AI_ENABLEMENT.value],
        supporting_excerpt="Established AI platform governance.",
        source_location=None,
        confidence=1.0,
        review_status=CareerFactProposalReviewStatus.PENDING.value,
        duplicate_candidate_fact_id=None,
        accepted_career_fact_id=None,
        reviewed_at=None,
        created_at=now,
        updated_at=now,
    )
    session.add_all([document, extraction_run, proposal])
    session.commit()
    return proposal.id


def test_saved_search_crud_enable_disable_and_update(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        search = create_job_search_definition(
            session,
            name="Platform roles",
            title_include_patterns=["platform engineering"],
            title_exclude_patterns=["finance"],
            target_domains=["platform_engineering"],
            target_seniority_levels=["director"],
            allowed_locations=[],
            allowed_remote_geographies=["United States"],
            allowed_workplace_types=["remote"],
            minimum_score_threshold=70,
        )

        updated = update_job_search_definition(
            session,
            search_definition_id=search.id,
            name="Platform and infra roles",
            title_include_patterns=["platform engineering", "infrastructure"],
            title_exclude_patterns=["finance"],
            target_domains=["platform_engineering", "infrastructure"],
            target_seniority_levels=["director"],
            allowed_locations=["Seattle"],
            allowed_remote_geographies=["United States"],
            allowed_workplace_types=["remote", "hybrid"],
            minimum_score_threshold=75,
        )
        disabled = set_job_search_definition_enabled(
            session,
            search_definition_id=search.id,
            enabled=False,
        )

        assert updated.name == "Platform and infra roles"
        assert disabled.enabled is False


def test_manual_run_persists_matches_and_historical_reruns(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        _seed_imported_jobs(session)
        search = create_job_search_definition(
            session,
            name="Platform roles",
            title_include_patterns=["platform engineering"],
            title_exclude_patterns=["finance"],
            target_domains=["platform_engineering"],
            target_seniority_levels=["director"],
            allowed_locations=[],
            allowed_remote_geographies=["United States"],
            allowed_workplace_types=["remote"],
            minimum_score_threshold=70,
        )

        first_run = run_job_search(session, search_definition_id=search.id)
        second_run = run_job_search(session, search_definition_id=search.id)
        first_matches = list_job_search_matches(session, search_run_id=first_run.id)
        runs = list_job_search_runs(session, search_definition_id=search.id)

        assert first_run.status == JobSearchRunStatus.COMPLETED.value
        assert first_run.candidates_considered == 2
        assert first_run.matched_by_criteria == 1
        assert first_run.above_threshold_count == 1
        assert len(first_matches) == 2
        assert sum(record.match.matched for record in first_matches) == 1
        matched = next(record.match for record in first_matches if record.match.matched)
        excluded = next(record.match for record in first_matches if not record.match.matched)
        assert matched.decision_explanation["outcome"] == "matched"
        assert sum(
            component["weighted_score"]
            for component in matched.decision_explanation["score_components"]
        ) == pytest.approx(matched.score_at_match_time)
        assert "title_include_missing" in excluded.exclusion_reason_codes
        assert len(runs) == 2
        assert first_run.id != second_run.id


def test_list_job_search_matches_applies_limit_and_offset(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        _seed_imported_jobs(session)
        search = create_job_search_definition(
            session,
            name="Platform roles",
            title_include_patterns=["platform engineering"],
            title_exclude_patterns=["finance"],
            target_domains=["platform_engineering"],
            target_seniority_levels=["director"],
            allowed_locations=[],
            allowed_remote_geographies=["United States"],
            allowed_workplace_types=["remote"],
            minimum_score_threshold=70,
        )
        run = run_job_search(session, search_definition_id=search.id)

        first_page = list_job_search_matches(session, search_run_id=run.id, limit=1)
        second_page = list_job_search_matches(session, search_run_id=run.id, limit=1, offset=1)

        assert len(first_page) == 1
        assert len(second_page) == 1
        assert first_page[0].match.id != second_page[0].match.id
        first_score = first_page[0].match.score_at_match_time
        second_score = second_page[0].match.score_at_match_time
        assert first_score is not None
        assert second_score is not None
        assert first_score >= second_score


def test_manual_run_reuses_existing_evaluations(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        _seed_imported_jobs(session)
        baseline_evaluation_count = session.query(JobEvaluationModel).count()
        search = create_job_search_definition(
            session,
            name="Platform roles",
            title_include_patterns=["platform engineering"],
            title_exclude_patterns=[],
            target_domains=[],
            target_seniority_levels=[],
            allowed_locations=[],
            allowed_remote_geographies=["United States"],
            allowed_workplace_types=["remote"],
            minimum_score_threshold=0,
        )

        run_job_search(session, search_definition_id=search.id)

        assert session.query(JobEvaluationModel).count() == baseline_evaluation_count


def test_evaluated_count_means_evaluations_successfully_used(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        _seed_imported_jobs(session)
        search = create_job_search_definition(
            session,
            name="Platform roles",
            title_include_patterns=["platform engineering"],
            title_exclude_patterns=[],
            target_domains=[],
            target_seniority_levels=[],
            allowed_locations=[],
            allowed_remote_geographies=["United States"],
            allowed_workplace_types=["remote"],
            minimum_score_threshold=0,
        )

        first_run = run_job_search(session, search_definition_id=search.id)
        second_run = run_job_search(session, search_definition_id=search.id)

        assert first_run.evaluated_count == 2
        assert second_run.evaluated_count == 2
        assert session.query(JobEvaluationModel).count() == 2


def test_run_loads_verified_evidence_once(
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        _seed_imported_jobs(session)
        search = create_job_search_definition(
            session,
            name="Platform roles",
            title_include_patterns=["platform engineering"],
            title_exclude_patterns=[],
            target_domains=[],
            target_seniority_levels=[],
            allowed_locations=[],
            allowed_remote_geographies=["United States"],
            allowed_workplace_types=["remote"],
            minimum_score_threshold=0,
        )

        call_count = 0

        from ai_job_finder.application.services import (
            retrieve_verified_evidence as original_retrieve_verified_evidence,
        )

        def counted_retrieve_verified_evidence(*args: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            return original_retrieve_verified_evidence(*args, **kwargs)

        monkeypatch.setattr(
            "ai_job_finder.application.job_searches.runs.retrieve_verified_evidence",
            counted_retrieve_verified_evidence,
        )

        run = run_job_search(session, search_definition_id=search.id)

        assert run.status == JobSearchRunStatus.COMPLETED.value
        assert call_count == 1


def test_reused_evaluation_is_not_recreated_when_inputs_are_current(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        _seed_imported_jobs(session)
        search = create_job_search_definition(
            session,
            name="Platform roles",
            title_include_patterns=["platform engineering"],
            title_exclude_patterns=[],
            target_domains=[],
            target_seniority_levels=[],
            allowed_locations=[],
            allowed_remote_geographies=["United States"],
            allowed_workplace_types=["remote"],
            minimum_score_threshold=0,
        )

        first_run = run_job_search(session, search_definition_id=search.id)
        evaluations_after_first_run = session.query(JobEvaluationModel).count()
        latest_versions = {
            evaluation.scoring_version for evaluation in session.query(JobEvaluationModel).all()
        }

        second_run = run_job_search(session, search_definition_id=search.id)

        assert first_run.evaluated_count == second_run.evaluated_count == 2
        assert session.query(JobEvaluationModel).count() == evaluations_after_first_run
        assert latest_versions == {DEFAULT_SCORING_VERSION}


def test_verified_evidence_removal_refreshes_saved_search_evaluations(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        _seed_imported_jobs(session)
        search = create_job_search_definition(
            session,
            name="Platform roles",
            title_include_patterns=["platform engineering"],
            title_exclude_patterns=[],
            target_domains=[],
            target_seniority_levels=[],
            allowed_locations=[],
            allowed_remote_geographies=["United States"],
            allowed_workplace_types=["remote"],
            minimum_score_threshold=0,
        )
        first_run = run_job_search(session, search_definition_id=search.id)
        evaluations_before = session.query(JobEvaluationModel).count()
        candidate = get_current_candidate_profile(session)
        assert candidate is not None
        verified_fact = retrieve_verified_evidence(
            session,
            candidate_profile_id=candidate.id,
        )[0]

        transition_career_fact(
            session,
            fact_id=verified_fact.id,
            lifecycle_status=CareerFactLifecycle.DRAFT.value,
        )
        second_run = run_job_search(session, search_definition_id=search.id)

        assert first_run.evaluated_count == second_run.evaluated_count == 2
        assert session.query(JobEvaluationModel).count() == evaluations_before + 2


def test_verified_evidence_addition_refreshes_saved_search_evaluations(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        _seed_imported_jobs(session)
        candidate = get_current_candidate_profile(session)
        assert candidate is not None
        draft_fact = create_career_fact(
            session,
            candidate_profile_id=candidate.id,
            category=CareerFactCategory.TRANSFORMATION.value,
            source_organization="Example Cloud",
            statement="Established AI platform governance.",
            metric=None,
            technologies=["Python"],
            leadership_scope=None,
            business_outcome="Reliable AI delivery",
            approved_wording="Established AI platform governance.",
            evidence_tags=[EvidenceTag.AI_ENABLEMENT.value],
            provenance_type=ProvenanceType.PROJECT_NOTES.value,
            source_reference="review packet",
        )
        search = create_job_search_definition(
            session,
            name="Platform roles",
            title_include_patterns=["platform engineering"],
            title_exclude_patterns=[],
            target_domains=[],
            target_seniority_levels=[],
            allowed_locations=[],
            allowed_remote_geographies=["United States"],
            allowed_workplace_types=["remote"],
            minimum_score_threshold=0,
        )
        first_run = run_job_search(session, search_definition_id=search.id)
        evaluations_before = session.query(JobEvaluationModel).count()

        transition_career_fact(
            session,
            fact_id=draft_fact.id,
            lifecycle_status=CareerFactLifecycle.VERIFIED.value,
        )
        second_run = run_job_search(session, search_definition_id=search.id)

        assert first_run.evaluated_count == second_run.evaluated_count == 2
        assert session.query(JobEvaluationModel).count() == evaluations_before + 2


def test_accepted_proposal_refreshes_saved_search_with_verified_evidence(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        _seed_imported_jobs(session)
        candidate = get_current_candidate_profile(session)
        assert candidate is not None
        strong_job = session.scalar(
            select(JobLeadModel).where(JobLeadModel.title == "Director, Platform Engineering")
        )
        assert strong_job is not None
        strong_job.description_normalized = (
            "Lead platform engineering with AI platform, Kubernetes, and cloud reliability."
        )
        strong_job.description_raw = strong_job.description_normalized
        session.commit()
        proposal_id = _seed_pending_ai_proposal(session, candidate_profile_id=candidate.id)
        search = create_job_search_definition(
            session,
            name="Platform roles",
            title_include_patterns=["platform engineering"],
            title_exclude_patterns=[],
            target_domains=[],
            target_seniority_levels=[],
            allowed_locations=[],
            allowed_remote_geographies=["United States"],
            allowed_workplace_types=["remote"],
            minimum_score_threshold=0,
        )
        first_run = run_job_search(session, search_definition_id=search.id)
        first_evaluation = session.scalar(
            select(JobEvaluationModel)
            .where(JobEvaluationModel.job_lead_id == strong_job.id)
            .order_by(JobEvaluationModel.evaluated_at.desc())
        )
        assert first_evaluation is not None
        evaluations_before = session.query(JobEvaluationModel).count()

        accepted = accept_career_fact_proposal(session, proposal_id=proposal_id)
        accepted_fact_id = accepted.accepted_career_fact_id
        assert accepted_fact_id is not None
        assert any(
            fact.id == accepted_fact_id
            for fact in retrieve_verified_evidence(session, candidate_profile_id=candidate.id)
        )
        second_run = run_job_search(session, search_definition_id=search.id)
        second_evaluation = session.scalar(
            select(JobEvaluationModel)
            .where(JobEvaluationModel.job_lead_id == strong_job.id)
            .order_by(JobEvaluationModel.evaluated_at.desc())
        )
        assert second_evaluation is not None

        assert first_run.evaluated_count == second_run.evaluated_count == 2
        assert session.query(JobEvaluationModel).count() == evaluations_before + 2
        assert (
            second_evaluation.technical_alignment_score > first_evaluation.technical_alignment_score
        )
        assert "Established AI platform governance." in second_evaluation.explanation


def test_manual_run_marks_partial_on_per_job_failure(
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        _seed_imported_jobs(session)
        search = create_job_search_definition(
            session,
            name="Platform roles",
            title_include_patterns=["platform engineering"],
            title_exclude_patterns=[],
            target_domains=[],
            target_seniority_levels=[],
            allowed_locations=[],
            allowed_remote_geographies=["United States"],
            allowed_workplace_types=["remote"],
            minimum_score_threshold=0,
        )

        from ai_job_finder.domain.job_searches import (
            evaluate_job_search_match as original_evaluate_job_search_match,
        )

        def fail_once(*args: Any, **kwargs: Any) -> Any:
            job = args[1]
            if job.external_id and job.external_id.endswith(":weak"):
                raise RuntimeError("intentional failure")
            return original_evaluate_job_search_match(*args, **kwargs)

        monkeypatch.setattr(
            "ai_job_finder.application.job_searches.runs.evaluate_job_search_match",
            fail_once,
        )

        run = run_job_search(session, search_definition_id=search.id)

        assert run.status == JobSearchRunStatus.PARTIAL.value
        assert run.failures_count == 1
        assert "intentional failure" in (run.error_message or "")


def test_manual_run_marks_failed_on_fatal_error(
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        _seed_imported_jobs(session)
        search = create_job_search_definition(
            session,
            name="Platform roles",
            title_include_patterns=["platform engineering"],
            title_exclude_patterns=[],
            target_domains=[],
            target_seniority_levels=[],
            allowed_locations=[],
            allowed_remote_geographies=["United States"],
            allowed_workplace_types=["remote"],
            minimum_score_threshold=0,
        )

        monkeypatch.setattr(
            "ai_job_finder.application.job_searches.runs._candidate_leads_query",
            lambda: (_ for _ in ()).throw(RuntimeError("fatal query failure")),
        )

        run = run_job_search(session, search_definition_id=search.id)

        assert run.status == JobSearchRunStatus.FAILED.value
        assert "fatal query failure" in (run.error_message or "")


def test_manual_run_persists_one_match_per_job_per_run(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        _seed_imported_jobs(session)
        search = create_job_search_definition(
            session,
            name="Platform roles",
            title_include_patterns=["platform engineering"],
            title_exclude_patterns=[],
            target_domains=[],
            target_seniority_levels=[],
            allowed_locations=[],
            allowed_remote_geographies=["United States"],
            allowed_workplace_types=["remote"],
            minimum_score_threshold=0,
        )

        run = run_job_search(session, search_definition_id=search.id)

        assert session.query(JobSearchMatchModel).filter_by(search_run_id=run.id).count() == 2


def test_manual_run_rejects_disabled_saved_search(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        _seed_imported_jobs(session)
        search = create_job_search_definition(
            session,
            name="Platform roles",
            title_include_patterns=["platform engineering"],
            title_exclude_patterns=[],
            target_domains=[],
            target_seniority_levels=[],
            allowed_locations=[],
            allowed_remote_geographies=["United States"],
            allowed_workplace_types=["remote"],
            minimum_score_threshold=0,
            enabled=False,
        )

        with pytest.raises(JobSearchDefinitionDisabledError):
            run_job_search(session, search_definition_id=search.id)
