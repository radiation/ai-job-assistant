from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from ai_job_finder.domain.enums import WorkplaceType
from ai_job_finder.domain.errors import JobDiscoveryQueryGenerationError
from ai_job_finder.domain.job_discovery import JobDiscoveryQuery
from ai_job_finder.domain.job_discovery.targeting import (
    DISCOVERY_ATS_QUERY_HOSTS,
    DISCOVERY_EXCLUDED_AGGREGATOR_DOMAINS,
)
from ai_job_finder.domain.job_searches import (
    JobSearchDefinitionSnapshot,
    JobSearchDomain,
    JobSearchSeniority,
)

MAX_TITLE_PHRASES = 4
MAX_LOCATION_TERMS = 2
MAX_LOGICAL_TARGETS = 2
SECONDARY_TARGETED_HOST_COUNT = 1

DOMAIN_LABELS: dict[JobSearchDomain, str] = {
    JobSearchDomain.PLATFORM_ENGINEERING: "Platform Engineering",
    JobSearchDomain.DEVELOPER_EXPERIENCE: "Developer Experience",
    JobSearchDomain.INFRASTRUCTURE: "Infrastructure",
    JobSearchDomain.ENGINEERING_PRODUCTIVITY: "Engineering Productivity",
    JobSearchDomain.AI_PLATFORM: "AI Platform",
    JobSearchDomain.DATA_PLATFORM: "Data Platform",
    JobSearchDomain.SHARED_SERVICES: "Shared Services",
}

SENIORITY_LABELS: dict[JobSearchSeniority, str] = {
    JobSearchSeniority.MANAGER: "Manager",
    JobSearchSeniority.SENIOR_MANAGER: "Senior Manager",
    JobSearchSeniority.DIRECTOR: "Director",
    JobSearchSeniority.SENIOR_DIRECTOR: "Senior Director",
    JobSearchSeniority.VICE_PRESIDENT: "VP",
    JobSearchSeniority.HEAD: "Head",
    JobSearchSeniority.PRINCIPAL: "Principal",
    JobSearchSeniority.STAFF: "Staff",
    JobSearchSeniority.EXECUTIVE: "Executive",
}


@dataclass(frozen=True, slots=True)
class _LogicalTarget:
    title_phrase: str
    location_term: str | None


def generate_job_discovery_queries(
    definition: JobSearchDefinitionSnapshot,
    *,
    max_queries: int,
    result_limit: int,
) -> list[JobDiscoveryQuery]:
    if max_queries <= 0 or result_limit <= 0:
        raise JobDiscoveryQueryGenerationError("Discovery query generation requires positive caps.")

    title_phrases = _title_phrases(definition)
    location_terms = _location_terms(definition)

    rendered_queries: list[tuple[str, str, str | None, str | None]] = []
    for index, target in enumerate(_logical_targets(title_phrases, location_terms)):
        targeted_hosts: tuple[str, ...] = DISCOVERY_ATS_QUERY_HOSTS
        if index > 0:
            targeted_hosts = DISCOVERY_ATS_QUERY_HOSTS[:SECONDARY_TARGETED_HOST_COUNT]
        for targeted_host in targeted_hosts:
            rendered_queries.append(
                (
                    _render_targeted_query(
                        title_phrase=target.title_phrase,
                        location_term=target.location_term,
                        target_host=targeted_host,
                    ),
                    target.title_phrase,
                    targeted_host,
                    target.location_term,
                )
            )
        rendered_queries.append(
            (
                _render_broad_query(
                    title_phrase=target.title_phrase,
                    location_term=target.location_term,
                ),
                target.title_phrase,
                None,
                target.location_term,
            )
        )

    deduped: list[tuple[str, str, str | None, str | None]] = []
    seen: set[str] = set()
    for rendered_query, title_phrase, target_domain, deduped_location_term in rendered_queries:
        key = rendered_query.casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append((rendered_query, title_phrase, target_domain, deduped_location_term))
        if len(deduped) >= max_queries:
            break

    if not deduped:
        raise JobDiscoveryQueryGenerationError(
            "Saved search did not produce any non-empty discovery queries."
        )

    return [
        JobDiscoveryQuery(
            stable_query_id=_stable_query_identifier(
                search_definition_id=str(definition.id),
                ordinal=ordinal,
                rendered_query=rendered_query,
            ),
            search_definition_id=definition.id,
            ordinal=ordinal,
            rendered_query=rendered_query,
            title_phrase=title_phrase,
            target_domain=target_domain,
            location_or_workplace_term=location_term,
            result_limit=result_limit,
        )
        for ordinal, (rendered_query, title_phrase, target_domain, location_term) in enumerate(
            deduped,
            start=1,
        )
    ]


