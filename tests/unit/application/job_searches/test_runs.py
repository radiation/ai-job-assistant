from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.orm import Session, sessionmaker

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
from ai_job_finder.domain.errors import JobSearchDefinitionDisabledError
from ai_job_finder.domain.job_searches import JobSearchRunStatus
from ai_job_finder.domain.job_sources import NormalizedJobPosting
from ai_job_finder.domain.scoring import DEFAULT_SCORING_VERSION
from ai_job_finder.infrastructure.database.base import Base
from ai_job_finder.infrastructure.database.models import JobEvaluationModel, JobSearchMatchModel
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
        assert len(runs) == 2
        assert first_run.id != second_run.id


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
