from __future__ import annotations

from ai_job_finder.bootstrap.contracts import (
    CandidatePayload,
    CareerFactCategory,
    CareerFactPayload,
    JobLeadPayload,
    JobLeadSource,
    ProvenanceType,
    RemotePreference,
    WorkplaceType,
)

BOOTSTRAP_OWNER = "bootstrap:candidate-kb-slice"
BOOTSTRAP_SOURCE_PREFIX = "bootstrap://candidate-kb/"
SCORING_VERSION = "candidate_evidence_v2"


def _bootstrap_candidate() -> CandidatePayload:
    return CandidatePayload(
        full_name="Alex Mercer",
        preferred_locations=["Seattle", "Remote", "New York"],
        remote_preference=RemotePreference.FLEXIBLE,
        target_levels=["director", "senior director", "vp"],
        target_functions=[
            "platform engineering",
            "developer experience",
            "infrastructure",
            "ai platform",
        ],
    )


def _fact_definitions() -> dict[str, CareerFactPayload]:
    return {
        "platform": CareerFactPayload(
            category=CareerFactCategory.PLATFORM,
            source_organization="Northstar Platforms",
            statement=(
                "Led a 120-engineer platform organization spanning developer platform, "
                "cloud foundations, and internal paved-road services."
            ),
            metric="38% faster service onboarding",
            technologies=["Kubernetes", "Backstage", "AWS", "Python"],
            leadership_scope="120 engineers across 8 teams",
            business_outcome=(
                "Improved developer throughput and reduced platform friction across "
                "the engineering organization."
            ),
            approved_wording=(
                "Scaled a self-service developer platform used across the engineering organization."
            ),
            evidence_tags=[
                "platform_engineering",
                "developer_experience",
                "shared_services",
                "people_leadership",
                "manager_of_managers",
                "cloud",
                "kubernetes",
            ],
            provenance_type=ProvenanceType.PROJECT_NOTES,
            source_reference=f"{BOOTSTRAP_SOURCE_PREFIX}fact/platform?owner={BOOTSTRAP_OWNER}",
        ),
        "ai": CareerFactPayload(
            category=CareerFactCategory.TRANSFORMATION,
            source_organization="Meridian AI",
            statement=(
                "Sponsored AI-assisted engineering automation for SDLC workflows and "
                "internal developer support."
            ),
            metric="27% reduction in toil for release coordination",
            technologies=["LLM", "Python", "Feature Store"],
            leadership_scope="Cross-functional program across engineering and product",
            business_outcome="Accelerated delivery planning and knowledge retrieval.",
            approved_wording=(
                "Introduced AI and automation workflows that improved engineering execution."
            ),
            evidence_tags=["ai_enablement", "developer_productivity", "data_platform"],
            provenance_type=ProvenanceType.PROJECT_NOTES,
            source_reference=f"{BOOTSTRAP_SOURCE_PREFIX}fact/ai?owner={BOOTSTRAP_OWNER}",
        ),
        "regulated": CareerFactPayload(
            category=CareerFactCategory.OPERATIONS,
            source_organization="RegulaBank",
            statement=(
                "Owned regulated infrastructure modernization in a financial-services environment."
            ),
            metric="99.95% availability during controls transition",
            technologies=["Terraform", "Kubernetes", "Vault"],
            leadership_scope="Global operations and governance stakeholders",
            business_outcome=(
                "Preserved delivery velocity while meeting audit and security controls."
            ),
            approved_wording=(
                "Modernized regulated infrastructure without disrupting compliance commitments."
            ),
            evidence_tags=[
                "regulated_environment",
                "security",
                "infrastructure",
                "global_operations",
            ],
            provenance_type=ProvenanceType.PROJECT_NOTES,
            source_reference=f"{BOOTSTRAP_SOURCE_PREFIX}fact/regulated?owner={BOOTSTRAP_OWNER}",
        ),
        "cicd": CareerFactPayload(
            category=CareerFactCategory.DELIVERY,
            source_organization="Northstar Platforms",
            statement=(
                "Standardized CI/CD, observability, and release guardrails across "
                "hundreds of services."
            ),
            metric="61% faster mean time to recovery",
            technologies=["GitHub Actions", "Argo CD", "OpenTelemetry", "Prometheus"],
            leadership_scope="Platform delivery standards across all product teams",
            business_outcome="Raised deployment confidence and reduced incident recovery time.",
            approved_wording=(
                "Built CI/CD and observability foundations that improved reliability "
                "and release quality."
            ),
            evidence_tags=["ci_cd", "observability", "reliability", "developer_productivity"],
            provenance_type=ProvenanceType.PROJECT_NOTES,
            source_reference=f"{BOOTSTRAP_SOURCE_PREFIX}fact/cicd?owner={BOOTSTRAP_OWNER}",
        ),
        "business": CareerFactPayload(
            category=CareerFactCategory.LEADERSHIP,
            source_organization="Northstar Platforms",
            statement=(
                "Managed platform budgeting, vendor relationships, and multi-year "
                "business cases for shared engineering investments."
            ),
            metric="$18M annual platform portfolio",
            technologies=["AWS", "FinOps"],
            leadership_scope="Executive stakeholder management and strategic vendors",
            business_outcome="Improved unit economics and contract leverage across shared tooling.",
            approved_wording=(
                "Owned vendor strategy and platform investment planning at executive scope."
            ),
            evidence_tags=[
                "vendor_management",
                "p_and_l",
                "cost_optimization",
                "people_leadership",
            ],
            provenance_type=ProvenanceType.PROJECT_NOTES,
            source_reference=f"{BOOTSTRAP_SOURCE_PREFIX}fact/business?owner={BOOTSTRAP_OWNER}",
        ),
    }


def _job_definitions() -> dict[str, JobLeadPayload]:
    return {
        "strong": JobLeadPayload(
            source=JobLeadSource.MANUAL,
            source_url="https://example.test/jobs/strong-platform",
            external_id="bootstrap-strong-platform-devex",
            company_name="Northstar",
            title="Senior Director, Platform Engineering",
            location_text="Seattle, WA",
            workplace_type=WorkplaceType.HYBRID,
            description_raw="Lead platform engineering and developer experience.",
            description_normalized=(
                "Lead platform engineering, developer platform strategy, "
                "self-service infrastructure, CI/CD modernization, observability, "
                "reliability, cloud foundations, and managers of managers."
            ),
            compensation_text="$280k",
        ),
        "partial": JobLeadPayload(
            source=JobLeadSource.MANUAL,
            source_url="https://example.test/jobs/partial-ai-data",
            external_id="bootstrap-partial-ai-data-platform",
            company_name="Meridian",
            title="Director, AI Data Platform",
            location_text="Remote",
            workplace_type=WorkplaceType.REMOTE,
            description_raw="Lead AI data platform and automation programs.",
            description_normalized=(
                "Lead AI and data platform strategy, ML platform operations, cloud "
                "infrastructure, and engineering automation."
            ),
            compensation_text="$250k",
        ),
        "weak": JobLeadPayload(
            source=JobLeadSource.MANUAL,
            source_url="https://example.test/jobs/weak-product",
            external_id="bootstrap-weak-product-engineering",
            company_name="BrightProduct",
            title="Director, Product Engineering",
            location_text="Austin, TX",
            workplace_type=WorkplaceType.ONSITE,
            description_raw="Lead consumer product delivery.",
            description_normalized=(
                "Lead frontend and mobile product engineering for consumer growth, "
                "experimentation, and design execution."
            ),
            compensation_text="$230k",
        ),
    }