def _title_phrases(definition: JobSearchDefinitionSnapshot) -> list[str]:
    phrases = _unique_preserving_order(definition.title_include_patterns)[:MAX_TITLE_PHRASES]
    generated: list[str] = []
    seniorities = definition.target_seniority_levels[:2]
    domains = definition.target_domains[:2]

    if seniorities and domains:
        for seniority in seniorities:
            for domain in domains:
                generated.append(f"{SENIORITY_LABELS[seniority]} {DOMAIN_LABELS[domain]}")
    elif seniorities:
        generated.extend(SENIORITY_LABELS[item] for item in seniorities)
    elif domains:
        generated.extend(DOMAIN_LABELS[item] for item in domains)

    existing = {item.casefold() for item in phrases}
    for phrase in generated:
        if len(phrases) >= MAX_TITLE_PHRASES:
            break
        normalized = _normalize_phrase(phrase)
        if normalized and normalized.casefold() not in existing:
            phrases.append(normalized)
            existing.add(normalized.casefold())

    return phrases


def _location_terms(definition: JobSearchDefinitionSnapshot) -> list[str]:
    terms: list[str] = []
    for location in definition.allowed_locations[:1]:
        terms.append(location)
    for geography in definition.allowed_remote_geographies[:1]:
        terms.append(f"remote {geography}")
    if WorkplaceType.REMOTE in definition.allowed_workplace_types:
        terms.append("remote")
    return _unique_preserving_order(terms)[:MAX_LOCATION_TERMS]


def _logical_targets(title_phrases: list[str], location_terms: list[str]) -> list[_LogicalTarget]:
    if not title_phrases:
        return []
    targets = [
        _LogicalTarget(
            title_phrase=title_phrases[0],
            location_term=location_terms[0] if location_terms else None,
        )
    ]
    if len(targets) >= MAX_LOGICAL_TARGETS:
        return targets
    secondary = _secondary_target(title_phrases, location_terms)
    if secondary is not None:
        targets.append(secondary)
    return targets


def _secondary_target(
    title_phrases: list[str],
    location_terms: list[str],
) -> _LogicalTarget | None:
    if location_terms:
        return _LogicalTarget(title_phrase=title_phrases[0], location_term=None)
    if len(title_phrases) > 1:
        return _LogicalTarget(title_phrase=title_phrases[1], location_term=None)
    return None


def _render_base_query(title_phrase: str, location_term: str | None) -> str:
    rendered = f'"{title_phrase}"'
    if location_term is not None:
        if location_term == "remote":
            rendered = f"{rendered} remote"
        else:
            rendered = f'{rendered} "{location_term}"'
    return rendered.strip()


def _render_targeted_query(title_phrase: str, location_term: str | None, target_host: str) -> str:
    return f"{_render_base_query(title_phrase, location_term)} site:{target_host}".strip()


def _render_broad_query(title_phrase: str, location_term: str | None) -> str:
    base_query = _render_base_query(title_phrase, location_term)
    exclusions = " ".join(f"-site:{domain}" for domain in DISCOVERY_EXCLUDED_AGGREGATOR_DOMAINS)
    return f"{base_query} {exclusions}".strip()


def _normalize_phrase(value: str) -> str:
    return " ".join(value.strip().split())


def _unique_preserving_order(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize_phrase(value)
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(normalized)
    return unique


def _stable_query_identifier(
    *,
    search_definition_id: str,
    ordinal: int,
    rendered_query: str,
) -> str:
    digest = sha256(f"{search_definition_id}:{ordinal}:{rendered_query.casefold()}".encode())
    return digest.hexdigest()[:24]
