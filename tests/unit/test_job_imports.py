from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ai_job_finder.application.job_imports import (
    create_job_source_configuration,
    duplicate_hint_key,
    run_job_source_import,
)
from ai_job_finder.application.services import (
    create_candidate_profile,
    create_career_fact,
    transition_career_fact,
    update_job_lead_status,
)
from ai_job_finder.domain.enums import (
    CareerFactCategory,
    CareerFactLifecycle,
    EvidenceTag,
    JobImportRunStatus,
    JobSourceProvider,
    PostingStatus,
    ProvenanceType,
    RemotePreference,
    SourcePostingStatus,
    WorkplaceType,
)
from ai_job_finder.domain.errors import (
    JobSourceDisabledError,
    JobSourceProviderError,
    OverlappingJobImportError,
)
from ai_job_finder.domain.job_sources import (
    JobSourceConfigurationSnapshot,
    JobSourceItemFailure,
    NormalizedJobPosting,
)
from ai_job_finder.infrastructure.database.base import Base
from ai_job_finder.infrastructure.database.models import (
    JobEvaluationModel,
    JobImportRunModel,
    JobLeadModel,
    JobSourceConfigurationModel,
    JobSourceObservationModel,
)
from ai_job_finder.infrastructure.database.session import create_engine_from_url
from ai_job_finder.infrastructure.job_sources.fake import FakeJobSourceConnector
from ai_job_finder.infrastructure.job_sources.greenhouse import (
    html_to_plain_text,
    parse_greenhouse_job,
)


