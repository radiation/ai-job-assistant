from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ai_job_finder.domain.enums import WorkplaceType
from ai_job_finder.domain.evaluation import EvaluationResult
from ai_job_finder.domain.job_lead import JobLeadSnapshot
from ai_job_finder.domain.job_searches.enums import JobSearchDomain, JobSearchSeniority
from ai_job_finder.domain.job_searches.models import JobSearchDefinitionSnapshot

_DOMAIN_RULES: tuple[tuple[JobSearchDomain, tuple[str, ...]], ...] = (
    (
        JobSearchDomain.PLATFORM_ENGINEERING,
        (
            "platform engineering",
            "developer platform",
            "internal platform",
            "platform team",
        ),
    ),
    (
        JobSearchDomain.DEVELOPER_EXPERIENCE,
        (
            "developer experience",
            "devex",
            "developer enablement",
        ),
    ),
    (
        JobSearchDomain.INFRASTRUCTURE,
        (
            "infrastructure",
            "cloud infrastructure",
            "reliability engineering",
            "site reliability",
        ),
    ),
    (
        JobSearchDomain.ENGINEERING_PRODUCTIVITY,
        (
            "engineering productivity",
            "developer productivity",
            "productivity engineering",
        ),
    ),
    (
        JobSearchDomain.AI_PLATFORM,
        (
            "ai platform",
            "ml platform",
            "machine learning platform",
            "ai infrastructure",
        ),
    ),
    (
        JobSearchDomain.DATA_PLATFORM,
        (
            "data platform",
            "data infrastructure",
            "analytics platform",
        ),
    ),
    (
        JobSearchDomain.SHARED_SERVICES,
        (
            "shared services",
            "common services",
            "core services",
        ),
    ),
)

_SENIORITY_RULES: tuple[tuple[JobSearchSeniority, tuple[str, ...]], ...] = (
    (JobSearchSeniority.EXECUTIVE, ("chief ", "cto", "cio", "ciso")),
    (JobSearchSeniority.VICE_PRESIDENT, ("vice president", " vp ", "svp", "avp")),
    (JobSearchSeniority.SENIOR_DIRECTOR, ("senior director",)),
    (JobSearchSeniority.DIRECTOR, ("director",)),
    (JobSearchSeniority.HEAD, ("head of", "head,")),
    (JobSearchSeniority.SENIOR_MANAGER, ("senior manager",)),
    (JobSearchSeniority.MANAGER, ("manager",)),
    (JobSearchSeniority.PRINCIPAL, ("principal",)),
    (JobSearchSeniority.STAFF, ("staff",)),
)


@dataclass(frozen=True, slots=True)
class JobSearchLocationContext:
    location_text: str | None
    workplace_type: WorkplaceType | None
    offices: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class JobSearchMatchResult:
    matched: bool
    criteria_matched: bool
    above_threshold: bool
    matched_criteria: dict[str, list[str]]
    exclusion_reasons: list[str]
    inferred_domains: list[JobSearchDomain]
    inferred_seniority_levels: list[JobSearchSeniority]


