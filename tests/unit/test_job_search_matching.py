from __future__ import annotations

from uuid import UUID

from ai_job_finder.domain.common import new_uuid, utc_now
from ai_job_finder.domain.enums import (
    JobLocationEligibilityReason,
    JobLocationEligibilityStatus,
    PostingStatus,
    Recommendation,
    WorkplaceType,
)
from ai_job_finder.domain.evaluation import EvaluationResult, ScoreComponent
from ai_job_finder.domain.job_lead import JobLeadSnapshot
from ai_job_finder.domain.job_searches import (
    JobSearchDefinitionSnapshot,
    JobSearchDomain,
    JobSearchExclusionReason,
    JobSearchLocationContext,
    JobSearchSeniority,
    evaluate_job_search_match,
)
from ai_job_finder.domain.job_searches.matching import normalize_search_text
from ai_job_finder.domain.location_eligibility import JobLocationEligibilityResult
from ai_job_finder.domain.scoring import recommendation_minimum_score


def _job(
    *,
    title: str = "Senior Director, Platform Engineering",
    location_text: str | None = "Remote United States",
    workplace_type: WorkplaceType | None = WorkplaceType.REMOTE,
    description: str = (
        "Lead platform engineering, developer experience, cloud infrastructure, and "
        "engineering productivity."
    ),
) -> JobLeadSnapshot:
    now = utc_now()
    return JobLeadSnapshot(
        id=new_uuid(),
        source="greenhouse",
        source_url="https://example.com/jobs/1",
        external_id="job-1",
        company_name="Acme",
        title=title,
        location_text=location_text,
        workplace_type=workplace_type,
        description_raw=description,
        description_normalized=description,
        compensation_text=None,
        discovered_at=now,
        posting_status=PostingStatus.DISCOVERED,
        created_at=now,
        updated_at=now,
    )


def _evaluation(
    score: float = 88.0,
    recommendation: Recommendation = Recommendation.STRONG_RECOMMEND,
) -> EvaluationResult:
    now = utc_now()
    return EvaluationResult(
        id=new_uuid(),
        candidate_profile_id=new_uuid(),
        job_lead_id=new_uuid(),
        scoring_version="candidate_evidence_v5",
        leadership_scope_score=80,
        technical_alignment_score=90,
        location_score=85,
        level_score=90,
        platform_ownership_score=88,
        referral_priority_score=0,
        overall_score=score,
        recommendation=recommendation,
        explanation="Scoring version: candidate_evidence_v2",
        evaluated_at=now,
        score_components=(
            ScoreComponent(
                name="leadership_scope",
                score=80,
                weight=0.2,
                weighted_score=16,
            ),
        ),
    )


def _search_definition(
    *,
    search_definition_id: UUID | None = None,
    name: str = "Platform roles",
    enabled: bool = True,
    title_include_patterns: list[str] | None = None,
    title_exclude_patterns: list[str] | None = None,
    target_domains: list[JobSearchDomain] | None = None,
    target_seniority_levels: list[JobSearchSeniority] | None = None,
    allowed_locations: list[str] | None = None,
    allowed_remote_geographies: list[str] | None = None,
    allowed_workplace_types: list[WorkplaceType] | None = None,
    minimum_score_threshold: float = 75.0,
) -> JobSearchDefinitionSnapshot:
    return JobSearchDefinitionSnapshot(
        id=new_uuid() if search_definition_id is None else search_definition_id,
        name=name,
        enabled=enabled,
        title_include_patterns=(
            ["platform engineering"] if title_include_patterns is None else title_include_patterns
        ),
        title_exclude_patterns=(
            ["finance"] if title_exclude_patterns is None else title_exclude_patterns
        ),
        target_domains=(
            [JobSearchDomain.PLATFORM_ENGINEERING] if target_domains is None else target_domains
        ),
        target_seniority_levels=(
            [JobSearchSeniority.SENIOR_DIRECTOR]
            if target_seniority_levels is None
            else target_seniority_levels
        ),
        allowed_locations=[] if allowed_locations is None else allowed_locations,
        allowed_remote_geographies=(
            ["United States"] if allowed_remote_geographies is None else allowed_remote_geographies
        ),
        allowed_workplace_types=(
            [WorkplaceType.REMOTE] if allowed_workplace_types is None else allowed_workplace_types
        ),
        minimum_score_threshold=minimum_score_threshold,
        created_at=utc_now(),
        updated_at=utc_now(),
    )


def test_normalize_search_text_is_explicit_and_stable() -> None:
    assert normalize_search_text(" Senior Director, Platform-Engineering ") == (
        "senior director platform engineering"
    )