@pytest.fixture()
def session_factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine_from_url("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _seed_candidate(session: Session) -> UUID:
    candidate = create_candidate_profile(
        session,
        full_name="Jordan Lee",
        preferred_locations=["Remote", "Seattle"],
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
        evidence_tags=[EvidenceTag.PLATFORM_ENGINEERING.value, EvidenceTag.CLOUD.value],
        provenance_type=ProvenanceType.PROJECT_NOTES.value,
        source_reference="review packet",
    )
    transition_career_fact(
        session,
        fact_id=fact.id,
        lifecycle_status=CareerFactLifecycle.VERIFIED.value,
    )
    return candidate.id


def _source_snapshot() -> JobSourceConfigurationSnapshot:
    return JobSourceConfigurationSnapshot(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        provider=JobSourceProvider.GREENHOUSE,
        display_name="Acme Greenhouse",
        company_name="Acme",
        board_token="acme",
        source_url="https://boards.greenhouse.io/acme",
        enabled=True,
        last_successful_sync_at=None,
        last_sync_status=None,
        last_sync_error=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _posting(
    external_id: str,
    *,
    title: str = "Director, Platform Engineering",
    description: str = "Lead platform engineering with Kubernetes and cloud reliability.",
    location: str = "Remote",
    internal_job_id: str | None = "req-1",
) -> NormalizedJobPosting:
    return NormalizedJobPosting(
        provider=JobSourceProvider.GREENHOUSE,
        company_name="Acme",
        title=title,
        location_text=location,
        workplace_type=WorkplaceType.REMOTE,
        description_raw=description,
        description_normalized=description,
        compensation_text="$200k - $250k",
        source_url=f"https://boards.greenhouse.io/acme/jobs/{external_id}",
        external_id=external_id,
        internal_job_id=internal_job_id,
        source_updated_at=datetime(2026, 1, 2, tzinfo=UTC),
        departments=["Engineering"],
        offices=["Remote"],
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


def test_greenhouse_parsing_missing_optional_fields_and_html_normalization() -> None:
    payload = {
        "id": 123,
        "title": "Director, Platform Engineering",
        "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
        "content": (
            "<p>Lead <strong>platform</strong></p><ul><li>Kubernetes</li></ul>"
            "<script>bad()</script>"
        ),
        "location": {"name": "Remote"},
        "updated_at": "2026-01-02T03:04:05Z",
    }

    posting = parse_greenhouse_job(_source_snapshot(), payload)

    assert posting.external_id == "123"
    assert posting.internal_job_id is None
    assert posting.workplace_type == WorkplaceType.REMOTE
    assert posting.description_normalized == "Lead platform\nKubernetes"
    assert "<script>" not in html_to_plain_text(cast(str, payload["content"]))


def test_duplicate_hint_is_deterministic() -> None:
    first = _posting("1")
    second = _posting("1", internal_job_id="req-1")

    assert duplicate_hint_key(first) == duplicate_hint_key(second)


def test_import_idempotency_material_change_and_evaluation_history(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        source_id = _create_source(session)

        first_run = run_job_source_import(
            session,
            source_id=source_id,
            connector=FakeJobSourceConnector(jobs=[_posting("1")]),
        )
        second_run = run_job_source_import(
            session,
            source_id=source_id,
            connector=FakeJobSourceConnector(jobs=[_posting("1")]),
        )
        changed_run = run_job_source_import(
            session,
            source_id=source_id,
            connector=FakeJobSourceConnector(
                jobs=[
                    _posting(
                        "1",
                        description=(
                            "Lead developer platform, Kubernetes, CI/CD, and observability."
                        ),
                    )
                ]
            ),
        )

        assert first_run.jobs_created == 1
        assert first_run.evaluations_created == 1
        assert second_run.jobs_unchanged == 1
        assert second_run.evaluations_created == 0
        assert changed_run.jobs_updated == 1
        assert changed_run.evaluations_created == 1
        assert len(list(session.scalars(select(JobLeadModel)))) == 1
        assert len(list(session.scalars(select(JobEvaluationModel)))) == 2


def test_closure_safety_failure_empty_and_reactivation(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        source_id = _create_source(session)
        run_job_source_import(
            session,
            source_id=source_id,
            connector=FakeJobSourceConnector(jobs=[_posting("1"), _posting("2")]),
        )

        failed_run = run_job_source_import(
            session,
            source_id=source_id,
            connector=FakeJobSourceConnector(error=JobSourceProviderError("provider unavailable")),
        )
        assert failed_run.status == JobImportRunStatus.FAILED.value
        assert _active_observations(session) == 2

        empty_run = run_job_source_import(
            session,
            source_id=source_id,
            connector=FakeJobSourceConnector(jobs=[], suspicious_empty=True),
        )
        assert empty_run.status == JobImportRunStatus.PARTIAL.value
        assert _active_observations(session) == 2

        close_run = run_job_source_import(
            session,
            source_id=source_id,
            connector=FakeJobSourceConnector(jobs=[_posting("1")]),
        )
        assert close_run.jobs_closed == 1
        assert _active_observations(session) == 1
        closed_job = session.scalar(
            select(JobLeadModel).where(JobLeadModel.external_id.endswith(":2"))
        )
        assert closed_job is not None
        assert closed_job.source_posting_status == SourcePostingStatus.CLOSED.value

        reactivate_run = run_job_source_import(
            session,
            source_id=source_id,
            connector=FakeJobSourceConnector(jobs=[_posting("1"), _posting("2")]),
        )
        assert reactivate_run.jobs_updated == 1
        assert _active_observations(session) == 2
        session.refresh(closed_job)
        assert closed_job.source_posting_status == SourcePostingStatus.OPEN.value


def test_import_run_terminal_status_after_evaluation_failure(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        source_id = _create_source(session)
        run_job_source_import(
            session,
            source_id=source_id,
            connector=FakeJobSourceConnector(jobs=[_posting("1"), _posting("2")]),
        )

        def fail_evaluation(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError("bad scoring input")

        monkeypatch.setattr(
            "ai_job_finder.application.job_imports.evaluate_job_fit",
            fail_evaluation,
        )

        run = run_job_source_import(
            session,
            source_id=source_id,
            connector=FakeJobSourceConnector(
                jobs=[
                    _posting(
                        "1",
                        description=(
                            "Lead platform engineering with Kubernetes, cloud reliability, "
                            "and observability."
                        ),
                    )
                ]
            ),
        )

        assert run.status == JobImportRunStatus.PARTIAL.value
        assert run.completed_at is not None
        assert run.evaluation_failures == 1
        assert len(list(session.scalars(select(JobLeadModel)))) == 2
        assert _active_observations(session) == 2


def test_connector_item_failure_makes_run_partial_and_closes_nothing(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        source_id = _create_source(session)
        run_job_source_import(
            session,
            source_id=source_id,
            connector=FakeJobSourceConnector(jobs=[_posting("1"), _posting("2")]),
        )

        run = run_job_source_import(
            session,
            source_id=source_id,
            connector=FakeJobSourceConnector(
                jobs=[_posting("1")],
                job_failures=[
                    JobSourceItemFailure(
                        external_id="broken",
                        message="Greenhouse job payload is missing title.",
                    )
                ],
            ),
        )

        assert run.status == JobImportRunStatus.PARTIAL.value
        assert run.jobs_failed == 1
        assert run.jobs_closed == 0
        assert _active_observations(session) == 2


@pytest.mark.parametrize(
    ("stage", "posting_external_id"),
    [
        ("after_job_lead_flush", "bad-lead"),
        ("after_observation_flush", "bad-observation"),
        ("after_payload_update", "1"),
    ],
)
def test_failed_posting_rolls_back_partial_writes(
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    posting_external_id: str,
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        source_id = _create_source(session)
        if stage == "after_payload_update":
            run_job_source_import(
                session,
                source_id=source_id,
                connector=FakeJobSourceConnector(jobs=[_posting("1")]),
            )
            original_title = session.scalar(
                select(JobLeadModel.title).where(JobLeadModel.external_id.endswith(":1"))
            )
        else:
            original_title = None

        original_flush = session.flush
        injected_failure = False

        def fail_flush(objects: Sequence[object] | None = None) -> object:
            nonlocal injected_failure
            if injected_failure:
                return original_flush(objects)

            pending_lead = next(
                (
                    obj
                    for obj in session.new
                    if isinstance(obj, JobLeadModel)
                    and obj.external_id is not None
                    and obj.external_id.endswith(f":{posting_external_id}")
                ),
                None,
            )
            pending_observation = next(
                (
                    obj
                    for obj in session.new
                    if isinstance(obj, JobSourceObservationModel)
                    and obj.external_post_id == posting_external_id
                ),
                None,
            )
            dirty_updated_job = next(
                (
                    obj
                    for obj in session.dirty
                    if isinstance(obj, JobLeadModel)
                    and obj.external_id is not None
                    and obj.external_id.endswith(f":{posting_external_id}")
                    and obj.title == "Broken title"
                ),
                None,
            )

            if stage == "after_job_lead_flush" and pending_lead is not None:
                original_flush(objects)
                injected_failure = True
                raise RuntimeError("fail after job lead flush")
            if stage == "after_observation_flush" and pending_observation is not None:
                original_flush(objects)
                injected_failure = True
                raise RuntimeError("fail after observation flush")
            if stage == "after_payload_update" and dirty_updated_job is not None:
                original_flush(objects)
                injected_failure = True
                raise RuntimeError("fail after payload update")

            return original_flush(objects)

        monkeypatch.setattr(session, "flush", fail_flush)

        postings = [_posting("good")]
        if stage == "after_payload_update":
            postings.append(_posting("1", title="Broken title"))
        else:
            postings.append(_posting(posting_external_id))

        run = run_job_source_import(
            session,
            source_id=source_id,
            connector=FakeJobSourceConnector(jobs=postings),
        )

        assert run.status == JobImportRunStatus.PARTIAL.value
        assert run.jobs_failed == 1
        failed_job = session.scalar(
            select(JobLeadModel).where(JobLeadModel.external_id.endswith(f":{posting_external_id}"))
        )
        if stage != "after_payload_update":
            assert failed_job is None
        if stage == "after_payload_update":
            restored_title = session.scalar(
                select(JobLeadModel.title).where(JobLeadModel.external_id.endswith(":1"))
            )
            assert restored_title == original_title
        assert (
            session.scalar(select(JobLeadModel).where(JobLeadModel.external_id.endswith(":good")))
            is not None
        )


def test_evaluation_flush_failure_rolls_back_partial_evaluation(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        source_id = _create_source(session)
        original_flush = session.flush

        def flaky_flush(objects: Sequence[object] | None = None) -> object:
            if any(isinstance(obj, JobEvaluationModel) for obj in session.new):
                raise RuntimeError("evaluation flush failed")
            return original_flush(objects)

        monkeypatch.setattr(session, "flush", flaky_flush)

        run = run_job_source_import(
            session,
            source_id=source_id,
            connector=FakeJobSourceConnector(jobs=[_posting("1")]),
        )

        assert run.status == JobImportRunStatus.PARTIAL.value
        assert run.evaluation_failures == 1
        assert len(list(session.scalars(select(JobLeadModel)))) == 1
        assert len(list(session.scalars(select(JobEvaluationModel)))) == 0


def test_disabled_source_cannot_sync(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        source_id = _create_source(session)
        source = session.get(JobSourceConfigurationModel, source_id)
        assert source is not None
        source.enabled = False
        session.add(source)
        session.commit()

        with pytest.raises(JobSourceDisabledError):
            run_job_source_import(
                session,
                source_id=source_id,
                connector=FakeJobSourceConnector(jobs=[_posting("1")]),
            )


def test_non_scoring_change_does_not_create_new_evaluation(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        source_id = _create_source(session)
        run_job_source_import(
            session,
            source_id=source_id,
            connector=FakeJobSourceConnector(jobs=[_posting("1")]),
        )

        run = run_job_source_import(
            session,
            source_id=source_id,
            connector=FakeJobSourceConnector(
                jobs=[
                    _posting(
                        "1",
                        internal_job_id="req-1b",
                    )
                ]
            ),
        )

        assert run.jobs_updated == 1
        assert run.evaluations_created == 0
        assert len(list(session.scalars(select(JobEvaluationModel)))) == 1


@pytest.mark.parametrize(
    "updated_posting",
    [
        _posting("1", title="Senior Director, Platform Engineering"),
        _posting("1", description="Lead platform reliability and observability."),
        NormalizedJobPosting(
            provider=JobSourceProvider.GREENHOUSE,
            company_name="Acme",
            title="Director, Platform Engineering",
            location_text="Hybrid - Seattle",
            workplace_type=WorkplaceType.HYBRID,
            description_raw="Lead platform engineering with Kubernetes and cloud reliability.",
            description_normalized=(
                "Lead platform engineering with Kubernetes and cloud reliability."
            ),
            compensation_text="$200k - $250k",
            source_url="https://boards.greenhouse.io/acme/jobs/1",
            external_id="1",
            internal_job_id="req-1",
            source_updated_at=datetime(2026, 1, 2, tzinfo=UTC),
            departments=["Engineering"],
            offices=["Remote"],
            metadata={"employment_type": "Full-time"},
            raw_payload={"id": "1"},
        ),
        NormalizedJobPosting(
            provider=JobSourceProvider.GREENHOUSE,
            company_name="Acme",
            title="Director, Platform Engineering",
            location_text="Remote",
            workplace_type=WorkplaceType.HYBRID,
            description_raw="Lead platform engineering with Kubernetes and cloud reliability.",
            description_normalized=(
                "Lead platform engineering with Kubernetes and cloud reliability."
            ),
            compensation_text="$200k - $250k",
            source_url="https://boards.greenhouse.io/acme/jobs/1",
            external_id="1",
            internal_job_id="req-1",
            source_updated_at=datetime(2026, 1, 2, tzinfo=UTC),
            departments=["Engineering"],
            offices=["Remote"],
            metadata={"employment_type": "Full-time"},
            raw_payload={"id": "1"},
        ),
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
            compensation_text="$225k - $275k",
            source_url="https://boards.greenhouse.io/acme/jobs/1",
            external_id="1",
            internal_job_id="req-1",
            source_updated_at=datetime(2026, 1, 2, tzinfo=UTC),
            departments=["Engineering"],
            offices=["Remote"],
            metadata={"employment_type": "Full-time"},
            raw_payload={"id": "1"},
        ),
    ],
)
def test_scoring_relevant_change_creates_new_evaluation(
    session_factory: sessionmaker[Session],
    updated_posting: NormalizedJobPosting,
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        source_id = _create_source(session)
        baseline = _posting("1")
        run_job_source_import(
            session,
            source_id=source_id,
            connector=FakeJobSourceConnector(jobs=[baseline]),
        )

        run = run_job_source_import(
            session,
            source_id=source_id,
            connector=FakeJobSourceConnector(jobs=[updated_posting]),
        )

        assert run.jobs_updated == 1
        assert run.evaluations_created == 1
        assert len(list(session.scalars(select(JobEvaluationModel)))) == 2


@pytest.mark.parametrize(
    "posting_status",
    [PostingStatus.REVIEWING, PostingStatus.PURSUING, PostingStatus.REJECTED],
)
def test_closure_and_reactivation_preserve_human_workflow_status(
    session_factory: sessionmaker[Session],
    posting_status: PostingStatus,
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        source_id = _create_source(session)
        run_job_source_import(
            session,
            source_id=source_id,
            connector=FakeJobSourceConnector(jobs=[_posting("1"), _posting("2")]),
        )
        job = session.scalar(select(JobLeadModel).where(JobLeadModel.external_id.endswith(":2")))
        assert job is not None
        if posting_status is PostingStatus.PURSUING:
            update_job_lead_status(session, job.id, PostingStatus.REVIEWING.value)
        update_job_lead_status(session, job.id, posting_status.value)

        close_run = run_job_source_import(
            session,
            source_id=source_id,
            connector=FakeJobSourceConnector(jobs=[_posting("1")]),
        )
        session.refresh(job)
        assert close_run.status == JobImportRunStatus.SUCCEEDED.value
        assert job.source_posting_status == SourcePostingStatus.CLOSED.value
        assert job.posting_status == posting_status.value

        reactivate_run = run_job_source_import(
            session,
            source_id=source_id,
            connector=FakeJobSourceConnector(jobs=[_posting("1"), _posting("2")]),
        )
        session.refresh(job)
        assert reactivate_run.status == JobImportRunStatus.SUCCEEDED.value
        assert job.source_posting_status == SourcePostingStatus.OPEN.value
        assert job.posting_status == posting_status.value


def test_same_external_id_on_different_boards_creates_distinct_observations(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        first_source_id = _create_source(session)
        second_source = create_job_source_configuration(
            session,
            provider=JobSourceProvider.GREENHOUSE.value,
            display_name="Acme Europe",
            company_name="Acme",
            board_token="acme-eu",
            source_url="https://boards.greenhouse.io/acme-eu",
        )

        run_job_source_import(
            session,
            source_id=first_source_id,
            connector=FakeJobSourceConnector(jobs=[_posting("shared")]),
        )
        run_job_source_import(
            session,
            source_id=second_source.id,
            connector=FakeJobSourceConnector(jobs=[_posting("shared")]),
        )

        assert len(list(session.scalars(select(JobSourceObservationModel)))) == 2
        assert len(list(session.scalars(select(JobLeadModel)))) == 2


def test_concurrent_same_source_import_rejected(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        source_id = _create_source(session)
        session.add(
            JobImportRunModel(
                id=UUID("00000000-0000-0000-0000-000000000099"),
                source_configuration_id=source_id,
                provider=JobSourceProvider.GREENHOUSE.value,
                status=JobImportRunStatus.RUNNING.value,
                connector_version="fake",
            )
        )
        session.commit()

        with pytest.raises(OverlappingJobImportError):
            run_job_source_import(
                session,
                source_id=source_id,
                connector=FakeJobSourceConnector(jobs=[_posting("1")]),
            )


def _active_observations(session: Session) -> int:
    return len(
        list(
            session.scalars(
                select(JobSourceObservationModel).where(JobSourceObservationModel.active.is_(True))
            )
        )
    )
