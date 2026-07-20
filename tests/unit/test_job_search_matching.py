from __future__ import annotations

from uuid import UUID

from ai_job_finder.domain.common import new_uuid, utc_now
from ai_job_finder.domain.enums import PostingStatus, Recommendation, WorkplaceType
from ai_job_finder.domain.evaluation import EvaluationResult
from ai_job_finder.domain.job_lead import JobLeadSnapshot
from ai_job_finder.domain.job_searches import (
    JobSearchDefinitionSnapshot,
    JobSearchDomain,
    JobSearchLocationContext,
    JobSearchSeniority,
    evaluate_job_search_match,
)
from ai_job_finder.domain.job_searches.matching import normalize_search_text


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


def _evaluation(score: float = 88.0) -> EvaluationResult:
    now = utc_now()
    return EvaluationResult(
        id=new_uuid(),
        candidate_profile_id=new_uuid(),
        job_lead_id=new_uuid(),
        scoring_version="candidate_evidence_v2",
        leadership_scope_score=80,
        technical_alignment_score=90,
        location_score=85,
        level_score=90,
        platform_ownership_score=88,
        referral_priority_score=0,
        overall_score=score,
        recommendation=Recommendation.STRONG_RECOMMEND,
        explanation="Scoring version: candidate_evidence_v2",
        evaluated_at=now,
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


def test_title_exclude_patterns_override_include_patterns() -> None:
    result = evaluate_job_search_match(
        _search_definition(title_exclude_patterns=["platform engineering"]),
        _job(),
        _evaluation(),
    )

    assert result.matched is False
    assert "Job title matched an exclude pattern." in result.exclusion_reasons


def test_domain_matching_fails_when_no_domain_signal_is_present() -> None:
    result = evaluate_job_search_match(
        _search_definition(target_domains=[JobSearchDomain.AI_PLATFORM]),
        _job(description="Own finance systems and accounting operations."),
        _evaluation(),
    )

    assert result.criteria_matched is False
    assert "Job domain signals did not match the saved-search domains." in result.exclusion_reasons


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


def test_missing_evaluation_is_reported_explicitly() -> None:
    result = evaluate_job_search_match(_search_definition(), _job(), None)

    assert result.matched is False
    assert result.criteria_matched is True
    assert (
        "Job has no evaluation for saved-search threshold comparison." in result.exclusion_reasons
    )
