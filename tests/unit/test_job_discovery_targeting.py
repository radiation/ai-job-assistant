from __future__ import annotations

from ai_job_finder.domain.job_discovery.targeting import discovery_result_index_reason


def test_discovery_result_filter_preserves_supported_ats_urls() -> None:
    assert (
        discovery_result_index_reason(
            "https://jobs.lever.co/acme/search",
            title_hint="Search jobs",
        )
        is None
    )


def test_discovery_result_filter_preserves_employer_and_individual_third_party_job_pages() -> None:
    assert (
        discovery_result_index_reason(
            "https://careers.example.com/jobs/director-platform-engineering",
            title_hint="Director, Platform Engineering",
        )
        is None
    )
    assert (
        discovery_result_index_reason(
            "https://third-party.example/jobs/12345",
            title_hint="Director, Platform Engineering at Acme",
        )
        is None
    )


def test_discovery_result_filter_excludes_clear_generic_index_shapes() -> None:
    assert (
        discovery_result_index_reason(
            "https://jobs.example.com/search?query=platform",
            title_hint="Search platform jobs",
        )
        == "Excluded generic search result before source detection."
    )
    assert (
        discovery_result_index_reason(
            "https://jobs.example.com/jobs/search/platform-engineering",
            title_hint="Platform jobs",
        )
        == "Excluded generic job-search result before source detection."
    )
    assert (
        discovery_result_index_reason(
            "https://jobs.example.com/categories/platform",
            title_hint="Best platform engineering jobs",
        )
        == "Excluded generic jobs-list result before source detection."
    )
