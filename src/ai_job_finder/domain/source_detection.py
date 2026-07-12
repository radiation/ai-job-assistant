from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PublicPage:
    requested_url: str
    final_url: str
    content_type: str
    text: str


class PublicPageFetcher(Protocol):
    def fetch(self, url: str) -> PublicPage: ...


@dataclass(frozen=True, slots=True)
class GreenhouseBoardValidation:
    token: str
    status: str
    valid: bool
    job_count: int | None = None
    sample_titles: list[str] = field(default_factory=list)
    company_name: str | None = None
    error_message: str | None = None


class GreenhouseBoardValidator(Protocol):
    def validate_board_token(self, board_token: str) -> GreenhouseBoardValidation: ...
