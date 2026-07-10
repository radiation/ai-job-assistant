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


class VerificationStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class JobLeadSource(StrEnum):
    MANUAL = "manual"
    REFERRAL = "referral"
    RECRUITER = "recruiter"


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
