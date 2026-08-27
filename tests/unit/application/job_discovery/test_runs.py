from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ai_job_finder.application.job_discovery import (
    JobDiscoveryConfig,
    get_job_discovery_run_detail,
    list_job_discovery_observations,
    run_job_discovery,
)
from ai_job_finder.application.job_discovery.query_generation import generate_job_discovery_queries
from ai_job_finder.application.job_searches import (
    create_job_search_definition,
    get_job_search_definition,
)
from ai_job_finder.application.job_sources import create_job_source_configuration
from ai_job_finder.application.services import (
    create_candidate_profile,
    create_career_fact,
    transition_career_fact,
)
from ai_job_finder.application.source_detection import SourceDetectionConfig
from ai_job_finder.domain.common import new_uuid, utc_now
from ai_job_finder.domain.enums import (
    CareerFactCategory,
    CareerFactLifecycle,
    EvidenceTag,
    JobSourceProvider,
    ProvenanceType,
    RemotePreference,
    WorkplaceType,
)
from ai_job_finder.domain.errors import (
    JobSearchDefinitionDisabledError,
    JobSourceProviderError,
    OverlappingJobDiscoveryRunError,
)
from ai_job_finder.domain.job_discovery import (
    DiscoveredJobCandidate,
    JobDiscoveryObservationStatus,
)
from ai_job_finder.domain.job_sources import JobSourceFetchResult, NormalizedJobPosting
from ai_job_finder.domain.source_detection import (
    AshbyBoardValidation,
    GreenhouseBoardValidation,
    PublicPage,
)
from ai_job_finder.infrastructure.database.base import Base
from ai_job_finder.infrastructure.database.models import (
    JobDiscoveryRunModel,
    JobEvaluationModel,
    JobLeadModel,
    JobSearchMatchModel,
    JobSourceConfigurationModel,
)
from ai_job_finder.infrastructure.database.session import create_engine_from_url
from ai_job_finder.infrastructure.job_discovery.fake import FakeJobDiscoveryProvider
from ai_job_finder.infrastructure.job_sources.fake import FakeJobSourceConnector


class FakeFetcher:
    def __init__(self, pages: dict[str, PublicPage]) -> None:
        self.pages = pages

    def fetch(self, url: str) -> PublicPage:
        return self.pages[url]


class CountingFetcher(FakeFetcher):
    def __init__(self, pages: dict[str, PublicPage]) -> None:
        super().__init__(pages)
        self.calls: list[str] = []

    def fetch(self, url: str) -> PublicPage:
        self.calls.append(url)
        return super().fetch(url)


class FakeValidator:
    def __init__(self, validation_by_token: dict[str, GreenhouseBoardValidation]) -> None:
        self.validation_by_token = validation_by_token

    def validate_board_token(self, board_token: str) -> GreenhouseBoardValidation:
        return self.validation_by_token.get(
            board_token, GreenhouseBoardValidation(token=board_token, status="invalid", valid=False)
        )


class FakeAshbyValidator:
    def validate_board_token(self, board_token: str) -> AshbyBoardValidation:
        return AshbyBoardValidation(
            token=board_token,
            status="valid",
            valid=True,
            job_count=2,
            sample_titles=["Director, Platform Engineering"],
            company_name="Beta",
        )


class BoardAwareConnector:
    def __init__(
        self,
        *,
        jobs_by_token: dict[str, list[NormalizedJobPosting]],
        errors_by_token: dict[str, Exception] | None = None,
    ) -> None:
        self.jobs_by_token = jobs_by_token
        self.errors_by_token = errors_by_token or {}
        self.fetch_calls: list[str] = []

    def fetch_jobs(self, source: object) -> JobSourceFetchResult:
        board_token = str(cast(Any, source).board_token)
        self.fetch_calls.append(board_token)
        error = self.errors_by_token.get(board_token)
        if error is not None:
            raise error
        return JobSourceFetchResult(
            jobs=list(self.jobs_by_token.get(board_token, [])),
            fetched_at=utc_now(),
            connector_version="board-aware-fake",
        )

    def validate_board_token(self, board_token: str) -> GreenhouseBoardValidation:
        token = board_token.strip().lower()
        jobs = self.jobs_by_token.get(token)
        if jobs is None and token not in self.errors_by_token:
            return GreenhouseBoardValidation(token=token, status="invalid", valid=False)
        company_name = jobs[0].company_name if jobs else token
        sample_titles = [job.title for job in (jobs or [])[:5]]
        return GreenhouseBoardValidation(
            token=token,
            status="valid_empty" if not jobs else "valid",
            valid=True,
            job_count=len(jobs or []),
            sample_titles=sample_titles,
            company_name=company_name,
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


def _seed_candidate(session: Session) -> None:
    candidate = create_candidate_profile(
        session,
        full_name="Jordan Lee",
        preferred_locations=["Remote"],
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
        statement="Built a developer platform.",
        metric="40% faster delivery",
        technologies=["Python", "Kubernetes"],
        leadership_scope="30 engineers",
        business_outcome="Faster delivery",
        approved_wording="Built a developer platform with measurable impact.",
        evidence_tags=[
            EvidenceTag.PLATFORM_ENGINEERING.value,
            EvidenceTag.CLOUD.value,
            EvidenceTag.DEVELOPER_EXPERIENCE.value,
        ],
        provenance_type=ProvenanceType.PROJECT_NOTES.value,
        source_reference="packet",
    )
    transition_career_fact(
        session,
        fact_id=fact.id,
        lifecycle_status=CareerFactLifecycle.VERIFIED.value,
    )


def _search(session: Session) -> UUID:
    return create_job_search_definition(
        session,
        name="Platform roles",
        title_include_patterns=["Director Platform Engineering"],
        title_exclude_patterns=["finance"],
        target_domains=["platform_engineering"],
        target_seniority_levels=["director"],
        allowed_locations=[],
        allowed_remote_geographies=["United States"],
        allowed_workplace_types=["remote"],
        minimum_score_threshold=70,
    ).id


def _page(url: str) -> PublicPage:
    return PublicPage(
        requested_url=url,
        final_url=url,
        content_type="text/html",
        text="https://boards-api.greenhouse.io/v1/boards/acme/jobs",
    )


def _page_for_token(url: str, token: str) -> PublicPage:
    return PublicPage(
        requested_url=url,
        final_url=url,
        content_type="text/html",
        text=f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
    )


def _posting(external_id: str, title: str) -> NormalizedJobPosting:
    return NormalizedJobPosting(
        provider=JobSourceProvider.GREENHOUSE,
        company_name="Acme",
        title=title,
        location_text="Remote United States",
        workplace_type=WorkplaceType.REMOTE,
        description_raw="Lead platform engineering with Kubernetes and cloud reliability.",
        description_normalized="Lead platform engineering with Kubernetes and cloud reliability.",
        compensation_text="$200k",
        source_url=f"https://boards.greenhouse.io/acme/jobs/{external_id}",
        external_id=external_id,
        internal_job_id=f"req-{external_id}",
        source_updated_at=datetime(2026, 1, 2, tzinfo=UTC),
        departments=["Engineering"],
        offices=["Remote"],
        metadata={},
        raw_payload={"id": external_id},
    )


def _posting_for_board(
    board_token: str,
    company_name: str,
    external_id: str,
    title: str,
) -> NormalizedJobPosting:
    return NormalizedJobPosting(
        provider=JobSourceProvider.GREENHOUSE,
        company_name=company_name,
        title=title,
        location_text="Remote United States",
        workplace_type=WorkplaceType.REMOTE,
        description_raw="Lead platform engineering with Kubernetes and cloud reliability.",
        description_normalized="Lead platform engineering with Kubernetes and cloud reliability.",
        compensation_text="$200k",
        source_url=f"https://boards.greenhouse.io/{board_token}/jobs/{external_id}",
        external_id=external_id,
        internal_job_id=f"req-{external_id}",
        source_updated_at=datetime(2026, 1, 2, tzinfo=UTC),
        departments=["Engineering"],
        offices=["Remote"],
        metadata={},
        raw_payload={"id": external_id},
    )


def _ashby_posting(external_id: str, title: str) -> NormalizedJobPosting:
    return NormalizedJobPosting(
        provider=JobSourceProvider.ASHBY,
        company_name="Beta",
        title=title,
        location_text="Remote United States",
        workplace_type=WorkplaceType.REMOTE,
        description_raw="Lead platform engineering with Kubernetes and cloud reliability.",
        description_normalized="Lead platform engineering with Kubernetes and cloud reliability.",
        compensation_text=None,
        source_url=f"https://jobs.ashbyhq.com/Beta/{external_id}",
        external_id=external_id,
        internal_job_id=None,
        source_updated_at=datetime(2026, 1, 2, tzinfo=UTC),
        departments=["Engineering"],
        offices=["Remote United States"],
        metadata={},
        raw_payload={"id": external_id},
    )


def _config() -> JobDiscoveryConfig:
    return JobDiscoveryConfig(
        max_queries_per_run=4,
        result_limit=5,
        max_total_candidates=5,
        source_detection=SourceDetectionConfig(
            max_linked_scripts=2,
            max_script_bytes=100_000,
            total_script_bytes=200_000,
        ),
        retain_raw_payload=True,
        close_on_empty=False,
        stale_after_seconds=3600,
    )


def test_run_job_discovery_forwards_configured_query_cap_to_generator(
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_max_queries: list[int] = []
    original_generate = generate_job_discovery_queries

    def capture_generate(*args: Any, **kwargs: Any) -> list[Any]:
        captured_max_queries.append(cast(int, kwargs["max_queries"]))
        return original_generate(*args, **kwargs)

    monkeypatch.setattr(
        "ai_job_finder.application.job_discovery.runs.generate_job_discovery_queries",
        capture_generate,
    )

    with session_factory() as session:
        _seed_candidate(session)
        search_id = _search(session)
        run_job_discovery(
            session,
            search_definition_id=search_id,
            provider_name="fake",
            provider=FakeJobDiscoveryProvider(),
            fetcher=FakeFetcher({}),
            validator=FakeJobSourceConnector(),
            connector=FakeJobSourceConnector(),
            config=replace(_config(), max_queries_per_run=12),
        )

    assert captured_max_queries == [12]


def test_run_job_discovery_completes_and_links_saved_search_matches(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        search_id = _search(session)
        create_job_source_configuration(
            session,
            provider=JobSourceProvider.GREENHOUSE.value,
            display_name="Acme Greenhouse",
            company_name="Acme",
            board_token="acme",
            source_url="https://boards.greenhouse.io/acme",
        )
        search = get_job_search_definition(session, search_id)
        queries = generate_job_discovery_queries(
            search.to_snapshot(), max_queries=4, result_limit=5
        )
        url_one = "https://boards.greenhouse.io/acme/jobs/strong"
        url_two = "https://boards.greenhouse.io/acme/jobs/weak"
        provider = FakeJobDiscoveryProvider(
            results_by_query={
                queries[0].rendered_query: [
                    DiscoveredJobCandidate(
                        discovered_url=url_one,
                        provider_name="fake",
                        query_identifier=queries[0].stable_query_id,
                        rank=1,
                        title_hint="Director, Platform Engineering",
                        company_hint="Acme",
                        location_hint="Remote United States",
                    ),
                    DiscoveredJobCandidate(
                        discovered_url=url_one,
                        provider_name="fake",
                        query_identifier=queries[0].stable_query_id,
                        rank=2,
                        title_hint="Director, Platform Engineering",
                        company_hint="Acme",
                        location_hint="Remote United States",
                    ),
                ],
                queries[1].rendered_query: [
                    DiscoveredJobCandidate(
                        discovered_url=url_two,
                        provider_name="fake",
                        query_identifier=queries[1].stable_query_id,
                        rank=1,
                        title_hint="Finance Operations Manager",
                        company_hint="Acme",
                        location_hint="Remote United States",
                    )
                ],
            }
        )
        connector = FakeJobSourceConnector(
            jobs=[
                _posting("strong", "Director, Platform Engineering"),
                _posting("weak", "Finance Operations Manager"),
            ],
            valid_tokens={"acme"},
        )

        run = run_job_discovery(
            session,
            search_definition_id=search_id,
            provider_name="fake",
            provider=provider,
            fetcher=FakeFetcher({url_one: _page(url_one), url_two: _page(url_two)}),
            validator=connector,
            connector=connector,
            config=_config(),
        )

        observations = list_job_discovery_observations(session, discovery_run_id=run.id)

        assert run.status == "completed"
        assert run.provider_result_count == 3
        assert run.unique_url_count == 2
        assert run.duplicate_count == 1
        assert run.detected_count == 2
        assert run.imported_lead_count == 2
        assert run.final_matched_count == 1
        assert run.saved_search_run_id is not None
        assert len(observations) == 2
        assert (
            sum(
                1
                for record in observations
                if record.saved_search_match and record.saved_search_match.matched
            )
            == 1
        )
        assert len(list(session.scalars(select(JobSourceConfigurationModel)))) == 1


def test_run_job_discovery_marks_partial_on_query_failure(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        search_id = _search(session)
        create_job_source_configuration(
            session,
            provider=JobSourceProvider.GREENHOUSE.value,
            display_name="Acme Greenhouse",
            company_name="Acme",
            board_token="acme",
            source_url="https://boards.greenhouse.io/acme",
        )
        search = get_job_search_definition(session, search_id)
        queries = generate_job_discovery_queries(
            search.to_snapshot(), max_queries=4, result_limit=5
        )
        url_one = "https://boards.greenhouse.io/acme/jobs/strong"
        provider = FakeJobDiscoveryProvider(
            results_by_query={
                queries[1].rendered_query: [
                    DiscoveredJobCandidate(
                        discovered_url=url_one,
                        provider_name="fake",
                        query_identifier=queries[1].stable_query_id,
                        rank=1,
                        title_hint="Director, Platform Engineering",
                        company_hint="Acme",
                    )
                ]
            },
            error_by_query={queries[0].rendered_query: RuntimeError("provider unavailable")},
        )
        connector = FakeJobSourceConnector(
            jobs=[_posting("strong", "Director, Platform Engineering")],
            valid_tokens={"acme"},
        )

        run = run_job_discovery(
            session,
            search_definition_id=search_id,
            provider_name="fake",
            provider=provider,
            fetcher=FakeFetcher({url_one: _page(url_one)}),
            validator=connector,
            connector=connector,
            config=_config(),
        )

        assert run.status == "partial"
        assert run.failure_count >= 1
        assert "provider unavailable" in (run.error_summary or "")


def test_run_job_discovery_rejects_disabled_saved_search(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        search = create_job_search_definition(
            session,
            name="Disabled search",
            title_include_patterns=["Director Platform Engineering"],
            title_exclude_patterns=[],
            target_domains=[],
            target_seniority_levels=[],
            allowed_locations=[],
            allowed_remote_geographies=[],
            allowed_workplace_types=[],
            minimum_score_threshold=70,
            enabled=False,
        )

        with pytest.raises(JobSearchDefinitionDisabledError):
            run_job_discovery(
                session,
                search_definition_id=search.id,
                provider_name="fake",
                provider=FakeJobDiscoveryProvider(),
                fetcher=FakeFetcher({}),
                validator=FakeValidator({}),
                connector=FakeJobSourceConnector(),
                config=_config(),
            )


def test_run_job_discovery_rejects_conflicting_active_run(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        search_id = _search(session)
        session.add(
            JobDiscoveryRunModel(
                id=new_uuid(),
                search_definition_id=search_id,
                provider="fake",
                status="running",
                started_at=utc_now(),
            )
        )
        session.commit()

        with pytest.raises(OverlappingJobDiscoveryRunError):
            run_job_discovery(
                session,
                search_definition_id=search_id,
                provider_name="fake",
                provider=FakeJobDiscoveryProvider(),
                fetcher=FakeFetcher({}),
                validator=FakeValidator({}),
                connector=FakeJobSourceConnector(),
                config=_config(),
            )


def test_run_job_discovery_auto_creates_unknown_greenhouse_source_and_retains_weak_jobs(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        search_id = _search(session)
        search = get_job_search_definition(session, search_id)
        queries = generate_job_discovery_queries(
            search.to_snapshot(), max_queries=4, result_limit=5
        )
        strong_url = "https://boards.greenhouse.io/beta/jobs/strong"
        weak_url = "https://boards.greenhouse.io/beta/jobs/weak"
        provider = FakeJobDiscoveryProvider(
            results_by_query={
                queries[0].rendered_query: [
                    DiscoveredJobCandidate(
                        discovered_url=strong_url,
                        provider_name="fake",
                        query_identifier=queries[0].stable_query_id,
                        rank=1,
                        title_hint="Director, Platform Engineering",
                        company_hint="Beta",
                    ),
                    DiscoveredJobCandidate(
                        discovered_url=weak_url,
                        provider_name="fake",
                        query_identifier=queries[0].stable_query_id,
                        rank=2,
                        title_hint="Finance Operations Manager",
                        company_hint="Beta",
                    ),
                ]
            }
        )
        connector = BoardAwareConnector(
            jobs_by_token={
                "beta": [
                    _posting_for_board("beta", "Beta", "strong", "Director, Platform Engineering"),
                    _posting_for_board("beta", "Beta", "weak", "Finance Operations Manager"),
                ]
            }
        )

        run = run_job_discovery(
            session,
            search_definition_id=search_id,
            provider_name="fake",
            provider=provider,
            fetcher=FakeFetcher(
                {
                    strong_url: _page_for_token(strong_url, "beta"),
                    weak_url: _page_for_token(weak_url, "beta"),
                }
            ),
            validator=connector,
            connector=connector,
            config=_config(),
        )

        sources = list(session.scalars(select(JobSourceConfigurationModel)))
        jobs = list(session.scalars(select(JobLeadModel).order_by(JobLeadModel.external_id.asc())))
        evaluations = list(session.scalars(select(JobEvaluationModel)))
        matches = list(
            session.scalars(
                select(JobSearchMatchModel).where(
                    JobSearchMatchModel.search_run_id == run.saved_search_run_id
                )
            )
        )

        assert run.status == "completed"
        assert len(sources) == 1
        assert sources[0].board_token == "beta"
        assert sources[0].enabled is True
        assert len(jobs) == 2
        assert len(evaluations) == 2
        assert len(matches) == 2
        assert sum(1 for match in matches if match.matched) == 1
        assert any(job.title == "Finance Operations Manager" for job in jobs)


def test_run_job_discovery_imports_same_board_once_per_run(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        search_id = _search(session)
        search = get_job_search_definition(session, search_id)
        queries = generate_job_discovery_queries(
            search.to_snapshot(), max_queries=4, result_limit=5
        )
        first_url = "https://boards.greenhouse.io/beta/jobs/111"
        second_url = "https://boards.greenhouse.io/beta/jobs/222"
        third_url = "https://boards.greenhouse.io/beta/jobs/333"
        provider = FakeJobDiscoveryProvider(
            results_by_query={
                queries[0].rendered_query: [
                    DiscoveredJobCandidate(
                        discovered_url=first_url,
                        provider_name="fake",
                        query_identifier=queries[0].stable_query_id,
                        rank=1,
                        title_hint="Director, Platform Engineering",
                        company_hint="Beta",
                    ),
                    DiscoveredJobCandidate(
                        discovered_url=second_url,
                        provider_name="fake",
                        query_identifier=queries[0].stable_query_id,
                        rank=2,
                        title_hint="Principal Platform Architect",
                        company_hint="Beta",
                    ),
                    DiscoveredJobCandidate(
                        discovered_url=third_url,
                        provider_name="fake",
                        query_identifier=queries[0].stable_query_id,
                        rank=3,
                        title_hint="Staff Platform Engineering Manager",
                        company_hint="Beta",
                    ),
                ]
            }
        )
        connector = BoardAwareConnector(
            jobs_by_token={
                "beta": [
                    _posting_for_board("beta", "Beta", "111", "Director, Platform Engineering"),
                    _posting_for_board("beta", "Beta", "222", "Principal Platform Architect"),
                    _posting_for_board(
                        "beta",
                        "Beta",
                        "333",
                        "Staff Platform Engineering Manager",
                    ),
                ]
            }
        )

        run = run_job_discovery(
            session,
            search_definition_id=search_id,
            provider_name="fake",
            provider=provider,
            fetcher=FakeFetcher(
                {
                    first_url: _page_for_token(first_url, "beta"),
                    second_url: _page_for_token(second_url, "beta"),
                    third_url: _page_for_token(third_url, "beta"),
                }
            ),
            validator=connector,
            connector=connector,
            config=_config(),
        )
        observations = list_job_discovery_observations(session, discovery_run_id=run.id)

        assert run.status == "completed"
        assert connector.fetch_calls == ["beta"]
        assert len(list(session.scalars(select(JobSourceConfigurationModel)))) == 1
        leads = list(session.scalars(select(JobLeadModel).order_by(JobLeadModel.external_id.asc())))
        assert len(leads) == 3
        external_ids = [lead.external_id for lead in leads]
        assert all(external_id is not None for external_id in external_ids)
        assert sorted(
            external_id.split(":")[-1] for external_id in external_ids if external_id is not None
        ) == ["111", "222", "333"]
        assert len(observations) == 3
        assert {record.observation.processing_status for record in observations} == {
            JobDiscoveryObservationStatus.IMPORTED.value
        }
        assert all(record.observation.imported_job_lead_id is not None for record in observations)
        assert len({record.observation.imported_job_lead_id for record in observations}) == 3


def test_run_job_discovery_imports_and_links_ashby_board_once(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        search_id = _search(session)
        search = get_job_search_definition(session, search_id)
        query = generate_job_discovery_queries(search.to_snapshot(), max_queries=4, result_limit=5)[
            0
        ]
        first_url = "https://jobs.ashbyhq.com/Beta/posting-111"
        second_url = "https://jobs.ashbyhq.com/Beta/posting-222"
        provider = FakeJobDiscoveryProvider(
            results_by_query={
                query.rendered_query: [
                    DiscoveredJobCandidate(
                        discovered_url=first_url,
                        provider_name="fake",
                        query_identifier=query.stable_query_id,
                        rank=1,
                        title_hint="Director, Platform Engineering",
                        company_hint="Beta",
                    ),
                    DiscoveredJobCandidate(
                        discovered_url=second_url,
                        provider_name="fake",
                        query_identifier=query.stable_query_id,
                        rank=2,
                        title_hint="Principal Platform Architect",
                        company_hint="Beta",
                    ),
                ]
            }
        )
        connector = BoardAwareConnector(
            jobs_by_token={
                "Beta": [
                    _ashby_posting("posting-111", "Director, Platform Engineering"),
                    _ashby_posting("posting-222", "Principal Platform Architect"),
                ]
            }
        )

        run = run_job_discovery(
            session,
            search_definition_id=search_id,
            provider_name="fake",
            provider=provider,
            fetcher=FakeFetcher({}),
            validator=FakeValidator({}),
            ashby_validator=FakeAshbyValidator(),
            connector=connector,
            config=_config(),
        )
        observations = list_job_discovery_observations(session, discovery_run_id=run.id)

        assert run.status == "completed"
        assert connector.fetch_calls == ["Beta"]
        assert len(observations) == 2
        assert all(record.observation.imported_job_lead_id is not None for record in observations)
        source = session.scalar(select(JobSourceConfigurationModel))
        assert source is not None
        assert source.provider == JobSourceProvider.ASHBY.value
        assert source.board_token == "Beta"


def test_run_job_discovery_reuses_prior_resolution_and_avoids_duplicate_sources_and_jobs(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        search_id = _search(session)
        search = get_job_search_definition(session, search_id)
        queries = generate_job_discovery_queries(
            search.to_snapshot(), max_queries=4, result_limit=5
        )
        job_url = "https://boards.greenhouse.io/beta/jobs/strong"
        provider = FakeJobDiscoveryProvider(
            results_by_query={
                queries[0].rendered_query: [
                    DiscoveredJobCandidate(
                        discovered_url=job_url,
                        provider_name="fake",
                        query_identifier=queries[0].stable_query_id,
                        rank=1,
                        title_hint="Director, Platform Engineering",
                        company_hint="Beta",
                    )
                ]
            }
        )
        connector = BoardAwareConnector(
            jobs_by_token={
                "beta": [
                    _posting_for_board("beta", "Beta", "strong", "Director, Platform Engineering")
                ]
            }
        )

        first_fetcher = CountingFetcher({job_url: _page_for_token(job_url, "beta")})
        first_run = run_job_discovery(
            session,
            search_definition_id=search_id,
            provider_name="fake",
            provider=provider,
            fetcher=first_fetcher,
            validator=connector,
            connector=connector,
            config=_config(),
        )
        second_fetcher = CountingFetcher({})
        second_run = run_job_discovery(
            session,
            search_definition_id=search_id,
            provider_name="fake",
            provider=provider,
            fetcher=second_fetcher,
            validator=connector,
            connector=connector,
            config=_config(),
        )

        assert first_run.status == "completed"
        assert second_run.status == "completed"
        assert first_fetcher.calls == [job_url]
        assert second_fetcher.calls == []
        assert len(list(session.scalars(select(JobSourceConfigurationModel)))) == 1
        assert len(list(session.scalars(select(JobLeadModel)))) == 1


def test_get_job_discovery_run_detail_marks_previously_seen_urls_and_reused_sources(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        search_id = _search(session)
        search = get_job_search_definition(session, search_id)
        queries = generate_job_discovery_queries(
            search.to_snapshot(), max_queries=4, result_limit=5
        )
        job_url = "https://boards.greenhouse.io/beta/jobs/strong"
        provider = FakeJobDiscoveryProvider(
            results_by_query={
                queries[0].rendered_query: [
                    DiscoveredJobCandidate(
                        discovered_url=job_url,
                        provider_name="fake",
                        query_identifier=queries[0].stable_query_id,
                        rank=1,
                        title_hint="Director, Platform Engineering",
                        company_hint="Beta",
                    )
                ]
            }
        )
        connector = BoardAwareConnector(
            jobs_by_token={
                "beta": [
                    _posting_for_board(
                        "beta",
                        "Beta",
                        "strong",
                        "Director, Platform Engineering",
                    )
                ]
            }
        )

        first_run = run_job_discovery(
            session,
            search_definition_id=search_id,
            provider_name="fake",
            provider=provider,
            fetcher=CountingFetcher({job_url: _page_for_token(job_url, "beta")}),
            validator=connector,
            connector=connector,
            config=_config(),
        )
        second_run = run_job_discovery(
            session,
            search_definition_id=search_id,
            provider_name="fake",
            provider=provider,
            fetcher=CountingFetcher({}),
            validator=connector,
            connector=connector,
            config=_config(),
        )

        assert first_run.status == "completed"
        detail = get_job_discovery_run_detail(session, second_run.id)

        assert len(detail.observations) == 1
        assert detail.observations[0].previously_seen is True
        assert detail.observations[0].reused_prior_resolution is True
        assert detail.observations[0].source_created_in_run is False
        assert len(detail.imports) == 1
        assert detail.imports[0].source_created_in_run is False
        assert detail.imports[0].import_run is not None
        assert detail.imports[0].import_run.jobs_unchanged == 1
        assert detail.matching_summary.saved_search_match_count == 1
        assert detail.matching_summary.surfaced_in_discover_count == 1
        assert detail.top_matches[0].surfaced_in_discover is True


def test_get_job_discovery_run_detail_distinguishes_ambiguous_unsupported_and_failed_imports(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        search_id = _search(session)
        search = get_job_search_definition(session, search_id)
        queries = generate_job_discovery_queries(
            search.to_snapshot(), max_queries=4, result_limit=5
        )
        beta_first_url = "https://boards.greenhouse.io/beta/jobs/111"
        beta_second_url = "https://boards.greenhouse.io/beta/jobs/222"
        ambiguous_url = "https://example.com/ambiguous"
        unsupported_url = "https://example.com/unsupported"
        failed_url = "https://boards.greenhouse.io/gamma/jobs/fail"
        provider = FakeJobDiscoveryProvider(
            results_by_query={
                queries[0].rendered_query: [
                    DiscoveredJobCandidate(
                        discovered_url=beta_first_url,
                        provider_name="fake",
                        query_identifier=queries[0].stable_query_id,
                        rank=1,
                        title_hint="Director, Platform Engineering",
                        company_hint="Beta",
                    ),
                    DiscoveredJobCandidate(
                        discovered_url=beta_second_url,
                        provider_name="fake",
                        query_identifier=queries[0].stable_query_id,
                        rank=2,
                        title_hint="Principal Platform Architect",
                        company_hint="Beta",
                    ),
                    DiscoveredJobCandidate(
                        discovered_url=ambiguous_url,
                        provider_name="fake",
                        query_identifier=queries[0].stable_query_id,
                        rank=3,
                    ),
                    DiscoveredJobCandidate(
                        discovered_url=unsupported_url,
                        provider_name="fake",
                        query_identifier=queries[0].stable_query_id,
                        rank=4,
                    ),
                    DiscoveredJobCandidate(
                        discovered_url=failed_url,
                        provider_name="fake",
                        query_identifier=queries[0].stable_query_id,
                        rank=5,
                        title_hint="Director, Platform Engineering",
                        company_hint="Gamma",
                    ),
                ]
            }
        )
        connector = BoardAwareConnector(
            jobs_by_token={
                "beta": [
                    _posting_for_board("beta", "Beta", "111", "Director, Platform Engineering"),
                    _posting_for_board("beta", "Beta", "222", "Principal Platform Architect"),
                ],
                "gamma": [],
            },
            errors_by_token={"gamma": JobSourceProviderError("provider unavailable")},
        )
        validator = FakeValidator(
            {
                "acme": GreenhouseBoardValidation(token="acme", status="valid", valid=True),
                "beta": GreenhouseBoardValidation(token="beta", status="valid", valid=True),
                "gamma": GreenhouseBoardValidation(token="gamma", status="valid", valid=True),
            }
        )

        detail_run = run_job_discovery(
            session,
            search_definition_id=search_id,
            provider_name="fake",
            provider=provider,
            fetcher=FakeFetcher(
                {
                    beta_first_url: _page_for_token(beta_first_url, "beta"),
                    beta_second_url: _page_for_token(beta_second_url, "beta"),
                    ambiguous_url: PublicPage(
                        requested_url=ambiguous_url,
                        final_url=ambiguous_url,
                        content_type="text/html",
                        text=(
                            '<a href="https://boards.greenhouse.io/acme">A</a>'
                            '<a href="https://job-boards.greenhouse.io/beta">B</a>'
                        ),
                    ),
                    unsupported_url: PublicPage(
                        requested_url=unsupported_url,
                        final_url=unsupported_url,
                        content_type="text/html",
                        text="https://example.com/jobs/1",
                    ),
                    failed_url: _page_for_token(failed_url, "gamma"),
                }
            ),
            validator=validator,
            connector=connector,
            config=_config(),
        )
        detail = get_job_discovery_run_detail(session, detail_run.id)

        observations_by_url = {
            record.observation.normalized_url: record for record in detail.observations
        }

        assert detail_run.status == "partial"
        assert observations_by_url[beta_second_url].source_reused_in_run is True
        assert (
            observations_by_url[ambiguous_url].observation.processing_status
            == JobDiscoveryObservationStatus.AMBIGUOUS.value
        )
        assert (
            observations_by_url[unsupported_url].observation.processing_status
            == JobDiscoveryObservationStatus.UNSUPPORTED.value
        )
        assert (
            observations_by_url[failed_url].observation.processing_status
            == JobDiscoveryObservationStatus.FAILED.value
        )

        imports_by_token = {
            record.source_configuration.board_token: record for record in detail.imports
        }
        assert imports_by_token["beta"].source_reused_in_run is True
        assert imports_by_token["beta"].import_run is not None
        assert imports_by_token["beta"].import_run.jobs_created == 2
        assert imports_by_token["gamma"].import_status == "failed"
        assert "provider unavailable" in (imports_by_token["gamma"].failure_message or "")

        assert detail.matching_summary.canonical_jobs_evaluated == 2
        assert detail.matching_summary.saved_search_match_count == 1
        assert detail.top_matches[0].job_lead.title == "Director, Platform Engineering"
        assert detail.top_matches[0].evaluation is not None
        assert detail.discover_jobs[0].job_lead.title == "Director, Platform Engineering"


def test_run_job_discovery_does_not_auto_promote_ambiguous_or_unsupported_sources(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        search_id = _search(session)
        search = get_job_search_definition(session, search_id)
        queries = generate_job_discovery_queries(
            search.to_snapshot(), max_queries=4, result_limit=5
        )
        ambiguous_url = "https://example.com/ambiguous"
        unsupported_url = "https://example.com/unsupported"
        provider = FakeJobDiscoveryProvider(
            results_by_query={
                queries[0].rendered_query: [
                    DiscoveredJobCandidate(
                        discovered_url=ambiguous_url,
                        provider_name="fake",
                        query_identifier=queries[0].stable_query_id,
                        rank=1,
                    ),
                    DiscoveredJobCandidate(
                        discovered_url=unsupported_url,
                        provider_name="fake",
                        query_identifier=queries[0].stable_query_id,
                        rank=2,
                    ),
                ]
            }
        )
        fetcher = FakeFetcher(
            {
                ambiguous_url: PublicPage(
                    requested_url=ambiguous_url,
                    final_url=ambiguous_url,
                    content_type="text/html",
                    text=(
                        '<a href="https://boards.greenhouse.io/acme">A</a>'
                        '<a href="https://job-boards.greenhouse.io/beta">B</a>'
                    ),
                ),
                unsupported_url: PublicPage(
                    requested_url=unsupported_url,
                    final_url=unsupported_url,
                    content_type="text/html",
                    text="https://example.com/jobs/1",
                ),
            }
        )
        validator = FakeValidator(
            {
                "acme": GreenhouseBoardValidation(token="acme", status="valid", valid=True),
                "beta": GreenhouseBoardValidation(token="beta", status="valid", valid=True),
            }
        )

        run = run_job_discovery(
            session,
            search_definition_id=search_id,
            provider_name="fake",
            provider=provider,
            fetcher=fetcher,
            validator=validator,
            connector=FakeJobSourceConnector(),
            config=_config(),
        )
        observations = list_job_discovery_observations(session, discovery_run_id=run.id)

        assert run.status == "completed"
        assert len(list(session.scalars(select(JobSourceConfigurationModel)))) == 0
        assert {record.observation.processing_status for record in observations} == {
            JobDiscoveryObservationStatus.AMBIGUOUS.value,
            JobDiscoveryObservationStatus.UNSUPPORTED.value,
        }


@pytest.mark.parametrize(
    ("url", "expected_domain"),
    [
        ("https://www.indeed.com/viewjob?jk=123", "indeed.com"),
        ("https://www.linkedin.com/jobs/view/123", "linkedin.com"),
        ("https://www.glassdoor.com/Job/example-job.htm", "glassdoor.com"),
        ("https://www.ziprecruiter.com/jobs/example-123", "ziprecruiter.com"),
    ],
)
def test_run_job_discovery_filters_known_aggregators_before_source_detection(
    session_factory: sessionmaker[Session],
    url: str,
    expected_domain: str,
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        search_id = _search(session)
        search = get_job_search_definition(session, search_id)
        queries = generate_job_discovery_queries(
            search.to_snapshot(), max_queries=4, result_limit=5
        )
        fetcher = CountingFetcher({})

        run = run_job_discovery(
            session,
            search_definition_id=search_id,
            provider_name="fake",
            provider=FakeJobDiscoveryProvider(
                results_by_query={
                    queries[0].rendered_query: [
                        DiscoveredJobCandidate(
                            discovered_url=url,
                            provider_name="fake",
                            query_identifier=queries[0].stable_query_id,
                            rank=1,
                        )
                    ]
                }
            ),
            fetcher=fetcher,
            validator=FakeValidator({}),
            connector=FakeJobSourceConnector(),
            config=_config(),
        )
        observations = list_job_discovery_observations(session, discovery_run_id=run.id)

        assert run.status == "completed"
        assert fetcher.calls == []
        assert len(observations) == 1
        assert (
            observations[0].observation.processing_status
            == JobDiscoveryObservationStatus.UNSUPPORTED.value
        )
        assert expected_domain in (observations[0].observation.exclusion_reason or "")


@pytest.mark.parametrize(
    "url",
    [
        "https://boards.greenhouse.io/acme/jobs/123",
        "https://jobs.ashbyhq.com/acme/123",
        "https://jobs.lever.co/acme/123",
        "https://careers.example.com/jobs/platform-director",
    ],
)
def test_run_job_discovery_keeps_supported_and_unknown_hosts_eligible_for_source_detection(
    session_factory: sessionmaker[Session],
    url: str,
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        search_id = _search(session)
        search = get_job_search_definition(session, search_id)
        queries = generate_job_discovery_queries(
            search.to_snapshot(), max_queries=4, result_limit=5
        )
        fetcher = CountingFetcher(
            {
                url: PublicPage(
                    requested_url=url,
                    final_url=url,
                    content_type="text/html",
                    text="https://example.com/jobs/123",
                )
            }
        )

        run = run_job_discovery(
            session,
            search_definition_id=search_id,
            provider_name="fake",
            provider=FakeJobDiscoveryProvider(
                results_by_query={
                    queries[0].rendered_query: [
                        DiscoveredJobCandidate(
                            discovered_url=url,
                            provider_name="fake",
                            query_identifier=queries[0].stable_query_id,
                            rank=1,
                        )
                    ]
                }
            ),
            fetcher=fetcher,
            validator=FakeValidator({}),
            connector=FakeJobSourceConnector(),
            config=_config(),
        )
        observations = list_job_discovery_observations(session, discovery_run_id=run.id)

        assert run.status == "completed"
        assert fetcher.calls == [url]
        assert len(observations) == 1
        assert observations[0].observation.exclusion_reason != (
            "Excluded known aggregator domain before source detection: indeed.com."
        )


def test_run_job_discovery_import_failure_isolated_to_one_supported_source(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        search_id = _search(session)
        search = get_job_search_definition(session, search_id)
        queries = generate_job_discovery_queries(
            search.to_snapshot(), max_queries=4, result_limit=5
        )
        good_url = "https://boards.greenhouse.io/acme/jobs/strong"
        bad_url = "https://boards.greenhouse.io/beta/jobs/fail"
        provider = FakeJobDiscoveryProvider(
            results_by_query={
                queries[0].rendered_query: [
                    DiscoveredJobCandidate(
                        discovered_url=good_url,
                        provider_name="fake",
                        query_identifier=queries[0].stable_query_id,
                        rank=1,
                        company_hint="Acme",
                    ),
                    DiscoveredJobCandidate(
                        discovered_url=bad_url,
                        provider_name="fake",
                        query_identifier=queries[0].stable_query_id,
                        rank=2,
                        company_hint="Beta",
                    ),
                ]
            }
        )
        connector = BoardAwareConnector(
            jobs_by_token={
                "acme": [_posting("strong", "Director, Platform Engineering")],
                "beta": [],
            },
            errors_by_token={"beta": JobSourceProviderError("provider unavailable")},
        )

        run = run_job_discovery(
            session,
            search_definition_id=search_id,
            provider_name="fake",
            provider=provider,
            fetcher=FakeFetcher(
                {
                    good_url: _page_for_token(good_url, "acme"),
                    bad_url: _page_for_token(bad_url, "beta"),
                }
            ),
            validator=connector,
            connector=connector,
            config=_config(),
        )
        observations = list_job_discovery_observations(session, discovery_run_id=run.id)

        assert run.status == "partial"
        assert len(list(session.scalars(select(JobSourceConfigurationModel)))) == 2
        assert len(list(session.scalars(select(JobLeadModel)))) == 1
        assert any(
            record.observation.processing_status == JobDiscoveryObservationStatus.IMPORTED.value
            for record in observations
        )
        assert any(
            record.observation.processing_status == JobDiscoveryObservationStatus.FAILED.value
            for record in observations
        )
