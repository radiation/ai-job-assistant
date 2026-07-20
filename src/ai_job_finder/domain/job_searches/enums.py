from __future__ import annotations

from enum import StrEnum


class JobSearchDomain(StrEnum):
    PLATFORM_ENGINEERING = "platform_engineering"
    DEVELOPER_EXPERIENCE = "developer_experience"
    INFRASTRUCTURE = "infrastructure"
    ENGINEERING_PRODUCTIVITY = "engineering_productivity"
    AI_PLATFORM = "ai_platform"
    DATA_PLATFORM = "data_platform"
    SHARED_SERVICES = "shared_services"


class JobSearchSeniority(StrEnum):
    MANAGER = "manager"
    SENIOR_MANAGER = "senior_manager"
    DIRECTOR = "director"
    SENIOR_DIRECTOR = "senior_director"
    VICE_PRESIDENT = "vice_president"
    HEAD = "head"
    PRINCIPAL = "principal"
    STAFF = "staff"
    EXECUTIVE = "executive"


class JobSearchRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
