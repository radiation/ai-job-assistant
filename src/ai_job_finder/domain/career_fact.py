from __future__ import annotations

from datetime import datetime

from ai_job_finder.domain.enums import CareerFactLifecycle
from ai_job_finder.domain.errors import InvalidCareerFactTransitionError

ALLOWED_LIFECYCLE_TRANSITIONS: dict[CareerFactLifecycle, set[CareerFactLifecycle]] = {
    CareerFactLifecycle.DRAFT: {
        CareerFactLifecycle.VERIFIED,
        CareerFactLifecycle.ARCHIVED,
    },
    CareerFactLifecycle.VERIFIED: {
        CareerFactLifecycle.DRAFT,
        CareerFactLifecycle.ARCHIVED,
    },
    CareerFactLifecycle.ARCHIVED: {
        CareerFactLifecycle.DRAFT,
    },
}


def ensure_valid_lifecycle_transition(
    current: CareerFactLifecycle,
    target: CareerFactLifecycle,
) -> None:
    if current == target:
        return
    if target not in ALLOWED_LIFECYCLE_TRANSITIONS[current]:
        msg = f"Cannot transition career fact from {current.value} to {target.value}."
        raise InvalidCareerFactTransitionError(msg)


def transition_metadata(
    current: CareerFactLifecycle,
    target: CareerFactLifecycle,
    *,
    changed_at: datetime,
    existing_verified_at: datetime | None,
) -> tuple[datetime | None, datetime | None]:
    ensure_valid_lifecycle_transition(current, target)

    verified_at = existing_verified_at
    archived_at: datetime | None = None

    if target is CareerFactLifecycle.VERIFIED:
        verified_at = changed_at
    elif target is CareerFactLifecycle.DRAFT:
        verified_at = None
    elif target is CareerFactLifecycle.ARCHIVED:
        archived_at = changed_at

    return verified_at, archived_at
