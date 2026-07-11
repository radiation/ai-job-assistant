from __future__ import annotations

from ai_job_finder.domain.enums import CareerFactProposalReviewStatus
from ai_job_finder.domain.errors import InvalidProposalTransitionError

ALLOWED_PROPOSAL_TRANSITIONS: dict[
    CareerFactProposalReviewStatus,
    set[CareerFactProposalReviewStatus],
] = {
    CareerFactProposalReviewStatus.PENDING: {
        CareerFactProposalReviewStatus.ACCEPTED,
        CareerFactProposalReviewStatus.REJECTED,
        CareerFactProposalReviewStatus.MERGED,
    },
    CareerFactProposalReviewStatus.ACCEPTED: set(),
    CareerFactProposalReviewStatus.REJECTED: set(),
    CareerFactProposalReviewStatus.MERGED: set(),
}


def ensure_valid_proposal_transition(
    current: CareerFactProposalReviewStatus,
    target: CareerFactProposalReviewStatus,
) -> None:
    if current == target:
        return
    if target not in ALLOWED_PROPOSAL_TRANSITIONS[current]:
        msg = f"Cannot transition career fact proposal from {current.value} to {target.value}."
        raise InvalidProposalTransitionError(msg)