def normalize_search_text(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def evaluate_job_search_match(
    definition: JobSearchDefinitionSnapshot,
    job: JobLeadSnapshot,
    evaluation: EvaluationResult | None,
    *,
    location_context: JobSearchLocationContext | None = None,
) -> JobSearchMatchResult:
    title_text = normalize_search_text(job.title)
    title_include = _matching_patterns(title_text, definition.title_include_patterns)
    title_exclude = _matching_patterns(title_text, definition.title_exclude_patterns)

    inferred_domains = infer_job_search_domains(job)
    inferred_seniority = infer_job_search_seniority(job)
    location_match, location_reasons, location_hits = _match_location(
        definition,
        location_context
        or JobSearchLocationContext(
            location_text=job.location_text,
            workplace_type=job.workplace_type,
        ),
    )

    matched_criteria: dict[str, list[str]] = {}
    exclusion_reasons: list[str] = []

    if definition.title_include_patterns:
        if title_include:
            matched_criteria["title_include_patterns"] = title_include
        else:
            exclusion_reasons.append("Job title did not match any saved-search include pattern.")
    if title_exclude:
        exclusion_reasons.append("Job title matched an exclude pattern.")
        matched_criteria["title_exclude_patterns"] = title_exclude

    if definition.target_domains:
        domain_hits = [
            domain.value for domain in inferred_domains if domain in set(definition.target_domains)
        ]
        if domain_hits:
            matched_criteria["target_domains"] = domain_hits
        else:
            exclusion_reasons.append("Job domain signals did not match the saved-search domains.")

    if definition.target_seniority_levels:
        seniority_hits = [
            level.value
            for level in inferred_seniority
            if level in set(definition.target_seniority_levels)
        ]
        if seniority_hits:
            matched_criteria["target_seniority_levels"] = seniority_hits
        else:
            exclusion_reasons.append("Job title did not match the saved-search seniority levels.")

    if location_match and location_hits:
        matched_criteria["location"] = location_hits
    elif location_reasons:
        exclusion_reasons.extend(location_reasons)

    if evaluation is None:
        above_threshold = False
        exclusion_reasons.append("Job has no evaluation for saved-search threshold comparison.")
    else:
        above_threshold = evaluation.overall_score >= definition.minimum_score_threshold
        if above_threshold:
            matched_criteria["minimum_score_threshold"] = [
                _threshold_label(evaluation.overall_score, definition.minimum_score_threshold)
            ]
        else:
            exclusion_reasons.append(
                "Job evaluation score is below the saved-search minimum threshold."
            )

    criteria_matched = not exclusion_reasons or all(
        reason == "Job evaluation score is below the saved-search minimum threshold."
        or reason == "Job has no evaluation for saved-search threshold comparison."
        for reason in exclusion_reasons
    )
    if title_exclude:
        criteria_matched = False
    if not location_match:
        criteria_matched = False
    if definition.title_include_patterns and not title_include:
        criteria_matched = False
    if definition.target_domains and "target_domains" not in matched_criteria:
        criteria_matched = False
    if definition.target_seniority_levels and "target_seniority_levels" not in matched_criteria:
        criteria_matched = False

    return JobSearchMatchResult(
        matched=criteria_matched and above_threshold,
        criteria_matched=criteria_matched,
        above_threshold=above_threshold,
        matched_criteria=matched_criteria,
        exclusion_reasons=_dedupe(exclusion_reasons),
        inferred_domains=inferred_domains,
        inferred_seniority_levels=inferred_seniority,
    )


def infer_job_search_domains(job: JobLeadSnapshot) -> list[JobSearchDomain]:
    haystack = normalize_search_text(f"{job.title} {job.description_normalized}")
    matched: list[JobSearchDomain] = []
    for domain, patterns in _DOMAIN_RULES:
        if any(normalize_search_text(pattern) in haystack for pattern in patterns):
            matched.append(domain)
    return matched


def infer_job_search_seniority(job: JobLeadSnapshot) -> list[JobSearchSeniority]:
    title = f" {normalize_search_text(job.title)} "
    matched: list[JobSearchSeniority] = []
    for level, patterns in _SENIORITY_RULES:
        if any(normalize_search_text(pattern).strip() in title for pattern in patterns):
            matched.append(level)
    if JobSearchSeniority.SENIOR_DIRECTOR in matched and JobSearchSeniority.DIRECTOR in matched:
        matched.remove(JobSearchSeniority.DIRECTOR)
    if JobSearchSeniority.SENIOR_MANAGER in matched and JobSearchSeniority.MANAGER in matched:
        matched.remove(JobSearchSeniority.MANAGER)
    return matched


def _matching_patterns(haystack: str, patterns: list[str]) -> list[str]:
    matches: list[str] = []
    for pattern in patterns:
        normalized_pattern = normalize_search_text(pattern)
        if normalized_pattern and normalized_pattern in haystack:
            matches.append(pattern)
    return matches


def _match_location(
    definition: JobSearchDefinitionSnapshot,
    context: JobSearchLocationContext,
) -> tuple[bool, list[str], list[str]]:
    normalized_locations = _normalized_location_values(context)
    allowed_locations = [normalize_search_text(value) for value in definition.allowed_locations]
    allowed_remote_geographies = [
        _canonical_remote_geography(value) for value in definition.allowed_remote_geographies
    ]
    allowed_workplace_types = set(definition.allowed_workplace_types)
    matched_locations: list[str] = []
    exclusion_reasons: list[str] = []

    if allowed_workplace_types:
        if context.workplace_type is None:
            exclusion_reasons.append("Job workplace type is missing for this saved search.")
            return False, exclusion_reasons, matched_locations
        if context.workplace_type not in allowed_workplace_types:
            exclusion_reasons.append("Job workplace type is not included in this saved search.")
            return False, exclusion_reasons, matched_locations
        matched_locations.append(context.workplace_type.value)

    if not allowed_locations and not allowed_remote_geographies:
        return True, exclusion_reasons, matched_locations

    if context.workplace_type is WorkplaceType.REMOTE:
        remote_hits = [
            location
            for location in normalized_locations
            if _canonical_remote_geography(location) in allowed_remote_geographies
        ]
        if remote_hits:
            return True, exclusion_reasons, matched_locations + remote_hits
        if allowed_locations:
            location_hits = [
                location
                for location in normalized_locations
                if _contains_location(location, allowed_locations)
            ]
            if location_hits:
                return True, exclusion_reasons, matched_locations + location_hits
        exclusion_reasons.append("Remote role geography does not match the saved search.")
        return False, exclusion_reasons, matched_locations

    if allowed_locations:
        location_hits = [
            location
            for location in normalized_locations
            if _contains_location(location, allowed_locations)
        ]
        if location_hits:
            return True, exclusion_reasons, matched_locations + location_hits
        exclusion_reasons.append("Job location does not match the saved search.")
        return False, exclusion_reasons, matched_locations

    return True, exclusion_reasons, matched_locations


def _normalized_location_values(context: JobSearchLocationContext) -> list[str]:
    values: list[str] = []
    for raw_value in [context.location_text, *context.offices]:
        normalized = normalize_search_text(raw_value)
        if normalized:
            values.extend(_split_location_parts(normalized))
    return _dedupe(values)


def _split_location_parts(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"\s(?:or|and)\s|[;/|]", value) if part.strip()]


def _contains_location(location: str, allowed_locations: list[str]) -> bool:
    return any(
        allowed == location or allowed in location or location in allowed
        for allowed in allowed_locations
    )


def _canonical_remote_geography(value: str) -> str:
    normalized = normalize_search_text(value)
    if normalized in {"us", "u s", "usa", "u s a", "united states", "united states of america"}:
        return "united states"
    if normalized.startswith("remote "):
        return _canonical_remote_geography(normalized.removeprefix("remote "))
    return normalized


def _threshold_label(score: float, threshold: float) -> str:
    return f"score {score:.2f} >= threshold {threshold:.2f}"


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped
