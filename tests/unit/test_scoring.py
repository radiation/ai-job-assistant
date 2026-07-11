from __future__ import annotations

from dataclasses import replace

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
from ai_job_finder.domain.scoring import evaluate_job_fit


def build_candidate() -> CandidateProfileSnapshot:
    now = utc_now()
    return CandidateProfileSnapshot(
        id=new_uuid(),
        full_name="Candidate",
        preferred_locations=["Seattle"],
        remote_preference=RemotePreference.FLEXIBLE,
        target_levels=["director"],
        target_functions=["platform engineering"],
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def build_fact() -> CareerFactSnapshot:
    now = utc_now()
    return CareerFactSnapshot(
        id=new_uuid(),
        candidate_profile_id=new_uuid(),
        category=CareerFactCategory.PLATFORM,
        source_organization="Example",
        statement="Built platform",
        metric="20% faster",
        technologies=["Python"],
        leadership_scope="20 engineers",
        business_outcome="Faster delivery",
        approved_wording="Built platform",
        lifecycle_status=CareerFactLifecycle.VERIFIED,
        evidence_tags=[EvidenceTag.PLATFORM_ENGINEERING, EvidenceTag.PEOPLE_LEADERSHIP],
        provenance_type=ProvenanceType.PROJECT_NOTES,
        source_reference="doc",
        verified_at=now,
        archived_at=None,
        created_at=now,
        updated_at=now,
    )


def build_job() -> JobLeadSnapshot:
    now = utc_now()
    return JobLeadSnapshot(
        id=new_uuid(),
        source="manual",
        source_url=None,
        external_id="abc",
        company_name="Northstar",
        title="Director, Platform Engineering",
        location_text="Seattle, WA",
        workplace_type=WorkplaceType.HYBRID,
        description_raw="Own the developer platform strategy and roadmap.",
        description_normalized=(
            "Own the developer platform strategy and roadmap for the engineering "
            "organization and lead teams building self-service infrastructure."
        ),
        compensation_text=None,
        discovered_at=now,
        posting_status=PostingStatus.DISCOVERED,
        created_at=now,
        updated_at=now,
    )


def test_scoring_outputs_components_and_explanation() -> None:
    evaluation = evaluate_job_fit(build_candidate(), build_job(), [build_fact()])

    assert evaluation.level_score == 100
    assert evaluation.location_score >= 70
    assert evaluation.platform_ownership_score >= 45
    assert evaluation.leadership_scope_score >= 60
    assert evaluation.technical_alignment_score >= 60
    assert "Scoring version: candidate_evidence_v2" in evaluation.explanation
    assert "Matched verified evidence:" in evaluation.explanation
    assert "Positive signals:" in evaluation.explanation
    assert "Concerns:" in evaluation.explanation
    assert "Missing evidence:" in evaluation.explanation


def test_overall_score_and_recommendation_thresholds() -> None:
    evaluation = evaluate_job_fit(build_candidate(), build_job(), [build_fact()])

    assert evaluation.overall_score >= 80
    assert evaluation.recommendation is Recommendation.STRONG_RECOMMEND
    assert evaluation.scoring_version == "candidate_evidence_v2"


def test_unverified_facts_do_not_count_as_usable() -> None:
    fact = build_fact()
    rejected_fact = replace(
        fact,
        lifecycle_status=CareerFactLifecycle.DRAFT,
        verified_at=None,
    )

    evaluation = evaluate_job_fit(build_candidate(), build_job(), [rejected_fact])

    assert "No verified career facts are available yet" in evaluation.explanation


def test_archived_facts_do_not_count_as_usable() -> None:
    fact = replace(
        build_fact(),
        lifecycle_status=CareerFactLifecycle.ARCHIVED,
        archived_at=utc_now(),
    )

    evaluation = evaluate_job_fit(build_candidate(), build_job(), [fact])

    assert "No verified career facts are available yet" in evaluation.explanation


def test_missing_evidence_is_reported_when_job_signals_exceed_verified_tags() -> None:
    fact = replace(build_fact(), evidence_tags=[EvidenceTag.PLATFORM_ENGINEERING])
    job = replace(
        build_job(),
        description_normalized=(
            "Own platform strategy with Kubernetes, CI/CD, observability, and global operations."
        ),
    )

    evaluation = evaluate_job_fit(build_candidate(), job, [fact])

    assert "Missing evidence:" in evaluation.explanation
    assert "CI/CD" in evaluation.explanation or "reliability" in evaluation.explanation.lower()


def test_matched_evidence_is_deduplicated_when_one_fact_matches_multiple_rules() -> None:
    fact = replace(
        build_fact(),
        approved_wording="Built platform with strong cloud and CI/CD outcomes",
        evidence_tags=[
            EvidenceTag.PLATFORM_ENGINEERING,
            EvidenceTag.CLOUD,
            EvidenceTag.CI_CD,
        ],
    )
    job = replace(
        build_job(),
        description_normalized=(
            "Own the developer platform strategy, improve cloud foundations, and "
            "lead CI/CD modernization for the engineering organization."
        ),
    )

    evaluation = evaluate_job_fit(build_candidate(), job, [fact])

    assert (
        evaluation.explanation.count(
            "- Built platform with strong cloud and CI/CD outcomes [ci_cd, cloud, "
            "platform_engineering]"
        )
        == 1
    )
