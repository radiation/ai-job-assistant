from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from ai_job_finder.domain.candidate import CandidateProfileSnapshot, CareerFactSnapshot
from ai_job_finder.domain.common import new_uuid, utc_now
from ai_job_finder.domain.enums import (
    EvidenceTag,
    Recommendation,
    RemotePreference,
    WorkplaceType,
)
from ai_job_finder.domain.evaluation import EvaluationResult, ScoreComponent
from ai_job_finder.domain.job_lead import JobLeadSnapshot
from ai_job_finder.domain.job_search_terminology import (
    is_excluded_target_function_title,
    normalize_job_search_text,
    target_function_matches,
)

DEFAULT_SCORING_VERSION: Final[str] = "candidate_evidence_v5"
_RECOMMENDATION_THRESHOLDS: Final[tuple[tuple[Recommendation, float], ...]] = (
    (Recommendation.STRONG_RECOMMEND, 80.0),
    (Recommendation.RECOMMEND, 65.0),
    (Recommendation.HOLD, 45.0),
    (Recommendation.DECLINE, 0.0),
)


@dataclass(frozen=True, slots=True)
class ScoringWeights:
    level_alignment: float = 0.40
    target_function_alignment: float = 0.20
    location_alignment: float = 0.10
    platform_ownership: float = 0.15
    leadership_scope: float = 0.10
    technical_alignment: float = 0.05
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
    usable_facts = [fact for fact in verified_facts if fact.is_usable]

    level_score, level_notes = _score_level(candidate, job)
    function_score, function_notes = _score_function(candidate, job)
    location_score, location_notes = _score_location(candidate, job)
    platform_score, platform_notes = _score_platform_ownership(job)
    technical_alignment_score, technical_notes = _score_technical_alignment(job, usable_facts)
    leadership_score, leadership_notes = _score_leadership_scope(job, usable_facts)

    positive_signals = (
        level_notes[0]
        + function_notes[0]
        + location_notes[0]
        + platform_notes[0]
        + technical_notes[0]
        + leadership_notes[0]
    )
    concerns = (
        level_notes[1]
        + function_notes[1]
        + location_notes[1]
        + platform_notes[1]
        + technical_notes[1]
        + leadership_notes[1]
    )
    missing_evidence = (
        level_notes[2]
        + function_notes[2]
        + location_notes[2]
        + platform_notes[2]
        + technical_notes[2]
        + leadership_notes[2]
    )
    matched_evidence = _dedupe_preserving_order(technical_notes[3] + leadership_notes[3])

    if not usable_facts:
        concerns.append(
            "No verified career facts are available yet; recommendation remains provisional."
        )

    referral_priority_score = 0
    missing_evidence.append("Referral priority remains intentionally deferred in this slice.")

    score_components = (
        _score_component("level_alignment", level_score, active_config.weights.level_alignment),
        _score_component(
            "target_function_alignment",
            function_score,
            active_config.weights.target_function_alignment,
        ),
        _score_component(
            "location_alignment", location_score, active_config.weights.location_alignment
        ),
        _score_component(
            "platform_ownership", platform_score, active_config.weights.platform_ownership
        ),
        _score_component(
            "leadership_scope", leadership_score, active_config.weights.leadership_scope
        ),
        _score_component(
            "technical_alignment",
            technical_alignment_score,
            active_config.weights.technical_alignment,
        ),
        _score_component(
            "referral_priority",
            referral_priority_score,
            active_config.weights.referral_priority,
        ),
    )
    overall_score = round(
        sum(component.weighted_score for component in score_components),
        2,
    )

    recommendation = recommendation_for_score(overall_score)
    explanation = _build_explanation(
        version=active_config.version,
        matched_evidence=matched_evidence,
        positive_signals=positive_signals,
        concerns=concerns,
        missing_evidence=missing_evidence,
    )

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
        score_components=score_components,
    )


def _score_component(name: str, score: int, weight: float) -> ScoreComponent:
    return ScoreComponent(
        name=name,
        score=score,
        weight=weight,
        weighted_score=score * weight,
    )


