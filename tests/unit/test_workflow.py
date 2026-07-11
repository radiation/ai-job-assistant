from __future__ import annotations

import pytest

from ai_job_finder.domain.career_fact import ensure_valid_lifecycle_transition
from ai_job_finder.domain.enums import CareerFactLifecycle, PostingStatus
from ai_job_finder.domain.errors import (
    InvalidCareerFactTransitionError,
    InvalidStatusTransitionError,
)
from ai_job_finder.domain.job_lead import ensure_valid_status_transition


def test_valid_workflow_transition() -> None:
    ensure_valid_status_transition(PostingStatus.DISCOVERED, PostingStatus.REVIEWING)


def test_invalid_workflow_transition() -> None:
    with pytest.raises(InvalidStatusTransitionError):
        ensure_valid_status_transition(PostingStatus.DISCOVERED, PostingStatus.PURSUING)


def test_valid_career_fact_transition() -> None:
    ensure_valid_lifecycle_transition(CareerFactLifecycle.DRAFT, CareerFactLifecycle.VERIFIED)


def test_invalid_career_fact_transition() -> None:
    with pytest.raises(InvalidCareerFactTransitionError):
        ensure_valid_lifecycle_transition(
            CareerFactLifecycle.ARCHIVED, CareerFactLifecycle.VERIFIED
        )
