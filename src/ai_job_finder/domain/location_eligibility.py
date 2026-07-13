from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ai_job_finder.domain.candidate import CandidateProfileSnapshot
from ai_job_finder.domain.enums import (
    JobLocationEligibilityReason,
    JobLocationEligibilityStatus,
    WorkplaceType,
)


@dataclass(frozen=True, slots=True)
class JobLocationSignals:
    location_text: str | None
    workplace_type: WorkplaceType | None
    offices: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class JobLocationEligibilityResult:
    status: JobLocationEligibilityStatus
    reasons: list[JobLocationEligibilityReason]
    summary: str


def classify_job_location_eligibility(
    candidate: CandidateProfileSnapshot,
    signals: JobLocationSignals,
) -> JobLocationEligibilityResult:
    location_text = _normalize(signals.location_text)
    workplace_type = signals.workplace_type
    locations = _location_values(signals)
    preferred_locations = [_canonical_location(value) for value in candidate.preferred_locations]
    acceptable_remote_geographies = [
        _canonical_remote_geography(value) for value in candidate.acceptable_remote_geographies
    ]

    if _has_conflicting_signals(
        workplace_type,
        [signals.location_text, *signals.offices],
    ):
        return _result(
            JobLocationEligibilityStatus.NEEDS_REVIEW,
            JobLocationEligibilityReason.CONFLICTING_LOCATION_SIGNALS,
            "Location and workplace signals conflict; review before acting.",
        )

    if not location_text and workplace_type is None and not locations:
        return _result(
            JobLocationEligibilityStatus.NEEDS_REVIEW,
            JobLocationEligibilityReason.MISSING_LOCATION_DATA,
            "Location and workplace type are missing; review before acting.",
        )

    if workplace_type is None:
        return _result(
            JobLocationEligibilityStatus.NEEDS_REVIEW,
            JobLocationEligibilityReason.MISSING_WORKPLACE_TYPE,
            "Workplace type is missing; review before acting.",
        )

    if workplace_type is WorkplaceType.REMOTE:
        return _classify_remote(locations, acceptable_remote_geographies)

    return _classify_presence_required(workplace_type, locations, preferred_locations)


def _classify_remote(
    locations: list[str],
    acceptable_remote_geographies: list[str],
) -> JobLocationEligibilityResult:
    if not acceptable_remote_geographies:
        return _result(
            JobLocationEligibilityStatus.NEEDS_REVIEW,
            JobLocationEligibilityReason.CANDIDATE_REMOTE_GEOGRAPHY_NOT_CONFIGURED,
            "Remote geography preferences are not configured; review before acting.",
        )
    if not locations or all(_is_remote_only(value) for value in locations):
        return _result(
            JobLocationEligibilityStatus.NEEDS_REVIEW,
            JobLocationEligibilityReason.REMOTE_GEOGRAPHY_UNCLEAR,
            "Remote role does not state a clear eligible geography.",
        )
    if len(_non_remote_locations(locations)) > 1:
        return _result(
            JobLocationEligibilityStatus.NEEDS_REVIEW,
            JobLocationEligibilityReason.MULTIPLE_LOCATIONS_REQUIRE_REVIEW,
            "Remote role lists multiple geographies; review selection constraints.",
        )

    location = _non_remote_locations(locations)[0]
    if _is_broad_region(location):
        return _result(
            JobLocationEligibilityStatus.NEEDS_REVIEW,
            JobLocationEligibilityReason.BROAD_REGION_REQUIRES_REVIEW,
            "Remote role lists a broad region; review before acting.",
        )
    if _matches_any_remote_geography(location, acceptable_remote_geographies):
        return _result(
            JobLocationEligibilityStatus.ELIGIBLE,
            JobLocationEligibilityReason.REMOTE_GEOGRAPHY_MATCH,
            "Remote geography matches the candidate's configured remote preferences.",
        )
    if _is_international(location):
        return _result(
            JobLocationEligibilityStatus.INELIGIBLE,
            JobLocationEligibilityReason.INTERNATIONAL_LOCATION_NOT_APPROVED,
            "Remote role is limited to a geography outside configured remote preferences.",
        )
    return _result(
        JobLocationEligibilityStatus.NEEDS_REVIEW,
        JobLocationEligibilityReason.REMOTE_GEOGRAPHY_UNCLEAR,
        "Remote geography does not clearly match configured preferences.",
    )