def _normalize(text: str | None) -> str:
    return (text or "").casefold()


def _level_target_matches_title(target: str, title: str) -> bool:
    aliases = {
        "vice president": ("vice president", "vp", "svp", "avp"),
        "senior director": ("senior director",),
        "director": ("director",),
        "head": ("head of", "head"),
        "senior manager": ("senior manager",),
        "manager": ("manager",),
    }
    normalized_title = f" {normalize_job_search_text(title)} "
    return any(
        f" {normalize_job_search_text(alias)} " in normalized_title
        for alias in aliases.get(target, (target,))
    )


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _score_level(
    candidate: CandidateProfileSnapshot,
    job: JobLeadSnapshot,
) -> tuple[int, tuple[list[str], list[str], list[str]]]:
    if is_excluded_target_function_title(job.title):
        return 0, (
            [],
            ["The title identifies a non-target technical or business function."],
            [],
        )
    normalized_title = normalize_job_search_text(job.title)
    normalized_targets = [_normalize(value) for value in candidate.target_levels]
    matches = [
        value
        for value in normalized_targets
        if value and _level_target_matches_title(value, normalized_title)
    ]

    if matches:
        return 100, ([f"Job level aligns with target level(s): {', '.join(matches)}."], [], [])
    if not normalized_targets:
        return 50, ([], [], ["Candidate target levels are missing."])
    return 35, ([], ["Job level does not clearly match the candidate's stated target levels."], [])


def _score_function(
    candidate: CandidateProfileSnapshot,
    job: JobLeadSnapshot,
) -> tuple[int, tuple[list[str], list[str], list[str]]]:
    targets = [_normalize(value) for value in candidate.target_functions]
    if is_excluded_target_function_title(job.title):
        return 0, (
            [],
            ["The title identifies a non-target technical or business function."],
            [],
        )
    title_match, description_match = target_function_matches(
        targets,
        title=job.title,
        description=job.description_normalized,
    )

    if title_match:
        return 100, (
            ["Job title maps directly to the candidate's target function."],
            [],
            [],
        )
    if description_match:
        return 80, (
            ["Job description reinforces the candidate's target function."],
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
    if is_excluded_target_function_title(job.title):
        return 10, ([], ["The title identifies a non-target technical or business function."], [])
    description = _normalize(f"{job.title} {job.description_normalized}")
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
    facts: list[CareerFactSnapshot],
) -> tuple[int, tuple[list[str], list[str], list[str], list[str]]]:
    text = _normalize(f"{job.title} {job.description_normalized}")
    evidence_index = _evidence_index(facts)
    signal_rules = [
        (
            {"manager", "manage", "team", "teams", "organization", "leadership"},
            EvidenceTag.PEOPLE_LEADERSHIP,
            "People leadership evidence supports the role's team leadership expectations.",
            (
                "The role expects people leadership, but no verified structured "
                "people-leadership evidence was found."
            ),
        ),
        (
            {"leaders", "managers", "manager of managers", "directors"},
            EvidenceTag.MANAGER_OF_MANAGERS,
            "Verified manager-of-managers evidence aligns with the role's leadership depth.",
            "The role signals manager-of-managers scope without matching verified evidence.",
        ),
        (
            {"global", "follow-the-sun", "multi-region"},
            EvidenceTag.GLOBAL_OPERATIONS,
            "Verified global-operations evidence matches the role's operating scope.",
            (
                "The role references global operations, but verified global-operations "
                "evidence is missing."
            ),
        ),
        (
            {"scale", "large-scale", "high scale", "millions"},
            EvidenceTag.HIGH_SCALE,
            "Verified high-scale evidence supports the role's scale expectations.",
            "The role expects high-scale leadership, but verified high-scale evidence is missing.",
        ),
        (
            {"p&l", "budget", "financial"},
            EvidenceTag.P_AND_L,
            "Verified P&L evidence supports the role's financial ownership scope.",
            "The role references financial ownership without matching verified P&L evidence.",
        ),
        (
            {"vendor", "outsourcing", "partners"},
            EvidenceTag.VENDOR_MANAGEMENT,
            "Verified vendor-management evidence supports the role's external partner scope.",
            "The role references vendor management without matching verified evidence.",
        ),
    ]
    return _score_evidence_rules(
        text,
        signal_rules,
        evidence_index,
        empty_message="Leadership-scope signals are weak or absent in the posting.",
        base_score=35,
        concern_score=30,
    )


