from __future__ import annotations

import re

from ai_job_finder.domain.job_lead import JobLeadSnapshot

_DOMAIN_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "platform_engineering",
        (
            "platform engineering",
            "cloud platform",
            "infrastructure platform",
            "developer platform",
            "internal developer platform",
            "internal platform",
            "developer infrastructure",
            "build platform",
            "ci cd platform",
            "cicd platform",
            "software engineering platform",
            "data platform",
            "data infrastructure",
            "ml platform",
            "machine learning platform",
        ),
    ),
    (
        "developer_experience",
        ("developer experience", "devex", "developer enablement", "developer tools"),
    ),
    (
        "infrastructure",
        (
            "infrastructure engineering",
            "cloud infrastructure",
            "reliability engineering",
            "site reliability",
        ),
    ),
    (
        "engineering_productivity",
        (
            "engineering productivity",
            "developer productivity",
            "productivity engineering",
            "build systems",
            "build tooling",
            "ci cd",
            "cicd",
        ),
    ),
    ("ai_platform", ("ai platform", "ml platform", "machine learning platform")),
    ("data_platform", ("data platform", "data infrastructure", "analytics platform")),
    (
        "shared_services",
        (
            "engineering shared services",
            "shared engineering services",
            "platform shared services",
            "technical shared services",
        ),
    ),
)

_EXCLUDED_TARGET_FUNCTION_TITLE_TERMS = (
    "hardware",
    "hardware architecture",
    "firmware",
    "embedded",
    "electrical",
    "mechanical",
    "silicon",
    "asic",
    "semiconductor",
    "rtl",
    "logical design",
    "chip design",
    "physical infrastructure",
    "facilities",
    "it security",
    "cyber security",
    "cybersecurity",
    "information security",
    "sales enablement",
    "revenue systems",
    "sales systems",
    "gtm systems",
    "crm systems",
    "business systems",
    "salesforce",
    "business central",
    "d365",
    "dynamics 365",
    "finance shared services",
    "hr shared services",
    "people shared services",
    "accounting shared services",
    "construction",
)

_GENERIC_DATA_TITLE_TERMS = ("data",)
_DATA_PLATFORM_TITLE_TERMS = (
    "data platform",
    "data infrastructure",
    "ml platform",
    "machine learning platform",
)


def normalize_job_search_text(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def is_excluded_target_function_title(title: str | None) -> bool:
    normalized_title = normalize_job_search_text(title)
    return _matches_any_phrase(normalized_title, _EXCLUDED_TARGET_FUNCTION_TITLE_TERMS)


def is_generic_data_title(title: str | None) -> bool:
    normalized_title = normalize_job_search_text(title)
    return _matches_any_phrase(
        normalized_title, _GENERIC_DATA_TITLE_TERMS
    ) and not _matches_any_phrase(normalized_title, _DATA_PLATFORM_TITLE_TERMS)


def infer_job_search_domain_values(job: JobLeadSnapshot) -> list[str]:
    if is_excluded_target_function_title(job.title):
        return []
    if is_generic_data_title(job.title):
        return (
            ["data_platform"]
            if "data platform" in normalize_job_search_text(job.description_normalized)
            else []
        )
    haystack = normalize_job_search_text(f"{job.title} {job.description_normalized}")
    return [
        domain
        for domain, patterns in _DOMAIN_RULES
        if any(pattern in haystack for pattern in patterns)
    ]


def target_function_matches(
    targets: list[str], *, title: str | None, description: str | None
) -> tuple[bool, bool]:
    """Return direct title and description-only target-function matches."""
    normalized_title = normalize_job_search_text(title)
    normalized_description = normalize_job_search_text(description)
    if is_excluded_target_function_title(normalized_title) or is_generic_data_title(
        normalized_title
    ):
        return False, False
    normalized_targets = [normalize_job_search_text(target) for target in targets]
    target_domains = _target_domains(normalized_targets)
    direct_targets = [target for target in normalized_targets if target != "infrastructure"]
    title_match = any(target and target in normalized_title for target in direct_targets)
    description_match = any(
        target and target in normalized_description for target in direct_targets
    )
    for domain, patterns in _DOMAIN_RULES:
        if domain not in target_domains:
            continue
        title_match = title_match or any(pattern in normalized_title for pattern in patterns)
        description_match = description_match or any(
            pattern in normalized_description for pattern in patterns
        )
    return title_match, description_match and not title_match


def _target_domains(targets: list[str]) -> set[str]:
    domains: set[str] = set()
    for domain, patterns in _DOMAIN_RULES:
        if any(target in patterns or target == domain.replace("_", " ") for target in targets):
            domains.add(domain)
    return domains


def _matches_any_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    padded_text = f" {text} "
    return any(f" {phrase} " in padded_text for phrase in phrases)
