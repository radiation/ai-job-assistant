from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from ai_job_finder.domain.enums import WorkplaceType
from ai_job_finder.domain.errors import JobDiscoveryQueryGenerationError
from ai_job_finder.domain.job_discovery import JobDiscoveryQuery
from ai_job_finder.domain.job_discovery.targeting import (
    DISCOVERY_BROAD_QUERY_EXCLUDED_DOMAINS,
)
from ai_job_finder.domain.job_searches import (
    JobSearchDefinitionSnapshot,
    JobSearchDomain,
    JobSearchSeniority,
)

_QUERY_VARIANT_CYCLE: tuple[str | None, ...] = (
    "boards.greenhouse.io",
    None,
    "jobs.ashbyhq.com",
    None,
    "jobs.lever.co",
    None,
)

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
    JobSearchSeniority.HEAD: "Head of",
    JobSearchSeniority.PRINCIPAL: "Principal",
    JobSearchSeniority.STAFF: "Staff",
    JobSearchSeniority.EXECUTIVE: "Executive",
}


@dataclass(frozen=True, slots=True)
class _LogicalTarget:
    title_phrase: str
    location_term: str | None


_TECHNICAL_DISCOVERY_DOMAINS = frozenset(
    {
        JobSearchDomain.PLATFORM_ENGINEERING,
        JobSearchDomain.DEVELOPER_EXPERIENCE,
        JobSearchDomain.INFRASTRUCTURE,
        JobSearchDomain.ENGINEERING_PRODUCTIVITY,
        JobSearchDomain.AI_PLATFORM,
        JobSearchDomain.DATA_PLATFORM,
    }
)


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

    rendered_queries = _render_queries(
        _logical_targets(title_phrases, location_terms),
        max_queries=max_queries,
        broad_context=_broad_context(definition),
        title_exclusions=_unique_preserving_order(definition.title_exclude_patterns),
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
    explicit_phrases = _unique_preserving_order(definition.title_include_patterns)
    phrases = explicit_phrases[:1]
    generated: list[str] = []
    seniorities = definition.target_seniority_levels
    domains = definition.target_domains

    if seniorities and domains:
        generated.extend(
            f"{SENIORITY_LABELS[seniorities[0]]} {DOMAIN_LABELS[domain]}" for domain in domains
        )
        generated.extend(
            f"{SENIORITY_LABELS[seniority]} {DOMAIN_LABELS[domains[0]]}"
            for seniority in seniorities[1:]
        )
        generated.extend(
            f"{SENIORITY_LABELS[seniority]} {DOMAIN_LABELS[domain]}"
            for seniority in seniorities[1:]
            for domain in domains[1:]
        )
    elif seniorities:
        generated.extend(SENIORITY_LABELS[item] for item in seniorities)
    elif domains:
        generated.extend(DOMAIN_LABELS[item] for item in domains)

    existing = {item.casefold() for item in phrases}
    for phrase in generated:
        normalized = _normalize_phrase(phrase)
        if normalized and normalized.casefold() not in existing:
            phrases.append(normalized)
            existing.add(normalized.casefold())

    for phrase in explicit_phrases[1:]:
        if phrase.casefold() not in existing:
            phrases.append(phrase)
            existing.add(phrase.casefold())

    return phrases


def _location_terms(definition: JobSearchDefinitionSnapshot) -> list[str]:
    terms: list[str] = []
    local_keys: set[str] = set()
    for location in definition.allowed_locations:
        key = _location_key(location)
        if key in local_keys:
            continue
        local_keys.add(key)
        terms.append(location)
    for geography in definition.allowed_remote_geographies:
        terms.append(f"remote {geography}")
    if (
        WorkplaceType.REMOTE in definition.allowed_workplace_types
        and not definition.allowed_remote_geographies
    ):
        terms.append("remote")
    return _unique_preserving_order(terms)


def _logical_targets(title_phrases: list[str], location_terms: list[str]) -> list[_LogicalTarget]:
    return [
        _LogicalTarget(
            title_phrase=title_phrase,
            location_term=location_terms[index % len(location_terms)] if location_terms else None,
        )
        for index, title_phrase in enumerate(title_phrases)
    ]


def _broad_context(definition: JobSearchDefinitionSnapshot) -> tuple[str, ...]:
    context: list[str] = []
    if set(definition.target_domains) & _TECHNICAL_DISCOVERY_DOMAINS:
        context.append('"software engineering"')
    if JobSearchDomain.SHARED_SERVICES not in definition.target_domains:
        context.append('-"shared services"')
    return tuple(context)


def _render_queries(
    targets: list[_LogicalTarget],
    *,
    max_queries: int,
    broad_context: tuple[str, ...],
    title_exclusions: list[str],
) -> list[tuple[str, str, str | None, str | None]]:
    """Give each target one balanced variant before allocating another to any target."""
    rendered_queries: list[tuple[str, str, str | None, str | None]] = []
    seen: set[str] = set()
    for variant_offset in range(len(_QUERY_VARIANT_CYCLE)):
        for target_index, target in enumerate(targets):
            target_host = _QUERY_VARIANT_CYCLE[
                (target_index + variant_offset) % len(_QUERY_VARIANT_CYCLE)
            ]
            rendered_query = (
                _render_broad_query(
                    target.title_phrase,
                    target.location_term,
                    broad_context=broad_context,
                    title_exclusions=title_exclusions,
                )
                if target_host is None
                else _render_targeted_query(target.title_phrase, target.location_term, target_host)
            )
            if rendered_query.casefold() in seen:
                continue
            seen.add(rendered_query.casefold())
            rendered_queries.append(
                (rendered_query, target.title_phrase, target_host, target.location_term)
            )
            if len(rendered_queries) >= max_queries:
                return rendered_queries
    return rendered_queries


def _render_base_query(title_phrase: str, location_term: str | None) -> str:
    rendered = _normalize_phrase(title_phrase)
    if location_term is not None:
        rendered = f"{rendered} {_normalize_phrase(location_term)}"
    return rendered.strip()


def _render_targeted_query(title_phrase: str, location_term: str | None, target_host: str) -> str:
    return f"{_render_base_query(title_phrase, location_term)} site:{target_host}".strip()


def _render_broad_query(
    title_phrase: str,
    location_term: str | None,
    *,
    broad_context: tuple[str, ...],
    title_exclusions: list[str],
) -> str:
    base_query = _render_base_query(title_phrase, location_term)
    exclusions = [
        *(f'-"{phrase}"' for phrase in title_exclusions),
        *(f"-site:{domain}" for domain in DISCOVERY_BROAD_QUERY_EXCLUDED_DOMAINS),
    ]
    return " ".join((base_query, *broad_context, *exclusions)).strip()


def _normalize_phrase(value: str) -> str:
    return " ".join(value.strip().split())


def _location_key(value: str) -> str:
    normalized = _normalize_phrase(value).casefold()
    if normalized in {"new york", "nyc", "new york city"}:
        return "new york city"
    return normalized


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
