from __future__ import annotations

from enum import StrEnum


class JobDiscoveryRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class JobDiscoveryObservationStatus(StrEnum):
    PENDING = "pending"
    DETECTED_SUPPORTED = "detected_supported"
    IMPORTED = "imported"
    UNSUPPORTED = "unsupported"
    AMBIGUOUS = "ambiguous"
    FAILED = "failed"


class JobDiscoveryQueryStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
