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


def _expanded_definition() -> JobSearchDefinitionSnapshot:
    definition = _definition()
    return JobSearchDefinitionSnapshot(
        id=definition.id,
        name=definition.name,
        enabled=definition.enabled,
        title_include_patterns=definition.title_include_patterns,
        title_exclude_patterns=definition.title_exclude_patterns,
        target_domains=[
            JobSearchDomain.PLATFORM_ENGINEERING,
            JobSearchDomain.DEVELOPER_EXPERIENCE,
            JobSearchDomain.INFRASTRUCTURE,
            JobSearchDomain.ENGINEERING_PRODUCTIVITY,
            JobSearchDomain.AI_PLATFORM,
            JobSearchDomain.SHARED_SERVICES,
        ],
        target_seniority_levels=[
            JobSearchSeniority.DIRECTOR,
            JobSearchSeniority.SENIOR_DIRECTOR,
            JobSearchSeniority.VICE_PRESIDENT,
            JobSearchSeniority.HEAD,
            JobSearchSeniority.EXECUTIVE,
        ],
        allowed_locations=["New York", "NYC"],
        allowed_remote_geographies=["US"],
        allowed_workplace_types=[WorkplaceType.REMOTE],
        minimum_score_threshold=definition.minimum_score_threshold,
        created_at=definition.created_at,
        updated_at=definition.updated_at,
    )


def test_query_generation_is_deterministic_deduplicated_and_capped() -> None:
    definition = _definition()

    first = generate_job_discovery_queries(definition, max_queries=4, result_limit=5)
    second = generate_job_discovery_queries(definition, max_queries=4, result_limit=5)

    assert [query.rendered_query for query in first] == [
        "Director Platform Engineering New York site:boards.greenhouse.io",
        (
            'Director Developer Experience remote United States "software engineering" '
            '-"shared services" -"finance" -site:indeed.com -site:linkedin.com '
            "-site:glassdoor.com -site:ziprecruiter.com -site:builtin.com -site:wellfound.com "
            "-site:theladders.com -site:virtualvocations.com -site:dice.com"
        ),
        "Senior Director Platform Engineering New York site:jobs.ashbyhq.com",
        (
            'Senior Director Developer Experience remote United States "software engineering" '
            '-"shared services" -"finance" -site:indeed.com -site:linkedin.com '
            "-site:glassdoor.com -site:ziprecruiter.com -site:builtin.com -site:wellfound.com "
            "-site:theladders.com -site:virtualvocations.com -site:dice.com"
        ),
    ]
    assert [query.stable_query_id for query in first] == [query.stable_query_id for query in second]
    assert len({query.rendered_query for query in first}) == len(first)
    assert all(query.result_limit == 5 for query in first)
    assert any("site:boards.greenhouse.io" in query.rendered_query for query in first)
    assert any("-site:indeed.com" in query.rendered_query for query in first)
    assert any('"software engineering"' in query.rendered_query for query in first)
    assert any('-"shared services"' in query.rendered_query for query in first)
    assert any("-site:dice.com" in query.rendered_query for query in first)
    assert [query.target_domain for query in first] == [
        "boards.greenhouse.io",
        None,
        "jobs.ashbyhq.com",
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
        "Senior Director Developer Experience site:boards.greenhouse.io",
        (
            'Senior Director Developer Experience "software engineering" '
            '-"shared services" -site:indeed.com -site:linkedin.com -site:glassdoor.com '
            "-site:ziprecruiter.com -site:builtin.com -site:wellfound.com -site:theladders.com "
            "-site:virtualvocations.com -site:dice.com"
        ),
        "Senior Director Developer Experience site:jobs.ashbyhq.com",
        "Senior Director Developer Experience site:jobs.lever.co",
    ]


def test_query_generation_covers_expanded_saved_search_intent() -> None:
    definition = _expanded_definition()

    queries = generate_job_discovery_queries(definition, max_queries=12, result_limit=5)

    assert len(queries) == 12
    assert len({query.rendered_query.casefold() for query in queries}) == len(queries)
    assert {query.location_or_workplace_term for query in queries} == {"New York", "remote US"}
    assert {"Director Developer Experience", "Director Shared Services"} <= {
        query.title_phrase for query in queries
    }
    assert {"Senior Director Platform Engineering", "Executive Platform Engineering"} <= {
        query.title_phrase for query in queries
    }
    assert any(query.target_domain == "boards.greenhouse.io" for query in queries)
    assert any(query.target_domain == "jobs.ashbyhq.com" for query in queries)
    assert any(query.target_domain == "jobs.lever.co" for query in queries)
    assert any(query.target_domain is None for query in queries)
    assert "NYC" not in {query.location_or_workplace_term for query in queries}
    assert any(query.title_phrase.startswith("Head of ") for query in queries)
    assert all(len(query.rendered_query) <= 300 for query in queries)
