from __future__ import annotations

from pathlib import Path

from ai_job_finder.application.job_searches.calibration import (
    EXPECTED_CANDIDATE_PROFILE,
    EXPECTED_FIXTURE_KIND,
    EXPECTED_FIXTURE_VERSION,
    _job_from_case,
    build_synthetic_calibration_subject,
    format_calibration_report,
    load_golden_set,
    parse_explanation_sections,
    run_scoring_calibration,
)
from ai_job_finder.domain.enums import WorkplaceType
from ai_job_finder.domain.job_searches import (
    JobSearchDefinitionSnapshot,
    JobSearchDomain,
    JobSearchSeniority,
    evaluate_job_search_match,
)
from ai_job_finder.domain.scoring import DEFAULT_SCORING_VERSION, evaluate_job_fit

ROLE_FAMILY_CALIBRATION_PATH = Path("tests/fixtures/scoring/role_family_calibration_v1.json")


def test_golden_set_loads_from_version_controlled_fixture() -> None:
    fixture = load_golden_set()

    assert fixture.metadata.version == EXPECTED_FIXTURE_VERSION
    assert fixture.metadata.fixture_kind == EXPECTED_FIXTURE_KIND
    assert fixture.metadata.candidate_profile == EXPECTED_CANDIDATE_PROFILE
    assert fixture.cases
    assert fixture.cases[0].case_id == "strong-platform-remote"
    assert fixture.cases[0].expected_match is True


def test_golden_set_case_ids_are_unique_and_stable() -> None:
    fixture = load_golden_set()

    case_ids = [case.case_id for case in fixture.cases]

    assert len(case_ids) == len(set(case_ids))
    assert len(case_ids) == 29
    assert "hardware-ai-infrastructure-director" in case_ids
    assert "eu-platform-director" in case_ids


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
    "fixture_kind": "discovery_match_calibration",
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


def test_discovery_match_calibration_corpus_has_expected_outcomes_and_ordering() -> None:
    fixture = load_golden_set()
    subject = build_synthetic_calibration_subject()
    definition = JobSearchDefinitionSnapshot(
        id=subject.candidate.id,
        name="Director+ Platform / DevEx",
        enabled=True,
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
        allowed_remote_geographies=["United States"],
        allowed_workplace_types=[
            WorkplaceType.REMOTE,
            WorkplaceType.HYBRID,
            WorkplaceType.ONSITE,
        ],
        minimum_score_threshold=65,
    )
    results = {}
    for case in fixture.cases:
        job = _job_from_case(case)
        evaluation = evaluate_job_fit(subject.candidate, job, list(subject.verified_facts))
        result = evaluate_job_search_match(definition, job, evaluation)
        results[case.case_id] = (evaluation, result)
        assert [domain.value for domain in result.inferred_domains] == case.expected_domains
        assert [
            level.value for level in result.inferred_seniority_levels
        ] == case.expected_seniority
        assert result.matched is case.expected_match
        assert (
            round(
                sum(component.weighted_score for component in result.explanation.score_components),
                2,
            )
            == result.explanation.score
        )

    assert (
        results["director-cloud-platform"][0].overall_score
        > results["hardware-ai-infrastructure-director"][0].overall_score
    )
    assert (
        results["director-developer-experience"][0].overall_score
        > results["senior-platform-engineer"][0].overall_score
    )
    assert (
        results["vp-software-platform"][0].overall_score
        > results["sales-enablement-director"][0].overall_score
    )


def test_role_family_calibration_corpus_has_expected_outcomes_and_ordering() -> None:
    fixture = load_golden_set(ROLE_FAMILY_CALIBRATION_PATH)
    subject = build_synthetic_calibration_subject()
    definition = JobSearchDefinitionSnapshot(
        id=subject.candidate.id,
        name="Director+ Platform / DevEx",
        enabled=True,
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
        allowed_remote_geographies=["United States"],
        allowed_workplace_types=[
            WorkplaceType.REMOTE,
            WorkplaceType.HYBRID,
            WorkplaceType.ONSITE,
        ],
        minimum_score_threshold=65,
    )

    results = {}
    for case in fixture.cases:
        job = _job_from_case(case)
        evaluation = evaluate_job_fit(subject.candidate, job, list(subject.verified_facts))
        result = evaluate_job_search_match(definition, job, evaluation)
        results[case.case_id] = (evaluation, result)
        assert case.expected_min_score is not None
        assert case.expected_max_score is not None
        assert case.expected_min_score <= evaluation.overall_score <= case.expected_max_score
        assert [domain.value for domain in result.inferred_domains] == case.expected_domains
        assert [level.value for level in result.inferred_seniority_levels] == (
            case.expected_seniority
        )
        assert result.matched is case.expected_match
        assert round(sum(item.weighted_score for item in evaluation.score_components), 2) == (
            evaluation.overall_score
        )

    assert (
        results["director-data-platform"][0].overall_score
        > results["director-engineering-data"][0].overall_score
    )
    core_platform = evaluate_job_fit(
        subject.candidate,
        _job_from_case(load_golden_set().cases[0]),
        list(subject.verified_facts),
    )
    for case_id in (
        "director-silicon-logical-design",
        "director-asic-design",
        "director-semiconductor-engineering",
        "director-hardware-architecture",
        "director-revenue-systems",
        "senior-director-sales-systems",
        "director-gtm-systems",
        "director-crm-systems",
        "director-business-systems",
    ):
        assert core_platform.overall_score > results[case_id][0].overall_score
