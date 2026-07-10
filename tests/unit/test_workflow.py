from __future__ import annotations

import pytest

from ai_job_finder.domain.enums import PostingStatus
from ai_job_finder.domain.errors import InvalidStatusTransitionError
from ai_job_finder.domain.job_lead import ensure_valid_status_transition


def test_valid_workflow_transition() -> None:
    ensure_valid_status_transition(PostingStatus.DISCOVERED, PostingStatus.REVIEWING)


def test_invalid_workflow_transition() -> None:
    with pytest.raises(InvalidStatusTransitionError):
        ensure_valid_status_transition(PostingStatus.DISCOVERED, PostingStatus.PURSUING)
