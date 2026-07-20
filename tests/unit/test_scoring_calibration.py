from __future__ import annotations

from pathlib import Path

from ai_job_finder.application.job_searches.calibration import (
    EXPECTED_CANDIDATE_PROFILE,
    EXPECTED_FIXTURE_KIND,
    EXPECTED_FIXTURE_VERSION,
    build_synthetic_calibration_subject,
    format_calibration_report,
    load_golden_set,
    parse_explanation_sections,
    run_scoring_calibration,
)
from ai_job_finder.domain.scoring import DEFAULT_SCORING_VERSION


def test_golden_set_loads_from_version_controlled_fixture() -> None:
    fixture = load_golden_set()

    assert fixture.metadata.version == EXPECTED_FIXTURE_VERSION
    assert fixture.metadata.fixture_kind == EXPECTED_FIXTURE_KIND
    assert fixture.metadata.candidate_profile == EXPECTED_CANDIDATE_PROFILE
    assert fixture.cases
    assert fixture.cases[0].case_id == "strong-platform-remote"


def test_golden_set_case_ids_are_unique_and_stable() -> None:
    fixture = load_golden_set()

    case_ids = [case.case_id for case in fixture.cases]

    assert len(case_ids) == len(set(case_ids))
    assert case_ids == [
        "strong-platform-remote",
        "plausible-infra-hybrid",
        "weak-platform-onsite",
        "reject-finance-ops",
    ]


def test_calibration_facts_belong_to_the_calibration_candidate() -> None:
    subject = build_synthetic_calibration_subject()

    assert subject.verified_facts
    assert all(fact.candidate_profile_id == subject.candidate.id for fact in subject.verified_facts)


def test_scoring_calibration_report_exposes_version_and_factor_outputs() -> None:
    report = run_scoring_calibration()

    assert report.scoring_version == DEFAULT_SCORING_VERSION
    assert report.case_results
    assert "level_score" in report.case_results[0].factor_outputs


def test_scoring_calibration_is_deterministic_for_the_smoke_fixture() -> None:
    first = run_scoring_calibration()
    second = run_scoring_calibration()

    assert first.scoring_version == second.scoring_version
    assert [result.case.case_id for result in first.case_results] == [
        result.case.case_id for result in second.case_results
    ]
    assert [result.score for result in first.case_results] == [
        result.score for result in second.case_results
    ]
    assert [result.recommendation for result in first.case_results] == [
        result.recommendation for result in second.case_results
    ]


def test_calibration_separates_missing_evidence_from_concerns() -> None:
    report = run_scoring_calibration()
    weak_case = next(
        item for item in report.case_results if item.case.case_id == "weak-platform-onsite"
    )

    assert weak_case.concerns or weak_case.missing_evidence
    assert weak_case.concerns != weak_case.missing_evidence


def test_parse_explanation_sections_ignores_default_empty_messages() -> None:
    parsed = parse_explanation_sections(
        "\n".join(
            [
                "Scoring version: candidate_evidence_v2",
                "Matched verified evidence:",
                "- No verified evidence matched the job signals.",
                "Positive signals:",
                "- Job level aligns.",
                "Concerns:",
                "- No material concerns were identified.",
                "Missing evidence:",
                "- No major evidence gaps were identified.",
            ]
        )
    )

    assert parsed["Matched verified evidence"] == []
    assert parsed["Positive signals"] == ["Job level aligns."]
    assert parsed["Concerns"] == []
    assert parsed["Missing evidence"] == []


def test_calibration_failure_messages_are_readable(tmp_path: Path) -> None:
    fixture = tmp_path / "golden.json"
    fixture.write_text(
        """
{
    "version": "v1",
    "fixture_kind": "synthetic_smoke",
    "candidate_profile": "synthetic",
    "purpose": "Intentional mismatch fixture",
    "cases": [
        {
            "case_id": "bad-case",
            "title": "Finance Operations Manager",
            "company": "LedgerWorks",
            "description": "Own finance operations reporting.",
            "location_text": "New York, NY",
            "workplace_type": "onsite",
            "expected_bucket": "strong_fit",
            "expected_min_score": 95,
            "expected_max_score": 100,
            "expected_ordering_group": "bad",
            "rationale": "Intentional mismatch"
        }
    ]
}
        """.strip()
    )

    report = run_scoring_calibration(fixture)
    text = format_calibration_report(report)

    assert report.passed is False
    assert "Case bad-case expected bucket strong_fit" in text