def test_saved_search_match_captures_title_domain_seniority_location_and_threshold() -> None:
    result = evaluate_job_search_match(_search_definition(), _job(), _evaluation())

    assert result.matched is True
    assert result.criteria_matched is True
    assert result.above_threshold is True
    assert result.matched_criteria["title_include_patterns"] == ["platform engineering"]
    assert result.matched_criteria["target_domains"] == ["platform_engineering"]
    assert result.matched_criteria["target_seniority_levels"] == ["senior_director"]
    assert "remote" in result.matched_criteria["location"]
    assert result.explanation.outcome == "matched"
    assert result.explanation.score_components[0].name == "leadership_scope"
    assert result.explanation.actionable is True


def test_title_exclude_patterns_override_include_patterns() -> None:
    result = evaluate_job_search_match(
        _search_definition(title_exclude_patterns=["platform engineering"]),
        _job(),
        _evaluation(),
    )

    assert result.matched is False
    assert "Job title matched an exclude pattern." in result.exclusion_reasons
    assert JobSearchExclusionReason.TITLE_EXCLUDED in result.exclusion_reason_codes


def test_domain_matching_fails_when_no_domain_signal_is_present() -> None:
    result = evaluate_job_search_match(
        _search_definition(target_domains=[JobSearchDomain.AI_PLATFORM]),
        _job(description="Own finance systems and accounting operations."),
        _evaluation(),
    )

    assert result.criteria_matched is False
    assert "Job domain signals did not match the saved-search domains." in result.exclusion_reasons
    assert JobSearchExclusionReason.ROLE_FAMILY_MISMATCH in result.exclusion_reason_codes


def test_cybersecurity_title_is_excluded_from_platform_domains() -> None:
    result = evaluate_job_search_match(
        _search_definition(title_include_patterns=[]),
        _job(
            title="Director of Cybersecurity Platform Engineering",
            description="Lead platform engineering and cloud infrastructure for security teams.",
        ),
        _evaluation(),
    )

    assert result.criteria_matched is False
    assert result.inferred_domains == []
    assert JobSearchExclusionReason.ROLE_FAMILY_MISMATCH in result.exclusion_reason_codes


def test_hardware_and_revenue_systems_titles_are_role_family_mismatches() -> None:
    for title in (
        "Director, Silicon Logical Design",
        "Director, ASIC Design",
        "Director, Semiconductor Engineering",
        "Director, Hardware Architecture",
        "Director, Revenue Systems",
        "Senior Director, Sales Systems",
        "Director, GTM Systems",
        "Director, CRM Systems",
        "Director, Business Systems",
    ):
        result = evaluate_job_search_match(
            _search_definition(title_include_patterns=[]),
            _job(title=title, description="Lead platform engineering and developer productivity."),
            _evaluation(),
        )

        assert result.matched is False
        assert result.inferred_domains == []
        assert JobSearchExclusionReason.ROLE_FAMILY_MISMATCH in result.exclusion_reason_codes


def test_data_platform_retains_platform_credit_while_generic_data_does_not() -> None:
    definition = _search_definition(
        title_include_patterns=[],
        target_domains=[JobSearchDomain.PLATFORM_ENGINEERING],
        target_seniority_levels=[JobSearchSeniority.DIRECTOR],
    )
    data_platform = evaluate_job_search_match(
        definition,
        _job(title="Director, Data Platform", description="Lead data platform engineering."),
        _evaluation(),
    )
    assert data_platform.matched is True
    assert JobSearchDomain.PLATFORM_ENGINEERING in data_platform.inferred_domains
    for description in (
        "Lead data platform engineering and data infrastructure.",
        "Lead data infrastructure engineering and data governance.",
        "Lead analytics platform engineering and data governance.",
    ):
        generic_data = evaluate_job_search_match(
            definition,
            _job(title="Director of Engineering, Data", description=description),
            _evaluation(),
        )

        assert generic_data.matched is False
        assert generic_data.inferred_domains == [JobSearchDomain.DATA_PLATFORM]
        assert JobSearchExclusionReason.ROLE_FAMILY_MISMATCH in generic_data.exclusion_reason_codes


def test_data_and_ml_platform_remain_adjacent_while_ai_platform_is_a_direct_target() -> None:
    definition = _search_definition(
        title_include_patterns=[],
        target_domains=[JobSearchDomain.PLATFORM_ENGINEERING],
        target_seniority_levels=[JobSearchSeniority.DIRECTOR],
    )
    for title in ("Director, Data Platform", "Director, ML Platform"):
        result = evaluate_job_search_match(
            definition,
            _job(title=title, description="Lead platform engineering and self-service services."),
            _evaluation(),
        )

        assert result.matched is True
        assert JobSearchDomain.PLATFORM_ENGINEERING in result.inferred_domains


