from __future__ import annotations

import pytest

from ai_job_finder.domain.enums import JobSourceProvider
from ai_job_finder.domain.errors import InvalidJobSourceError
from ai_job_finder.domain.source_detection import JobSourceBoardValidation
from ai_job_finder.infrastructure.job_sources.router import ProviderJobSourceBoardValidator


class _TokenValidator:
    def __init__(self, label: str) -> None:
        self.label = label
        self.calls: list[str] = []

    def validate_board_token(self, board_token: str) -> JobSourceBoardValidation:
        self.calls.append(board_token)
        return JobSourceBoardValidation(
            token=board_token,
            status="valid",
            valid=True,
            company_name=self.label,
        )


def test_routes_greenhouse_and_ashby_to_their_own_token_validators() -> None:
    greenhouse = _TokenValidator("Greenhouse")
    ashby = _TokenValidator("Ashby")
    validator = ProviderJobSourceBoardValidator(
        {
            JobSourceProvider.GREENHOUSE: greenhouse,
            JobSourceProvider.ASHBY: ashby,
        }
    )

    greenhouse_result = validator.validate(JobSourceProvider.GREENHOUSE, "acme")
    ashby_result = validator.validate(JobSourceProvider.ASHBY, "Acme")

    assert greenhouse.calls == ["acme"]
    assert ashby.calls == ["Acme"]
    assert greenhouse_result.company_name == "Greenhouse"
    assert ashby_result.company_name == "Ashby"


def test_missing_provider_fails_clearly() -> None:
    validator = ProviderJobSourceBoardValidator({})

    with pytest.raises(InvalidJobSourceError, match="Unsupported job source provider"):
        validator.validate(JobSourceProvider.ASHBY, "Acme")
