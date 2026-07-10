from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from ai_job_finder.domain.candidate import CandidateProfileSnapshot, CareerFactSnapshot
from ai_job_finder.domain.common import new_uuid, utc_now
from ai_job_finder.domain.enums import (
    Recommendation,
    RemotePreference,
    VerificationStatus,
    WorkplaceType,
)
from ai_job_finder.domain.evaluation import EvaluationResult
from ai_job_finder.domain.job_lead import JobLeadSnapshot

DEFAULT_SCORING_VERSION: Final[str] = "foundation_v1"


@dataclass(frozen=True, slots=True)
class ScoringWeights:
    level_alignment: float = 0.25
    target_function_alignment: float = 0.20
    location_alignment: float = 0.15
    platform_ownership: float = 0.20
    leadership_scope: float = 0.20
    technical_alignment: float = 0.0
    referral_priority: float = 0.0


@dataclass(frozen=True, slots=True)
class ScoringConfig:
    version: str = DEFAULT_SCORING_VERSION
    weights: ScoringWeights = ScoringWeights()


DEFAULT_SCORING_CONFIG: Final[ScoringConfig] = ScoringConfig()


def evaluate_job_fit(
    candidate: CandidateProfileSnapshot,
    job: JobLeadSnapshot,
    verified_facts: list[CareerFactSnapshot],
    config: ScoringConfig | None = None,
) -> EvaluationResult:
    active_config = config or DEFAULT_SCORING_CONFIG
    usable_facts = [
        fact for fact in verified_facts if fact.verification_status is VerificationStatus.VERIFIED
    ]

    level_score, level_notes = _score_level(candidate, job)
    function_score, function_notes = _score_function(candidate, job)
    location_score, location_notes = _score_location(candidate, job)
    platform_score, platform_notes = _score_platform_ownership(job)
    leadership_score, leadership_notes = _score_leadership_scope(job)

    positive_signals = (
        level_notes[0]
        + function_notes[0]
        + location_notes[0]
        + platform_notes[0]
        + leadership_notes[0]
    )
    concerns = (
        level_notes[1]
        + function_notes[1]
        + location_notes[1]
        + platform_notes[1]
        + leadership_notes[1]
    )
    missing_information = (
        level_notes[2]
        + function_notes[2]
        + location_notes[2]
        + platform_notes[2]
        + leadership_notes[2]
    )

    if not usable_facts:
        concerns.append(
            "No verified career facts are available yet; recommendation remains provisional."
        )

    technical_alignment_score = 0
    referral_priority_score = 0
    missing_information.extend(
        [
            "Technical alignment is intentionally deferred in the foundation slice.",
            "Referral priority is intentionally deferred in the foundation slice.",
        ]
    )

    overall_score = round(
        (level_score * active_config.weights.level_alignment)
        + (function_score * active_config.weights.target_function_alignment)
        + (location_score * active_config.weights.location_alignment)
        + (platform_score * active_config.weights.platform_ownership)
        + (leadership_score * active_config.weights.leadership_scope)
        + (technical_alignment_score * active_config.weights.technical_alignment)
        + (referral_priority_score * active_config.weights.referral_priority),
        2,
    )

    recommendation = _recommendation_for_score(overall_score)
    explanation = _build_explanation(positive_signals, concerns, missing_information)

    return EvaluationResult(
        id=new_uuid(),
        candidate_profile_id=candidate.id,
        job_lead_id=job.id,
        scoring_version=active_config.version,
        leadership_scope_score=leadership_score,
        technical_alignment_score=technical_alignment_score,
        location_score=location_score,
        level_score=level_score,
        platform_ownership_score=platform_score,
        referral_priority_score=referral_priority_score,
        overall_score=overall_score,
        recommendation=recommendation,
        explanation=explanation,
        evaluated_at=utc_now(),
    )


def _normalize(text: str | None) -> str:
    return (text or "").casefold()


def _score_level(
    candidate: CandidateProfileSnapshot,
    job: JobLeadSnapshot,
) -> tuple[int, tuple[list[str], list[str], list[str]]]:
    haystack = f"{job.title} {job.description_normalized}"
    normalized_haystack = _normalize(haystack)
    normalized_targets = [_normalize(value) for value in candidate.target_levels]
    matches = [value for value in normalized_targets if value and value in normalized_haystack]

    if matches:
        return 100, ([f"Job level aligns with target level(s): {', '.join(matches)}."], [], [])
    if not normalized_targets:
        return 50, ([], [], ["Candidate target levels are missing."])
    return 35, ([], ["Job level does not clearly match the candidate's stated target levels."], [])


