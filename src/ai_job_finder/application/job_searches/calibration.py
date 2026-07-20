from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from ai_job_finder.domain.candidate import CandidateProfileSnapshot, CareerFactSnapshot
from ai_job_finder.domain.common import new_uuid, utc_now
from ai_job_finder.domain.enums import (
    CareerFactCategory,
    CareerFactLifecycle,
    EvidenceTag,
    PostingStatus,
    ProvenanceType,
    Recommendation,
    RemotePreference,
    WorkplaceType,
)
from ai_job_finder.domain.job_lead import JobLeadSnapshot
from ai_job_finder.domain.scoring import DEFAULT_SCORING_VERSION, evaluate_job_fit

GOLDEN_SET_PATH = Path("tests/fixtures/scoring/golden_set_v1.json")
EXPECTED_FIXTURE_VERSION = "v1"
EXPECTED_FIXTURE_KIND = "synthetic_smoke"
EXPECTED_CANDIDATE_PROFILE = "synthetic"
BUCKET_TO_RECOMMENDATION: dict[str, Recommendation] = {
    "strong_fit": Recommendation.STRONG_RECOMMEND,
    "plausible_fit": Recommendation.RECOMMEND,
    "weak_fit": Recommendation.HOLD,
    "reject": Recommendation.DECLINE,
}
BUCKET_ORDER = ["strong_fit", "plausible_fit", "weak_fit", "reject"]


@dataclass(frozen=True, slots=True)
class CalibrationFixtureMetadata:
    version: str
    fixture_kind: str
    candidate_profile: str
    purpose: str


@dataclass(frozen=True, slots=True)
class CalibrationFixture:
    metadata: CalibrationFixtureMetadata
    cases: list[GoldenSetCase]


@dataclass(frozen=True, slots=True)
class CalibrationSubject:
    candidate: CandidateProfileSnapshot
    verified_facts: tuple[CareerFactSnapshot, ...]


@dataclass(frozen=True, slots=True)
class GoldenSetCase:
    case_id: str
    title: str
    company: str
    description: str
    location_text: str | None
    workplace_type: WorkplaceType | None
    expected_bucket: str
    expected_min_score: float | None
    expected_max_score: float | None
    expected_ordering_group: str | None
    rationale: str | None


@dataclass(frozen=True, slots=True)
class CalibrationCaseResult:
    case: GoldenSetCase
    score: float
    recommendation: Recommendation
    scoring_version: str
    factor_outputs: dict[str, int]
    concerns: list[str]
    missing_evidence: list[str]
    matched_evidence: list[str]
    positive_signals: list[str]
    explanation: str


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    scoring_version: str
    case_results: list[CalibrationCaseResult]
    failures: list[str]

    @property
    def passed(self) -> bool:
        return not self.failures


