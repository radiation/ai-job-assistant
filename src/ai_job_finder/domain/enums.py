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


class SourcePostingStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


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
