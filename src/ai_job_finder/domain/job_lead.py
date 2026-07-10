from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from ai_job_finder.domain.enums import PostingStatus, WorkplaceType
from ai_job_finder.domain.errors import InvalidStatusTransitionError

ALLOWED_POSTING_STATUS_TRANSITIONS: dict[PostingStatus, frozenset[PostingStatus]] = {
    PostingStatus.DISCOVERED: frozenset(
        {PostingStatus.REVIEWING, PostingStatus.REJECTED, PostingStatus.CLOSED}
    ),
    PostingStatus.REVIEWING: frozenset(
        {PostingStatus.PURSUING, PostingStatus.REJECTED, PostingStatus.CLOSED}
    ),
    PostingStatus.PURSUING: frozenset({PostingStatus.REJECTED, PostingStatus.CLOSED}),
    PostingStatus.REJECTED: frozenset(),
    PostingStatus.CLOSED: frozenset(),
}


def ensure_valid_status_transition(current: PostingStatus, target: PostingStatus) -> None:
    if current == target:
        return
    if target not in ALLOWED_POSTING_STATUS_TRANSITIONS[current]:
        msg = f"Cannot transition job lead from {current.value!r} to {target.value!r}."
        raise InvalidStatusTransitionError(msg)


@dataclass(frozen=True, slots=True)
class JobLeadSnapshot:
    id: UUID
    source: str
    source_url: str | None
    external_id: str | None
    company_name: str
    title: str
    location_text: str | None
    workplace_type: WorkplaceType | None
    description_raw: str
    description_normalized: str
    compensation_text: str | None
    discovered_at: datetime
    posting_status: PostingStatus
    created_at: datetime
    updated_at: datetime