def test_cloud_reliability_remains_an_infrastructure_role_family_match() -> None:
    result = evaluate_job_search_match(
        _search_definition(
            title_include_patterns=[],
            target_domains=[JobSearchDomain.INFRASTRUCTURE],
            target_seniority_levels=[JobSearchSeniority.DIRECTOR],
        ),
        _job(
            title="Director of Engineering, Cloud & Reliability",
            description="Lead cloud infrastructure and reliability engineering.",
        ),
        _evaluation(),
    )

    assert result.matched is True
    assert JobSearchDomain.INFRASTRUCTURE in result.inferred_domains


def test_ci_cd_platform_text_uses_normalized_domain_variants() -> None:
    result = evaluate_job_search_match(
        _search_definition(
            title_include_patterns=[],
            target_domains=[
                JobSearchDomain.PLATFORM_ENGINEERING,
                JobSearchDomain.ENGINEERING_PRODUCTIVITY,
            ],
        ),
        _job(
            title="Senior Director, Delivery Engineering",
            description="Lead CI/CD platform and CI/CD tooling for engineering teams.",
        ),
        _evaluation(),
    )

    assert result.criteria_matched is True
    assert [domain.value for domain in result.inferred_domains] == [
        "platform_engineering",
        "engineering_productivity",
    ]


def test_seniority_matching_uses_normalized_title_signals() -> None:
    result = evaluate_job_search_match(
        _search_definition(target_seniority_levels=[JobSearchSeniority.VICE_PRESIDENT]),
        _job(title="VP Platform Engineering"),
        _evaluation(),
    )

    assert result.criteria_matched is True
    assert result.matched_criteria["target_seniority_levels"] == ["vice_president"]


def test_remote_geography_must_match_saved_search_when_configured() -> None:
    result = evaluate_job_search_match(
        _search_definition(allowed_remote_geographies=["United Kingdom"]),
        _job(location_text="Remote United States"),
        _evaluation(),
    )

    assert result.criteria_matched is False
    assert "Remote role geography does not match the saved search." in result.exclusion_reasons
    assert JobSearchExclusionReason.REMOTE_GEOGRAPHY_MISMATCH in result.exclusion_reason_codes


def test_presence_required_roles_match_allowed_locations() -> None:
    result = evaluate_job_search_match(
        _search_definition(
            allowed_workplace_types=[WorkplaceType.HYBRID],
            allowed_locations=["Seattle"],
            allowed_remote_geographies=[],
        ),
        _job(location_text="Seattle, WA", workplace_type=WorkplaceType.HYBRID),
        _evaluation(),
        location_context=JobSearchLocationContext(
            location_text="Seattle, WA",
            workplace_type=WorkplaceType.HYBRID,
        ),
    )

    assert result.criteria_matched is True
    assert "seattle wa" in result.matched_criteria["location"]


def test_score_threshold_is_separate_from_criteria_matching() -> None:
    result = evaluate_job_search_match(
        _search_definition(minimum_score_threshold=90.0),
        _job(),
        _evaluation(82.0),
    )

    assert result.criteria_matched is True
    assert result.above_threshold is False
    assert result.matched is False
    assert (
        "Job evaluation score is below the saved-search minimum threshold."
        in result.exclusion_reasons
    )
    assert result.explanation.score == 82.0
    assert result.explanation.match_threshold == 90.0
    assert JobSearchExclusionReason.BELOW_MATCH_THRESHOLD in result.exclusion_reason_codes


def test_missing_evaluation_is_reported_explicitly() -> None:
    result = evaluate_job_search_match(_search_definition(), _job(), None)

    assert result.matched is False
    assert result.criteria_matched is True
    assert (
        "Job has no evaluation for saved-search threshold comparison." in result.exclusion_reasons
    )
    assert JobSearchExclusionReason.EVALUATION_MISSING in result.exclusion_reason_codes


def test_needs_review_location_is_distinct_from_saved_search_matching() -> None:
    result = evaluate_job_search_match(
        _search_definition(),
        _job(),
        _evaluation(),
        location_eligibility=JobLocationEligibilityResult(
            status=JobLocationEligibilityStatus.NEEDS_REVIEW,
            reasons=[JobLocationEligibilityReason.REMOTE_GEOGRAPHY_UNCLEAR],
            summary="Remote role does not state a clear eligible geography.",
        ),
    )

    assert result.matched is True
    assert result.explanation.location_eligibility is not None
    assert result.explanation.to_payload()["location_eligibility"] == {
        "status": "needs_review",
        "reason_codes": ["remote_geography_unclear"],
        "summary": "Remote role does not state a clear eligible geography.",
    }


def test_match_threshold_and_actionable_threshold_are_distinct() -> None:
    result = evaluate_job_search_match(
        _search_definition(minimum_score_threshold=60.0),
        _job(),
        _evaluation(64.0, recommendation=Recommendation.HOLD),
    )

    assert result.matched is True
    assert result.explanation.match_threshold == 60.0
    assert result.explanation.actionable_threshold == recommendation_minimum_score(
        Recommendation.RECOMMEND
    )
    assert result.explanation.actionable is False