def calibration_candidate() -> CandidateProfileSnapshot:
    now = utc_now()
    return CandidateProfileSnapshot(
        id=new_uuid(),
        full_name="Calibration Candidate",
        preferred_locations=["Seattle", "Remote"],
        acceptable_remote_geographies=["United States"],
        remote_preference=RemotePreference.FLEXIBLE,
        target_levels=["director", "senior director", "vice president"],
        target_functions=["platform engineering", "developer experience", "infrastructure"],
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def calibration_verified_facts(candidate_profile_id: UUID) -> list[CareerFactSnapshot]:
    now = utc_now()
    return [
        CareerFactSnapshot(
            id=new_uuid(),
            candidate_profile_id=candidate_profile_id,
            category=CareerFactCategory.PLATFORM,
            source_organization="Example Cloud",
            statement="Built a cloud platform for engineering teams.",
            metric="40% faster delivery",
            technologies=["Python", "Kubernetes"],
            leadership_scope="30 engineers",
            business_outcome="Faster delivery",
            approved_wording="Built a cloud platform for engineering teams with measurable impact.",
            lifecycle_status=CareerFactLifecycle.VERIFIED,
            evidence_tags=[
                EvidenceTag.PLATFORM_ENGINEERING,
                EvidenceTag.DEVELOPER_EXPERIENCE,
                EvidenceTag.CLOUD,
                EvidenceTag.KUBERNETES,
                EvidenceTag.PEOPLE_LEADERSHIP,
                EvidenceTag.CI_CD,
            ],
            provenance_type=ProvenanceType.PROJECT_NOTES,
            source_reference="calibration packet",
            verified_at=now,
            archived_at=None,
            created_at=now,
            updated_at=now,
        )
    ]


def build_synthetic_calibration_subject() -> CalibrationSubject:
    candidate = calibration_candidate()
    return CalibrationSubject(
        candidate=candidate,
        verified_facts=tuple(calibration_verified_facts(candidate.id)),
    )


def load_golden_set(path: Path | None = None) -> CalibrationFixture:
    payload = json.loads((path or GOLDEN_SET_PATH).read_text())
    if not isinstance(payload, dict):
        raise ValueError("Calibration fixture must be an object with metadata and cases.")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError("Calibration fixture must include a list-shaped 'cases' field.")
    metadata = CalibrationFixtureMetadata(
        version=str(payload.get("version", "")),
        fixture_kind=str(payload.get("fixture_kind", "")),
        candidate_profile=str(payload.get("candidate_profile", "")),
        purpose=str(payload.get("purpose", "")),
    )
    cases: list[GoldenSetCase] = []
    for item in raw_cases:
        if not isinstance(item, dict):
            raise ValueError("Each calibration fixture case must be an object.")
        cases.append(
            GoldenSetCase(
                case_id=str(item["case_id"]),
                title=str(item["title"]),
                company=str(item["company"]),
                description=str(item["description"]),
                location_text=item.get("location_text"),
                workplace_type=(
                    WorkplaceType(item["workplace_type"]) if item.get("workplace_type") else None
                ),
                expected_bucket=str(item["expected_bucket"]),
                expected_min_score=float(item["expected_min_score"])
                if item.get("expected_min_score") is not None
                else None,
                expected_max_score=float(item["expected_max_score"])
                if item.get("expected_max_score") is not None
                else None,
                expected_ordering_group=(
                    str(item["expected_ordering_group"])
                    if item.get("expected_ordering_group")
                    else None
                ),
                rationale=str(item["rationale"]) if item.get("rationale") else None,
            )
        )
    _validate_fixture_metadata(metadata)
    _validate_fixture_cases(cases)
    return CalibrationFixture(metadata=metadata, cases=cases)


def run_scoring_calibration(path: Path | None = None) -> CalibrationReport:
    fixture = load_golden_set(path)
    subject = build_synthetic_calibration_subject()
    results: list[CalibrationCaseResult] = []
    failures: list[str] = []

    for case in fixture.cases:
        evaluation = evaluate_job_fit(
            subject.candidate,
            _job_from_case(case),
            list(subject.verified_facts),
        )
        parsed_explanation = parse_explanation_sections(evaluation.explanation)
        result = CalibrationCaseResult(
            case=case,
            score=evaluation.overall_score,
            recommendation=evaluation.recommendation,
            scoring_version=evaluation.scoring_version,
            factor_outputs={
                "level_score": evaluation.level_score,
                "technical_alignment_score": evaluation.technical_alignment_score,
                "location_score": evaluation.location_score,
                "leadership_scope_score": evaluation.leadership_scope_score,
                "platform_ownership_score": evaluation.platform_ownership_score,
                "referral_priority_score": evaluation.referral_priority_score,
            },
            concerns=parsed_explanation["Concerns"],
            missing_evidence=parsed_explanation["Missing evidence"],
            matched_evidence=parsed_explanation["Matched verified evidence"],
            positive_signals=parsed_explanation["Positive signals"],
            explanation=evaluation.explanation,
        )
        results.append(result)
        failures.extend(_validate_case_result(result))

    failures.extend(_validate_bucket_ordering(results))
    scoring_versions = {result.scoring_version for result in results}
    scoring_version = sorted(scoring_versions)[0] if scoring_versions else DEFAULT_SCORING_VERSION
    if len(scoring_versions) > 1:
        failures.append(
            f"Calibration produced multiple scoring versions: {sorted(scoring_versions)}"
        )
    return CalibrationReport(
        scoring_version=scoring_version,
        case_results=results,
        failures=failures,
    )


def format_calibration_report(report: CalibrationReport) -> str:
    lines = [
        f"scoring_version={report.scoring_version}",
        f"cases={len(report.case_results)}",
        f"failures={len(report.failures)}",
    ]
    for result in report.case_results:
        lines.append(
            " ".join(
                [
                    f"case_id={result.case.case_id}",
                    f"bucket={result.case.expected_bucket}",
                    f"score={result.score:.2f}",
                    f"recommendation={result.recommendation.value}",
                ]
            )
        )
    if report.failures:
        lines.append("failures:")
        lines.extend(f"- {message}" for message in report.failures)
    return "\n".join(lines)


def parse_explanation_sections(explanation: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {
        "Matched verified evidence": [],
        "Positive signals": [],
        "Concerns": [],
        "Missing evidence": [],
    }
    current_section: str | None = None
    for line in explanation.splitlines():
        if line in {f"{section}:" for section in sections}:
            current_section = line[:-1]
            continue
        if line.startswith("Scoring version:"):
            current_section = None
            continue
        if current_section and line.startswith("- "):
            value = line[2:].strip()
            default_messages = {
                "No verified evidence matched the job signals.",
                "No strong positive signals were identified.",
                "No material concerns were identified.",
                "No major evidence gaps were identified.",
            }
            if value not in default_messages:
                sections[current_section].append(value)
    return sections


def _job_from_case(case: GoldenSetCase) -> JobLeadSnapshot:
    now = utc_now()
    return JobLeadSnapshot(
        id=new_uuid(),
        source="calibration",
        source_url=None,
        external_id=case.case_id,
        company_name=case.company,
        title=case.title,
        location_text=case.location_text,
        workplace_type=case.workplace_type,
        description_raw=case.description,
        description_normalized=case.description,
        compensation_text=None,
        discovered_at=now,
        posting_status=PostingStatus.DISCOVERED,
        created_at=now,
        updated_at=now,
    )


def _validate_case_result(result: CalibrationCaseResult) -> list[str]:
    failures: list[str] = []
    expected_recommendation = BUCKET_TO_RECOMMENDATION[result.case.expected_bucket]
    if result.recommendation is not expected_recommendation:
        failures.append(
            f"Case {result.case.case_id} expected bucket "
            f"{result.case.expected_bucket} but got {result.recommendation.value}."
        )
    if result.case.expected_min_score is not None and result.score < result.case.expected_min_score:
        failures.append(
            f"Case {result.case.case_id} scored {result.score:.2f}, "
            f"below minimum {result.case.expected_min_score:.2f}."
        )
    if result.case.expected_max_score is not None and result.score > result.case.expected_max_score:
        failures.append(
            f"Case {result.case.case_id} scored {result.score:.2f}, "
            f"above maximum {result.case.expected_max_score:.2f}."
        )
    if result.scoring_version != DEFAULT_SCORING_VERSION:
        failures.append(
            f"Case {result.case.case_id} produced scoring version "
            f"{result.scoring_version} instead of {DEFAULT_SCORING_VERSION}."
        )
    return failures


def _validate_fixture_metadata(metadata: CalibrationFixtureMetadata) -> None:
    if metadata.version != EXPECTED_FIXTURE_VERSION:
        raise ValueError(
            "Calibration fixture version must be "
            f"{EXPECTED_FIXTURE_VERSION}, got {metadata.version!r}."
        )
    if metadata.fixture_kind != EXPECTED_FIXTURE_KIND:
        raise ValueError(
            "Calibration fixture kind must be "
            f"{EXPECTED_FIXTURE_KIND}, got {metadata.fixture_kind!r}."
        )
    if metadata.candidate_profile != EXPECTED_CANDIDATE_PROFILE:
        raise ValueError(
            "Calibration fixture candidate_profile must be "
            f"{EXPECTED_CANDIDATE_PROFILE}, got {metadata.candidate_profile!r}."
        )
    if not metadata.purpose.strip():
        raise ValueError("Calibration fixture purpose must not be blank.")


def _validate_fixture_cases(cases: list[GoldenSetCase]) -> None:
    if not cases:
        raise ValueError("Calibration fixture must contain at least one case.")
    seen_case_ids: set[str] = set()
    for case in cases:
        if case.case_id in seen_case_ids:
            raise ValueError(f"Calibration fixture case_id {case.case_id!r} is duplicated.")
        seen_case_ids.add(case.case_id)
        if case.expected_bucket not in BUCKET_TO_RECOMMENDATION:
            raise ValueError(
                f"Calibration fixture case {case.case_id!r} has invalid bucket "
                f"{case.expected_bucket!r}."
            )
        if (
            case.expected_min_score is not None
            and case.expected_max_score is not None
            and case.expected_min_score > case.expected_max_score
        ):
            raise ValueError(
                f"Calibration fixture case {case.case_id!r} has min score above max score."
            )


def _validate_bucket_ordering(results: list[CalibrationCaseResult]) -> list[str]:
    failures: list[str] = []
    grouped: dict[str, list[CalibrationCaseResult]] = {bucket: [] for bucket in BUCKET_ORDER}
    for result in results:
        grouped[result.case.expected_bucket].append(result)
    for higher_index, higher_bucket in enumerate(BUCKET_ORDER[:-1]):
        higher_results = grouped[higher_bucket]
        if not higher_results:
            continue
        for lower_bucket in BUCKET_ORDER[higher_index + 1 :]:
            lower_results = grouped[lower_bucket]
            if not lower_results:
                continue
            weakest_higher = min(higher_results, key=lambda item: item.score)
            strongest_lower = max(lower_results, key=lambda item: item.score)
            if weakest_higher.score < strongest_lower.score:
                failures.append(
                    "Ordering regression: "
                    f"{higher_bucket} case {weakest_higher.case.case_id} "
                    f"({weakest_higher.case.expected_ordering_group or 'ungrouped'}, "
                    f"score {weakest_higher.score:.2f}) fell below "
                    f"{lower_bucket} case {strongest_lower.case.case_id} "
                    f"({strongest_lower.case.expected_ordering_group or 'ungrouped'}, "
                    f"score {strongest_lower.score:.2f})."
                )
    return failures