def _score_function(
    candidate: CandidateProfileSnapshot,
    job: JobLeadSnapshot,
) -> tuple[int, tuple[list[str], list[str], list[str]]]:
    title = _normalize(job.title)
    description = _normalize(job.description_normalized)
    targets = [_normalize(value) for value in candidate.target_functions]

    title_matches = [value for value in targets if value and value in title]
    description_matches = [value for value in targets if value and value in description]

    if title_matches:
        return 100, (
            [f"Job title maps directly to target function(s): {', '.join(title_matches)}."],
            [],
            [],
        )
    if description_matches:
        return 80, (
            [f"Job description reinforces target function(s): {', '.join(description_matches)}."],
            [],
            [],
        )
    if not targets:
        return 50, ([], [], ["Candidate target functions are missing."])
    return 30, (
        [],
        ["No clear target-function match was found in the job title or description."],
        [],
    )


def _score_location(
    candidate: CandidateProfileSnapshot,
    job: JobLeadSnapshot,
) -> tuple[int, tuple[list[str], list[str], list[str]]]:
    location_text = _normalize(job.location_text)
    preferred_locations = [_normalize(value) for value in candidate.preferred_locations]
    workplace_type = job.workplace_type

    if workplace_type is WorkplaceType.REMOTE:
        if candidate.remote_preference in {RemotePreference.REMOTE_ONLY, RemotePreference.FLEXIBLE}:
            return 100, (
                ["Remote workplace arrangement matches the candidate's preference."],
                [],
                [],
            )
        return 65, (["Remote role preserves location flexibility."], [], [])

    if workplace_type is WorkplaceType.HYBRID:
        if candidate.remote_preference in {RemotePreference.HYBRID, RemotePreference.FLEXIBLE}:
            if any(location and location in location_text for location in preferred_locations):
                return 90, (["Hybrid role is in a preferred market."], [], [])
            return 70, (
                ["Hybrid workplace aligns broadly with the candidate's preference."],
                [],
                ["Location is not an explicit preferred market match."],
            )
        return 45, (
            [],
            ["Hybrid expectation may conflict with the candidate's remote preference."],
            [],
        )

    if workplace_type is WorkplaceType.ONSITE:
        if any(location and location in location_text for location in preferred_locations):
            if candidate.remote_preference is RemotePreference.ONSITE:
                return 85, (
                    ["Onsite role is in a preferred location and matches onsite preference."],
                    [],
                    [],
                )
            return 60, (
                ["Onsite role is in a preferred location."],
                ["Workplace type is less flexible than the candidate typically prefers."],
                [],
            )
        return 20, ([], ["Onsite role is outside the candidate's stated preferred locations."], [])

    if not job.location_text and workplace_type is None:
        return 40, ([], [], ["Job location and workplace type were not supplied."])

    return 50, ([], [], ["Job workplace alignment is only partially specified."])


def _score_platform_ownership(
    job: JobLeadSnapshot,
) -> tuple[int, tuple[list[str], list[str], list[str]]]:
    description = _normalize(job.description_normalized)
    phrases = {
        "platform": "Platform ownership is named directly.",
        "developer platform": "Developer platform responsibility is explicit.",
        "platform engineering": "Platform engineering language is present.",
        "self-service": "Self-service enablement is called out.",
        "internal platform": "Internal platform responsibility is called out.",
    }

    matches = [message for phrase, message in phrases.items() if phrase in description]
    if matches:
        score = min(100, 45 + (len(matches) * 12))
        return score, (matches, [], [])
    return 25, ([], ["The posting does not clearly describe platform ownership scope."], [])


def _score_leadership_scope(
    job: JobLeadSnapshot,
) -> tuple[int, tuple[list[str], list[str], list[str]]]:
    text = _normalize(f"{job.title} {job.description_normalized}")
    phrases = {
        "director": "Director-level scope is explicit.",
        "head of": "Head-of scope is explicit.",
        "strategy": "Strategic ownership is expected.",
        "roadmap": "Roadmap ownership is included.",
        "team": "Team leadership is referenced.",
        "organization": "Organization-level leadership is referenced.",
    }
    matches = [message for phrase, message in phrases.items() if phrase in text]
    if matches:
        score = min(100, 40 + (len(matches) * 10))
        return score, (matches, [], [])
    return 30, ([], ["Leadership-scope signals are weak or absent in the posting."], [])


def _recommendation_for_score(score: float) -> Recommendation:
    if score >= 80:
        return Recommendation.STRONG_RECOMMEND
    if score >= 65:
        return Recommendation.RECOMMEND
    if score >= 45:
        return Recommendation.HOLD
    return Recommendation.DECLINE


def _build_explanation(
    positive_signals: list[str], concerns: list[str], missing_information: list[str]
) -> str:
    sections = [
        "Positive signals:",
        *(
            f"- {item}"
            for item in positive_signals or ["No strong positive signals were identified."]
        ),
        "Concerns:",
        *(f"- {item}" for item in concerns or ["No material concerns were identified."]),
        "Missing information:",
        *(
            f"- {item}"
            for item in missing_information or ["No major information gaps were identified."]
        ),
    ]
    return "\n".join(sections)