def _score_technical_alignment(
    job: JobLeadSnapshot,
    facts: list[CareerFactSnapshot],
) -> tuple[int, tuple[list[str], list[str], list[str], list[str]]]:
    if is_excluded_target_function_title(job.title):
        return 15, (
            [],
            ["The title identifies a non-target technical or business function."],
            [],
            [],
        )
    text = _normalize(f"{job.title} {job.description_normalized}")
    evidence_index = _evidence_index(facts)
    signal_rules = [
        (
            {
                "platform engineering",
                "developer platform",
                "devex",
                "developer experience",
                "developer productivity",
            },
            EvidenceTag.PLATFORM_ENGINEERING,
            (
                "Verified platform and developer-experience evidence aligns with the "
                "job's platform language."
            ),
            (
                "The role emphasizes platform or developer-experience work without "
                "matching verified evidence."
            ),
        ),
        (
            {"infrastructure", "cloud", "kubernetes", "containers"},
            EvidenceTag.INFRASTRUCTURE,
            (
                "Verified infrastructure or cloud evidence aligns with the job's "
                "platform foundations."
            ),
            (
                "The role emphasizes infrastructure, cloud, or Kubernetes without "
                "matching verified evidence."
            ),
        ),
        (
            {"ai", "ml", "machine learning", "data platform"},
            EvidenceTag.AI_ENABLEMENT,
            (
                "Verified AI, ML-platform, or data-platform evidence matches the "
                "job's AI platform signals."
            ),
            "The role references AI, ML, or data-platform work without matching verified evidence.",
        ),
        (
            {"reliability", "observability", "security", "incident"},
            EvidenceTag.RELIABILITY,
            (
                "Verified reliability, observability, or security evidence supports "
                "the job's operational expectations."
            ),
            (
                "The role stresses reliability, observability, or security without "
                "matching verified evidence."
            ),
        ),
        (
            {
                "ci/cd",
                "continuous integration",
                "continuous delivery",
                "build systems",
                "build tooling",
            },
            EvidenceTag.CI_CD,
            (
                "Verified CI/CD and delivery-system evidence aligns with the job's "
                "build and release expectations."
            ),
            "The role expects CI/CD or build-system ownership without matching verified evidence.",
        ),
    ]
    return _score_evidence_rules(
        text,
        signal_rules,
        evidence_index,
        empty_message="The posting provides limited technical signal for evidence matching.",
        base_score=40,
        concern_score=35,
    )


def _evidence_index(facts: list[CareerFactSnapshot]) -> dict[EvidenceTag, list[CareerFactSnapshot]]:
    indexed: dict[EvidenceTag, list[CareerFactSnapshot]] = {}
    for fact in facts:
        for tag in fact.evidence_tags:
            indexed.setdefault(tag, []).append(fact)
    return indexed


def _supporting_tags(primary_tag: EvidenceTag) -> set[EvidenceTag]:
    related = {
        EvidenceTag.PLATFORM_ENGINEERING: {
            EvidenceTag.PLATFORM_ENGINEERING,
            EvidenceTag.DEVELOPER_EXPERIENCE,
            EvidenceTag.DEVELOPER_PRODUCTIVITY,
            EvidenceTag.SHARED_SERVICES,
        },
        EvidenceTag.INFRASTRUCTURE: {
            EvidenceTag.INFRASTRUCTURE,
            EvidenceTag.CLOUD,
            EvidenceTag.KUBERNETES,
        },
        EvidenceTag.AI_ENABLEMENT: {
            EvidenceTag.AI_ENABLEMENT,
            EvidenceTag.AI_PLATFORM,
            EvidenceTag.AGENTIC_WORKFLOWS,
            EvidenceTag.AI_DEVELOPER_EXPERIENCE,
            EvidenceTag.LLM_PLATFORM,
            EvidenceTag.AI_GOVERNANCE,
            EvidenceTag.ML_PLATFORM,
            EvidenceTag.DATA_PLATFORM,
        },
        EvidenceTag.RELIABILITY: {
            EvidenceTag.RELIABILITY,
            EvidenceTag.OBSERVABILITY,
            EvidenceTag.SECURITY,
        },
        EvidenceTag.CI_CD: {
            EvidenceTag.CI_CD,
            EvidenceTag.DEVELOPER_PRODUCTIVITY,
        },
    }
    return related.get(primary_tag, {primary_tag})


