from __future__ import annotations

from enum import StrEnum


class RemotePreference(StrEnum):
    REMOTE_ONLY = "remote_only"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    FLEXIBLE = "flexible"


class CareerFactCategory(StrEnum):
    LEADERSHIP = "leadership"
    PLATFORM = "platform"
    DELIVERY = "delivery"
    OPERATIONS = "operations"
    TRANSFORMATION = "transformation"


class CareerFactLifecycle(StrEnum):
    DRAFT = "draft"
    VERIFIED = "verified"
    ARCHIVED = "archived"


class EvidenceTag(StrEnum):
    PEOPLE_LEADERSHIP = "people_leadership"
    MANAGER_OF_MANAGERS = "manager_of_managers"
    PLATFORM_ENGINEERING = "platform_engineering"
    DEVELOPER_EXPERIENCE = "developer_experience"
    DEVELOPER_PRODUCTIVITY = "developer_productivity"
    INFRASTRUCTURE = "infrastructure"
    SHARED_SERVICES = "shared_services"
    AI_ENABLEMENT = "ai_enablement"
    ML_PLATFORM = "ml_platform"
    DATA_PLATFORM = "data_platform"
    GLOBAL_OPERATIONS = "global_operations"
    HIGH_SCALE = "high_scale"
    REGULATED_ENVIRONMENT = "regulated_environment"
    CUSTOMER_IMPACT = "customer_impact"
    P_AND_L = "p_and_l"
    VENDOR_MANAGEMENT = "vendor_management"
    COST_OPTIMIZATION = "cost_optimization"
    RELIABILITY = "reliability"
    SECURITY = "security"
    OBSERVABILITY = "observability"
    CI_CD = "ci_cd"
    CLOUD = "cloud"
    KUBERNETES = "kubernetes"


class SourceDocumentType(StrEnum):
    RESUME = "resume"
    PERFORMANCE_REVIEW = "performance_review"
    PROJECT_NOTES = "project_notes"
    CAREER_NOTES = "career_notes"
    OTHER = "other"


class SourceDocumentExtractionStatus(StrEnum):
    UPLOADED = "uploaded"
    TEXT_EXTRACTED = "text_extracted"
    EXTRACTION_FAILED = "extraction_failed"
    FACTS_EXTRACTED = "facts_extracted"


class ExtractionRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class CareerFactProposalReviewStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    MERGED = "merged"


class ProvenanceType(StrEnum):
    RESUME = "resume"
    PERFORMANCE_REVIEW = "performance_review"
    PROJECT_NOTES = "project_notes"
    PERSONAL_RECOLLECTION = "personal_recollection"
    VERIFIED_EXTERNAL_SOURCE = "verified_external_source"
    OTHER = "other"


class JobLeadSource(StrEnum):
    MANUAL = "manual"
    REFERRAL = "referral"
    RECRUITER = "recruiter"
    GREENHOUSE = "greenhouse"


class JobSourceProvider(StrEnum):
    GREENHOUSE = "greenhouse"


class JobImportRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"


class SourceDetectionRunStatus(StrEnum):
    RUNNING = "running"
    DETECTED = "detected"
    NOT_DETECTED = "not_detected"
    AMBIGUOUS = "ambiguous"
    FAILED = "failed"
    SOURCE_CREATED = "source_created"


class SourcePostingStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class JobLocationEligibilityStatus(StrEnum):
    ELIGIBLE = "eligible"
    NEEDS_REVIEW = "needs_review"
    INELIGIBLE = "ineligible"


class JobLocationEligibilityReason(StrEnum):
    PREFERRED_LOCATION_MATCH = "preferred_location_match"
    REMOTE_GEOGRAPHY_MATCH = "remote_geography_match"
    PRESENCE_REQUIRED_OUTSIDE_PREFERRED_GEOGRAPHY = "presence_required_outside_preferred_geography"
    REMOTE_GEOGRAPHY_UNCLEAR = "remote_geography_unclear"
    MISSING_LOCATION_DATA = "missing_location_data"
    MISSING_WORKPLACE_TYPE = "missing_workplace_type"
    CONFLICTING_LOCATION_SIGNALS = "conflicting_location_signals"
    MULTIPLE_LOCATIONS_REQUIRE_REVIEW = "multiple_locations_require_review"
    BROAD_REGION_REQUIRES_REVIEW = "broad_region_requires_review"
    INTERNATIONAL_LOCATION_NOT_APPROVED = "international_location_not_approved"
    CANDIDATE_REMOTE_GEOGRAPHY_NOT_CONFIGURED = "candidate_remote_geography_not_configured"


class WorkplaceType(StrEnum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"


class PostingStatus(StrEnum):
    DISCOVERED = "discovered"
    REVIEWING = "reviewing"
    PURSUING = "pursuing"
    REJECTED = "rejected"
    CLOSED = "closed"


class Recommendation(StrEnum):
    STRONG_RECOMMEND = "strong_recommend"
    RECOMMEND = "recommend"
    HOLD = "hold"
    DECLINE = "decline"
