from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ai_job_finder.application.job_sources._common import _normalize_optional_str
from ai_job_finder.domain.common import new_uuid
from ai_job_finder.domain.enums import JobSourceProvider
from ai_job_finder.domain.errors import DuplicateJobSourceError, NotFoundError
from ai_job_finder.infrastructure.database.models import JobSourceConfigurationModel


def create_job_source_configuration(
    session: Session,
    *,
    provider: str,
    display_name: str,
    company_name: str,
    board_token: str,
    source_url: str | None,
    enabled: bool = True,
) -> JobSourceConfigurationModel:
    source = JobSourceConfigurationModel(
        id=new_uuid(),
        provider=JobSourceProvider(provider).value,
        display_name=display_name.strip(),
        company_name=company_name.strip(),
        board_token=board_token.strip(),
        source_url=_normalize_optional_str(source_url),
        enabled=enabled,
    )
    session.add(source)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateJobSourceError(
            "A source with this provider and board token already exists."
        ) from exc
    session.refresh(source)
    return source


def list_job_source_configurations(session: Session) -> list[JobSourceConfigurationModel]:
    return list(
        session.scalars(
            select(JobSourceConfigurationModel).order_by(
                JobSourceConfigurationModel.created_at.desc()
            )
        )
    )


def get_job_source_configuration(session: Session, source_id: UUID) -> JobSourceConfigurationModel:
    source = session.get(JobSourceConfigurationModel, source_id)
    if source is None:
        raise NotFoundError(f"Job source {source_id} was not found.")
    return source


def update_job_source_configuration(
    session: Session,
    *,
    source_id: UUID,
    display_name: str,
    company_name: str,
    board_token: str,
    source_url: str | None,
) -> JobSourceConfigurationModel:
    source = get_job_source_configuration(session, source_id)
    source.display_name = display_name.strip()
    source.company_name = company_name.strip()
    source.board_token = board_token.strip()
    source.source_url = _normalize_optional_str(source_url)
    session.add(source)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateJobSourceError(
            "A source with this provider and board token already exists."
        ) from exc
    session.refresh(source)
    return source


def set_job_source_enabled(
    session: Session,
    *,
    source_id: UUID,
    enabled: bool,
) -> JobSourceConfigurationModel:
    source = get_job_source_configuration(session, source_id)
    source.enabled = enabled
    session.add(source)
    session.commit()
    session.refresh(source)
    return source