def _classify_presence_required(
    workplace_type: WorkplaceType,
    locations: list[str],
    preferred_locations: list[str],
) -> JobLocationEligibilityResult:
    if not locations:
        return _result(
            JobLocationEligibilityStatus.NEEDS_REVIEW,
            JobLocationEligibilityReason.MISSING_LOCATION_DATA,
            "Presence is required, but job location is missing.",
        )
    if len(_non_remote_locations(locations)) > 1:
        return _result(
            JobLocationEligibilityStatus.NEEDS_REVIEW,
            JobLocationEligibilityReason.MULTIPLE_LOCATIONS_REQUIRE_REVIEW,
            "Role lists multiple locations; review whether the candidate can choose "
            "an approved market.",
        )

    location = _non_remote_locations(locations)[0]
    if _matches_any_preferred_location(location, preferred_locations):
        return _result(
            JobLocationEligibilityStatus.ELIGIBLE,
            JobLocationEligibilityReason.PREFERRED_LOCATION_MATCH,
            f"{workplace_type.value.title()} role is in an approved candidate market.",
        )
    if _is_broad_region(location):
        return _result(
            JobLocationEligibilityStatus.NEEDS_REVIEW,
            JobLocationEligibilityReason.BROAD_REGION_REQUIRES_REVIEW,
            "Presence role lists a broad region; review before acting.",
        )
    if _is_international(location):
        return _result(
            JobLocationEligibilityStatus.INELIGIBLE,
            JobLocationEligibilityReason.INTERNATIONAL_LOCATION_NOT_APPROVED,
            "Presence is required in an international location outside approved markets.",
        )
    return _result(
        JobLocationEligibilityStatus.INELIGIBLE,
        JobLocationEligibilityReason.PRESENCE_REQUIRED_OUTSIDE_PREFERRED_GEOGRAPHY,
        "Presence is required outside the candidate's approved markets.",
    )


def _result(
    status: JobLocationEligibilityStatus,
    reason: JobLocationEligibilityReason,
    summary: str,
) -> JobLocationEligibilityResult:
    return JobLocationEligibilityResult(status=status, reasons=[reason], summary=summary)


def _location_values(signals: JobLocationSignals) -> list[str]:
    values: list[str] = []
    for value in [signals.location_text, *signals.offices]:
        values.extend(_normalized_location_parts(value))
    return _dedupe([_normalize(value) for value in values if _normalize(value)])


def _has_conflicting_signals(
    workplace_type: WorkplaceType | None,
    raw_values: list[str | None],
) -> bool:
    if workplace_type is None:
        return False
    text = " ".join(_normalize(value) for value in raw_values if value)
    if workplace_type is WorkplaceType.REMOTE:
        return bool(re.search(r"\b(?:hybrid|on[ -]?site|onsite|in office)\b", text))
    return any(_is_remote_only(value) for value in raw_values if value)


def _normalized_location_parts(value: str | None) -> list[str]:
    if value is None:
        return []
    parts = _split_location_parts(value)
    if len(parts) <= 1:
        return parts

    geographic_parts = [part for part in parts if not _is_workplace_marker(part)]
    return geographic_parts or parts


def _split_location_parts(value: str) -> list[str]:
    if _has_multiple_location_delimiter(value):
        return _split_multiple_locations(value)
    return [value]


def _has_multiple_location_delimiter(value: str) -> bool:
    return bool(re.search(r"\s(?:or|and)\s|[;/|]", value, flags=re.IGNORECASE))


def _split_multiple_locations(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"\s(?:or|and)\s|[;/|]", value) if part.strip()]


def _is_workplace_marker(value: str) -> bool:
    return _normalize(value) in {
        "remote",
        "hybrid",
        "onsite",
        "on site",
        "office",
        "in office",
    }


def _non_remote_locations(locations: list[str]) -> list[str]:
    return [location for location in locations if not _is_remote_only(location)]


def _is_remote_only(value: str) -> bool:
    return _normalize(value) in {"remote", "remote anywhere", "anywhere remote"}


def _matches_any_preferred_location(location: str, preferred_locations: list[str]) -> bool:
    canonical_location = _canonical_location(location)
    return any(canonical_location == preferred for preferred in preferred_locations)


def _matches_any_remote_geography(location: str, acceptable_remote_geographies: list[str]) -> bool:
    canonical_location = _canonical_remote_geography(location)
    return any(
        canonical_location == geography
        or canonical_location.endswith(f" {geography}")
        or geography in _remote_geography_aliases(canonical_location)
        for geography in acceptable_remote_geographies
    )


def _canonical_location(value: str) -> str:
    normalized = _normalize(value)
    if normalized in {"nyc", "new york", "new york ny", "new york city"}:
        return "new york city"
    if normalized in {"edinburgh", "edinburgh uk", "edinburgh scotland"}:
        return "edinburgh"
    return normalized


def _canonical_remote_geography(value: str) -> str:
    normalized = _normalize(value)
    if normalized in {"us", "u s", "usa", "u s a", "united states", "united states of america"}:
        return "united states"
    if normalized.startswith("remote "):
        return _canonical_remote_geography(normalized.removeprefix("remote "))
    return normalized


def _remote_geography_aliases(value: str) -> set[str]:
    aliases = {value}
    if value in {"us", "u s", "usa", "u s a", "united states", "united states of america"}:
        aliases.add("united states")
    if value in {"uk", "u k", "united kingdom", "england", "scotland"}:
        aliases.add("united kingdom")
    if value in {"edinburgh", "london"}:
        aliases.add("united kingdom")
    return aliases


def _is_broad_region(value: str) -> bool:
    return _normalize(value) in {
        "americas",
        "apac",
        "asia pacific",
        "emea",
        "europe",
        "european union",
        "north america",
    }


def _is_international(value: str) -> bool:
    normalized = _normalize(value)
    return any(
        token in normalized
        for token in {
            "edinburgh",
            "london",
            "scotland",
            "united kingdom",
            "uk",
            "u k",
            "canada",
            "toronto",
            "berlin",
            "germany",
            "paris",
            "france",
        }
    )


def _normalize(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
