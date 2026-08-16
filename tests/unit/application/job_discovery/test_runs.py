from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy.orm import Session, sessionmaker

from ai_job_finder.application.job_discovery import (
    JobDiscoveryConfig,
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
    OverlappingJobDiscoveryRunError,
)
from ai_job_finder.domain.job_discovery import DiscoveredJobCandidate
from ai_job_finder.domain.job_sources import NormalizedJobPosting
from ai_job_finder.domain.source_detection import GreenhouseBoardValidation, PublicPage
from ai_job_finder.infrastructure.database.base import Base
from ai_job_finder.infrastructure.database.models import JobDiscoveryRunModel
from ai_job_finder.infrastructure.database.session import create_engine_from_url
from ai_job_finder.infrastructure.job_discovery.fake import FakeJobDiscoveryProvider
from ai_job_finder.infrastructure.job_sources.fake import FakeJobSourceConnector


class FakeFetcher:
    def __init__(self, pages: dict[str, PublicPage]) -> None:
        self.pages = pages

    def fetch(self, url: str) -> PublicPage:
        return self.pages[url]


class FakeValidator:
    def __init__(self, validation_by_token: dict[str, GreenhouseBoardValidation]) -> None:
        self.validation_by_token = validation_by_token

    def validate_board_token(self, board_token: str) -> GreenhouseBoardValidation:
        return self.validation_by_token.get(
            board_token, GreenhouseBoardValidation(token=board_token, status="invalid", valid=False)
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
