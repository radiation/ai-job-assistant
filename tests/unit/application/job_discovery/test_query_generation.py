from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from ai_job_finder.application.job_discovery.query_generation import generate_job_discovery_queries
from ai_job_finder.domain.enums import WorkplaceType
from ai_job_finder.domain.job_searches import (
    JobSearchDefinitionSnapshot,
    JobSearchDomain,
    JobSearchSeniority,
)


def _definition() -> JobSearchDefinitionSnapshot:
    return JobSearchDefinitionSnapshot(
        id=uuid4(),
        name="Platform roles",
        enabled=True,
        title_include_patterns=["Director Platform Engineering", "director platform engineering"],
        title_exclude_patterns=["finance"],
        target_domains=[JobSearchDomain.PLATFORM_ENGINEERING, JobSearchDomain.DEVELOPER_EXPERIENCE],
        target_seniority_levels=[JobSearchSeniority.DIRECTOR, JobSearchSeniority.SENIOR_DIRECTOR],
        allowed_locations=["New York"],
        allowed_remote_geographies=["United States"],
        allowed_workplace_types=[WorkplaceType.REMOTE],
        minimum_score_threshold=70,
        created_at=datetime(2026, 7, 20, tzinfo=UTC),
        updated_at=datetime(2026, 7, 20, tzinfo=UTC),
    )


def test_query_generation_is_deterministic_deduplicated_and_capped() -> None:
    definition = _definition()

    first = generate_job_discovery_queries(definition, max_queries=4, result_limit=5)
    second = generate_job_discovery_queries(definition, max_queries=4, result_limit=5)

    assert [query.rendered_query for query in first] == [
        '"Director Platform Engineering" "New York" site:boards.greenhouse.io',
        '"Director Platform Engineering" "New York" site:jobs.ashbyhq.com',
        '"Director Platform Engineering" "New York" site:jobs.lever.co',
        (
            '"Director Platform Engineering" "New York" '
            "-site:indeed.com -site:linkedin.com -site:glassdoor.com -site:ziprecruiter.com"
        ),
    ]
    assert [query.stable_query_id for query in first] == [query.stable_query_id for query in second]
    assert len({query.rendered_query for query in first}) == len(first)
    assert all(query.result_limit == 5 for query in first)
    assert [query.target_domain for query in first] == [
        "boards.greenhouse.io",
        "jobs.ashbyhq.com",
        "jobs.lever.co",
        None,
    ]


def test_query_generation_uses_seniority_and_domain_fallbacks() -> None:
    definition = JobSearchDefinitionSnapshot(
        id=uuid4(),
        name="DX roles",
        enabled=True,
        title_include_patterns=[],
        title_exclude_patterns=[],
        target_domains=[JobSearchDomain.DEVELOPER_EXPERIENCE],
        target_seniority_levels=[JobSearchSeniority.SENIOR_DIRECTOR],
        allowed_locations=[],
        allowed_remote_geographies=[],
        allowed_workplace_types=[],
        minimum_score_threshold=60,
        created_at=datetime(2026, 7, 20, tzinfo=UTC),
        updated_at=datetime(2026, 7, 20, tzinfo=UTC),
    )

    queries = generate_job_discovery_queries(definition, max_queries=4, result_limit=3)

    assert [query.rendered_query for query in queries] == [
        '"Senior Director Developer Experience" site:boards.greenhouse.io',
        '"Senior Director Developer Experience" site:jobs.ashbyhq.com',
        '"Senior Director Developer Experience" site:jobs.lever.co',
        (
            '"Senior Director Developer Experience" '
            "-site:indeed.com -site:linkedin.com -site:glassdoor.com -site:ziprecruiter.com"
        ),
    ]


def test_query_generation_bounds_requests_with_primary_and_secondary_targets() -> None:
    definition = _definition()

    queries = generate_job_discovery_queries(definition, max_queries=10, result_limit=5)

    assert [query.rendered_query for query in queries] == [
        '"Director Platform Engineering" "New York" site:boards.greenhouse.io',
        '"Director Platform Engineering" "New York" site:jobs.ashbyhq.com',
        '"Director Platform Engineering" "New York" site:jobs.lever.co',
        (
            '"Director Platform Engineering" "New York" '
            "-site:indeed.com -site:linkedin.com -site:glassdoor.com -site:ziprecruiter.com"
        ),
        '"Director Platform Engineering" site:boards.greenhouse.io',
        (
            '"Director Platform Engineering" '
            "-site:indeed.com -site:linkedin.com -site:glassdoor.com -site:ziprecruiter.com"
        ),
    ]
    assert len(queries) == 6
