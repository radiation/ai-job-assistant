from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ai_job_finder.application.job_searches._common import normalize_list
from ai_job_finder.domain.common import new_uuid
from ai_job_finder.domain.enums import WorkplaceType
from ai_job_finder.domain.errors import DuplicateJobSearchError, NotFoundError
from ai_job_finder.domain.job_searches import JobSearchDomain, JobSearchSeniority
from ai_job_finder.infrastructure.database.models import JobSearchDefinitionModel


def create_job_search_definition(
    session: Session,
    *,
    name: str,
    title_include_patterns: list[str],
    title_exclude_patterns: list[str],
    target_domains: list[str],
    target_seniority_levels: list[str],
    allowed_locations: list[str],
    allowed_remote_geographies: list[str],
    allowed_workplace_types: list[str],
    minimum_score_threshold: float,
    enabled: bool = True,
) -> JobSearchDefinitionModel:
    search = JobSearchDefinitionModel(
        id=new_uuid(),
        name=name.strip(),
        enabled=enabled,
        title_include_patterns=normalize_list(title_include_patterns),
        title_exclude_patterns=normalize_list(title_exclude_patterns),
        target_domains=[JobSearchDomain(value).value for value in normalize_list(target_domains)],
        target_seniority_levels=[
            JobSearchSeniority(value).value for value in normalize_list(target_seniority_levels)
        ],
        allowed_locations=normalize_list(allowed_locations),
        allowed_remote_geographies=normalize_list(allowed_remote_geographies),
        allowed_workplace_types=[
            WorkplaceType(value).value for value in normalize_list(allowed_workplace_types)
        ],
        minimum_score_threshold=minimum_score_threshold,
    )
    session.add(search)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateJobSearchError("A saved search with this name already exists.") from exc
    session.refresh(search)
    return search


def list_job_search_definitions(session: Session) -> list[JobSearchDefinitionModel]:
    return list(
        session.scalars(
            select(JobSearchDefinitionModel)
            .options(selectinload(JobSearchDefinitionModel.runs))
            .order_by(JobSearchDefinitionModel.created_at.desc())
        )
    )


def get_job_search_definition(
    session: Session,
    search_definition_id: UUID,
) -> JobSearchDefinitionModel:
    search = session.scalar(
        select(JobSearchDefinitionModel)
        .options(selectinload(JobSearchDefinitionModel.runs))
        .where(JobSearchDefinitionModel.id == search_definition_id)
    )
    if search is None:
        raise NotFoundError(f"Job search definition {search_definition_id} was not found.")
    return search


def update_job_search_definition(
    session: Session,
    *,
    search_definition_id: UUID,
    name: str,
    title_include_patterns: list[str],
    title_exclude_patterns: list[str],
    target_domains: list[str],
    target_seniority_levels: list[str],
    allowed_locations: list[str],
    allowed_remote_geographies: list[str],
    allowed_workplace_types: list[str],
    minimum_score_threshold: float,
) -> JobSearchDefinitionModel:
    search = get_job_search_definition(session, search_definition_id)
    search.name = name.strip()
    search.title_include_patterns = normalize_list(title_include_patterns)
    search.title_exclude_patterns = normalize_list(title_exclude_patterns)
    search.target_domains = [
        JobSearchDomain(value).value for value in normalize_list(target_domains)
    ]
    search.target_seniority_levels = [
        JobSearchSeniority(value).value for value in normalize_list(target_seniority_levels)
    ]
    search.allowed_locations = normalize_list(allowed_locations)
    search.allowed_remote_geographies = normalize_list(allowed_remote_geographies)
    search.allowed_workplace_types = [
        WorkplaceType(value).value for value in normalize_list(allowed_workplace_types)
    ]
    search.minimum_score_threshold = minimum_score_threshold
    session.add(search)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise DuplicateJobSearchError("A saved search with this name already exists.") from exc
    session.refresh(search)
    return search


def set_job_search_definition_enabled(
    session: Session,
    *,
    search_definition_id: UUID,
    enabled: bool,
) -> JobSearchDefinitionModel:
    search = get_job_search_definition(session, search_definition_id)
    search.enabled = enabled
    session.add(search)
    session.commit()
    session.refresh(search)
    return search