def _fact_summary(fact: CareerFactSnapshot) -> str:
    tag_summary = ", ".join(sorted(tag.value for tag in fact.evidence_tags)) or "no tags"
    return f"{fact.approved_wording} [{tag_summary}]"


def _score_evidence_rules(
    text: str,
    signal_rules: list[tuple[set[str], EvidenceTag, str, str]],
    evidence_index: dict[EvidenceTag, list[CareerFactSnapshot]],
    *,
    empty_message: str,
    base_score: int,
    concern_score: int,
) -> tuple[int, tuple[list[str], list[str], list[str], list[str]]]:
    positive_signals: list[str] = []
    concerns: list[str] = []
    missing_evidence: list[str] = []
    matched_evidence: list[str] = []
    matched_count = 0
    triggered_count = 0

    for phrases, primary_tag, success_message, missing_message in signal_rules:
        if not any(phrase in text for phrase in phrases):
            continue
        triggered_count += 1
        supporting_facts: list[CareerFactSnapshot] = []
        for tag in _supporting_tags(primary_tag):
            supporting_facts.extend(evidence_index.get(tag, []))
        unique_facts_by_id: dict[str, CareerFactSnapshot] = {}
        for fact in supporting_facts:
            unique_facts_by_id[str(fact.id)] = fact
        unique_facts = list(unique_facts_by_id.values())
        if primary_tag is EvidenceTag.PEOPLE_LEADERSHIP:
            unique_facts = [fact for fact in unique_facts if fact.leadership_scope]
        if unique_facts:
            matched_count += 1
            positive_signals.append(success_message)
            matched_evidence.extend(_fact_summary(fact) for fact in unique_facts[:2])
        else:
            concerns.append(missing_message)
            missing_evidence.append(missing_message)

    if triggered_count == 0:
        return base_score, ([], [empty_message], [], [])

    coverage = matched_count / triggered_count
    if coverage == 1:
        score = 100
    elif coverage >= 0.66:
        score = 80
    elif coverage >= 0.33:
        score = 60
    else:
        score = concern_score
    return score, (positive_signals, concerns, missing_evidence, matched_evidence)


def recommendation_for_score(score: float) -> Recommendation:
    for recommendation, minimum_score in _RECOMMENDATION_THRESHOLDS:
        if score >= minimum_score:
            return recommendation
    raise ValueError("Score must not be less than zero.")


def recommendation_minimum_score(recommendation: Recommendation) -> float:
    for candidate_recommendation, minimum_score in _RECOMMENDATION_THRESHOLDS:
        if recommendation is candidate_recommendation:
            return minimum_score
    raise ValueError(f"No minimum score is configured for recommendation {recommendation!r}.")


def _build_explanation(
    *,
    version: str,
    matched_evidence: list[str],
    positive_signals: list[str],
    concerns: list[str],
    missing_evidence: list[str],
) -> str:
    sections = [
        f"Scoring version: {version}",
        "Matched verified evidence:",
        *(
            f"- {item}"
            for item in matched_evidence or ["No verified evidence matched the job signals."]
        ),
        "Positive signals:",
        *(
            f"- {item}"
            for item in positive_signals or ["No strong positive signals were identified."]
        ),
        "Concerns:",
        *(f"- {item}" for item in concerns or ["No material concerns were identified."]),
        "Missing evidence:",
        *(f"- {item}" for item in missing_evidence or ["No major evidence gaps were identified."]),
    ]
    return "\n".join(sections)
