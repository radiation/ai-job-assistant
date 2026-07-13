from __future__ import annotations

from dataclasses import replace

from ai_job_finder.domain.candidate import CandidateProfileSnapshot
from ai_job_finder.domain.common import new_uuid, utc_now
from ai_job_finder.domain.enums import (
    JobLocationEligibilityReason,
    JobLocationEligibilityStatus,
    RemotePreference,
    WorkplaceType,
)
from ai_job_finder.domain.location_eligibility import (
    JobLocationEligibilityResult,
    JobLocationSignals,
    classify_job_location_eligibility,
)


def build_candidate() -> CandidateProfileSnapshot:
    now = utc_now()
    return CandidateProfileSnapshot(
        id=new_uuid(),
        full_name="Candidate",
        preferred_locations=["New York City"],
        acceptable_remote_geographies=["United States"],
        remote_preference=RemotePreference.FLEXIBLE,
        target_levels=["director"],
        target_functions=["platform engineering"],
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def classify(
    signals: JobLocationSignals,
    candidate: CandidateProfileSnapshot | None = None,
) -> JobLocationEligibilityResult:
    return classify_job_location_eligibility(candidate or build_candidate(), signals)


def test_nyc_hybrid_is_eligible_for_preferred_location() -> None:
    result = classify(JobLocationSignals("New York, NY", WorkplaceType.HYBRID))

    assert result.status is JobLocationEligibilityStatus.ELIGIBLE
    assert result.reasons == [JobLocationEligibilityReason.PREFERRED_LOCATION_MATCH]


def test_nyc_onsite_is_eligible_for_preferred_location() -> None:
    result = classify(JobLocationSignals("NYC", WorkplaceType.ONSITE))

    assert result.status is JobLocationEligibilityStatus.ELIGIBLE
    assert result.reasons == [JobLocationEligibilityReason.PREFERRED_LOCATION_MATCH]


def test_edinburgh_hybrid_is_ineligible_without_approved_market() -> None:
    result = classify(JobLocationSignals("Edinburgh", WorkplaceType.HYBRID))

    assert result.status is JobLocationEligibilityStatus.INELIGIBLE
    assert result.reasons == [JobLocationEligibilityReason.INTERNATIONAL_LOCATION_NOT_APPROVED]


def test_edinburgh_hybrid_suffix_is_not_treated_as_multiple_locations() -> None:
    result = classify(JobLocationSignals("Edinburgh / Hybrid", WorkplaceType.HYBRID))

    assert result.status is JobLocationEligibilityStatus.INELIGIBLE
    assert result.reasons == [JobLocationEligibilityReason.INTERNATIONAL_LOCATION_NOT_APPROVED]


def test_new_york_hybrid_suffix_is_eligible() -> None:
    result = classify(JobLocationSignals("New York / Hybrid", WorkplaceType.HYBRID))

    assert result.status is JobLocationEligibilityStatus.ELIGIBLE
    assert result.reasons == [JobLocationEligibilityReason.PREFERRED_LOCATION_MATCH]


def test_new_york_onsite_suffix_is_eligible() -> None:
    result = classify(JobLocationSignals("New York | Onsite", WorkplaceType.ONSITE))

    assert result.status is JobLocationEligibilityStatus.ELIGIBLE
    assert result.reasons == [JobLocationEligibilityReason.PREFERRED_LOCATION_MATCH]


def test_remote_us_is_eligible_with_configured_remote_geography() -> None:
    result = classify(JobLocationSignals("Remote - US", WorkplaceType.REMOTE))

    assert result.status is JobLocationEligibilityStatus.ELIGIBLE
    assert result.reasons == [JobLocationEligibilityReason.REMOTE_GEOGRAPHY_MATCH]


def test_remote_us_suffix_is_eligible() -> None:
    result = classify(JobLocationSignals("Remote / United States", WorkplaceType.REMOTE))

    assert result.status is JobLocationEligibilityStatus.ELIGIBLE
    assert result.reasons == [JobLocationEligibilityReason.REMOTE_GEOGRAPHY_MATCH]


def test_remote_us_needs_review_without_configured_remote_geography() -> None:
    candidate = replace(build_candidate(), acceptable_remote_geographies=[])

    result = classify(JobLocationSignals("Remote - US", WorkplaceType.REMOTE), candidate)

    assert result.status is JobLocationEligibilityStatus.NEEDS_REVIEW
    assert result.reasons == [
        JobLocationEligibilityReason.CANDIDATE_REMOTE_GEOGRAPHY_NOT_CONFIGURED
    ]


def test_generic_remote_needs_review() -> None:
    result = classify(JobLocationSignals("Remote", WorkplaceType.REMOTE))

    assert result.status is JobLocationEligibilityStatus.NEEDS_REVIEW
    assert result.reasons == [JobLocationEligibilityReason.REMOTE_GEOGRAPHY_UNCLEAR]


def test_missing_location_and_workplace_needs_review() -> None:
    result = classify(JobLocationSignals(None, None))

    assert result.status is JobLocationEligibilityStatus.NEEDS_REVIEW
    assert result.reasons == [JobLocationEligibilityReason.MISSING_LOCATION_DATA]


def test_missing_workplace_type_needs_review() -> None:
    result = classify(JobLocationSignals("New York, NY", None))

    assert result.status is JobLocationEligibilityStatus.NEEDS_REVIEW
    assert result.reasons == [JobLocationEligibilityReason.MISSING_WORKPLACE_TYPE]


def test_conflicting_signals_need_review() -> None:
    result = classify(JobLocationSignals("Remote", WorkplaceType.HYBRID))

    assert result.status is JobLocationEligibilityStatus.NEEDS_REVIEW
    assert result.reasons == [JobLocationEligibilityReason.CONFLICTING_LOCATION_SIGNALS]


def test_broad_region_needs_review() -> None:
    result = classify(JobLocationSignals("Europe", WorkplaceType.REMOTE))

    assert result.status is JobLocationEligibilityStatus.NEEDS_REVIEW
    assert result.reasons == [JobLocationEligibilityReason.BROAD_REGION_REQUIRES_REVIEW]


def test_international_location_outside_approved_geography_is_ineligible() -> None:
    result = classify(JobLocationSignals("Remote - United Kingdom", WorkplaceType.REMOTE))

    assert result.status is JobLocationEligibilityStatus.INELIGIBLE
    assert result.reasons == [JobLocationEligibilityReason.INTERNATIONAL_LOCATION_NOT_APPROVED]


def test_multiple_locations_including_approved_market_need_review() -> None:
    result = classify(JobLocationSignals("New York / Edinburgh", WorkplaceType.HYBRID))

    assert result.status is JobLocationEligibilityStatus.NEEDS_REVIEW
    assert result.reasons == [JobLocationEligibilityReason.MULTIPLE_LOCATIONS_REQUIRE_REVIEW]


def test_multiple_locations_with_pipe_still_need_review() -> None:
    result = classify(JobLocationSignals("New York | London", WorkplaceType.HYBRID))

    assert result.status is JobLocationEligibilityStatus.NEEDS_REVIEW
    assert result.reasons == [JobLocationEligibilityReason.MULTIPLE_LOCATIONS_REQUIRE_REVIEW]


def test_multiple_offices_including_approved_market_need_review() -> None:
    result = classify(
        JobLocationSignals(
            "New York",
            WorkplaceType.HYBRID,
            offices=["New York", "Edinburgh"],
        )
    )

    assert result.status is JobLocationEligibilityStatus.NEEDS_REVIEW
    assert result.reasons == [JobLocationEligibilityReason.MULTIPLE_LOCATIONS_REQUIRE_REVIEW]
