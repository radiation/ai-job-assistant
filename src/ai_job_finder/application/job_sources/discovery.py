from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.sql import over

from ai_job_finder.application.job_searches.definitions import get_job_search_definition
from ai_job_finder.application.job_sources.imports import _current_candidate
from ai_job_finder.domain.enums import JobLocationEligibilityStatus, WorkplaceType
from ai_job_finder.domain.location_eligibility import (
    JobLocationEligibilityResult,
    JobLocationSignals,
    classify_job_location_eligibility,
)
from ai_job_finder.infrastructure.database.models import (
    JobEvaluationModel,
    JobLeadModel,
    JobSearchDefinitionModel,
    JobSearchMatchModel,
    JobSearchRunModel,
    JobSourceObservationModel,
)


@dataclass(frozen=True, slots=True)
class RankedDiscoveredLead:
    job: JobLeadModel
    observation: JobSourceObservationModel
    latest_evaluation: JobEvaluationModel | None
    location_eligibility: JobLocationEligibilityResult
    saved_search_matches: tuple[JobSearchMatchModel, ...]


def _match_sort_key(match: JobSearchMatchModel) -> tuple[float, datetime, str]:
    return (
        match.score_at_match_time or -1.0,
        match.created_at,
        str(match.id),
    )


def _location_signals_for_observation(
    job: JobLeadModel,
    observation: JobSourceObservationModel,
) -> JobLocationSignals:
    payload = observation.normalized_payload or {}
    offices = payload.get("offices")
    metadata = payload.get("metadata")
    return JobLocationSignals(
        location_text=job.location_text,
        workplace_type=WorkplaceType(job.workplace_type) if job.workplace_type else None,
        offices=[str(value) for value in offices if isinstance(value, str)]
        if isinstance(offices, list)
        else [],
        metadata=metadata if isinstance(metadata, dict) else {},
    )


def _latest_evaluation_subquery() -> Select[tuple[UUID, Any]]:
    return select(
        JobEvaluationModel.job_lead_id,
        func.max(JobEvaluationModel.evaluated_at).label("latest_evaluated_at"),
    ).group_by(JobEvaluationModel.job_lead_id)


def _current_saved_search_matches_subquery(
    *,
    search_definition_id: UUID | None = None,
) -> Select[tuple[Any, ...]]:
    ranked_matches = (
        select(
            JobSearchMatchModel.id.label("match_id"),
            over(
                func.row_number(),
                partition_by=(
                    JobSearchMatchModel.job_lead_id,
                    JobSearchMatchModel.search_definition_id,
                ),
                order_by=(
                    JobSearchRunModel.completed_at.desc(),
                    JobSearchRunModel.started_at.desc(),
                    JobSearchMatchModel.created_at.desc(),
                    JobSearchMatchModel.id.desc(),
                ),
            ).label("match_rank"),
        )
        .join(JobSearchRunModel, JobSearchRunModel.id == JobSearchMatchModel.search_run_id)
        .join(
            JobSearchDefinitionModel,
            JobSearchDefinitionModel.id == JobSearchMatchModel.search_definition_id,
        )
        .where(
            JobSearchRunModel.status.in_(("completed", "partial")),
            JobSearchDefinitionModel.enabled.is_(True),
        )
    )
    if search_definition_id is not None:
        ranked_matches = ranked_matches.where(
            JobSearchMatchModel.search_definition_id == search_definition_id
        )
    ranked_match_rows = ranked_matches.subquery()
    return select(ranked_match_rows.c.match_id).where(ranked_match_rows.c.match_rank == 1)


def list_ranked_discovered_leads(
    session: Session,
    *,
    search_definition_id: UUID | None = None,
    source_id: UUID | None = None,
    company: str | None = None,
    source_posting_status: str | None = None,
    workflow_status: str | None = None,
    recommendation: str | None = None,
    minimum_score: float | None = None,
    location: str | None = None,
    workplace_type: str | None = None,
    location_eligibility: JobLocationEligibilityStatus | None = None,
    include_ineligible: bool = False,
) -> list[RankedDiscoveredLead]:
    candidate = _current_candidate(session)
    candidate_snapshot = candidate.to_snapshot()
    if search_definition_id is not None:
        get_job_search_definition(session, search_definition_id)
    latest = _latest_evaluation_subquery().subquery()
    current_match_ids = _current_saved_search_matches_subquery(
        search_definition_id=search_definition_id
    ).subquery()
    query = (
        select(JobSourceObservationModel, JobLeadModel, JobEvaluationModel, JobSearchMatchModel)
        .options(joinedload(JobSearchMatchModel.search_definition))
        .join(JobLeadModel, JobLeadModel.id == JobSourceObservationModel.job_lead_id)
        .outerjoin(
            latest,
            latest.c.job_lead_id == JobLeadModel.id,
        )
        .outerjoin(
            JobEvaluationModel,
            and_(
                JobEvaluationModel.job_lead_id == JobLeadModel.id,
                JobEvaluationModel.evaluated_at == latest.c.latest_evaluated_at,
            ),
        )
        .join(JobSearchMatchModel, JobSearchMatchModel.job_lead_id == JobLeadModel.id)
        .join(current_match_ids, current_match_ids.c.match_id == JobSearchMatchModel.id)
        .where(
            JobSourceObservationModel.active.is_(True),
            JobLeadModel.source_posting_status == "open",
            JobLeadModel.posting_status.not_in(("rejected", "closed")),
            JobSearchMatchModel.matched.is_(True),
            JobSearchMatchModel.job_evaluation_id == JobEvaluationModel.id,
        )
    )
    if source_id is not None:
        query = query.where(JobSourceObservationModel.source_configuration_id == source_id)
    if company:
        query = query.where(JobLeadModel.company_name.ilike(f"%{company}%"))
    if source_posting_status:
        query = query.where(JobLeadModel.source_posting_status == source_posting_status)
    if workflow_status:
        query = query.where(JobLeadModel.posting_status == workflow_status)
    if recommendation:
        query = query.where(JobEvaluationModel.recommendation == recommendation)
    if minimum_score is not None:
        query = query.where(JobEvaluationModel.overall_score >= minimum_score)
    if location:
        query = query.where(JobLeadModel.location_text.ilike(f"%{location}%"))
    if workplace_type:
        query = query.where(JobLeadModel.workplace_type == workplace_type)

    rows = session.execute(query).all()
    matches_by_job_id: dict[UUID, list[JobSearchMatchModel]] = {}
    observations_by_job_id: dict[UUID, JobSourceObservationModel] = {}
    evaluations_by_match_id: dict[UUID, JobEvaluationModel] = {}
    for observation, job, evaluation, match in rows:
        matches_by_job_id.setdefault(job.id, []).append(match)
        evaluations_by_match_id[match.id] = evaluation
        current_observation = observations_by_job_id.get(job.id)
        if current_observation is None or (
            observation.source_updated_at or observation.last_seen_at,
            observation.first_seen_at,
            str(observation.id),
        ) > (
            current_observation.source_updated_at or current_observation.last_seen_at,
            current_observation.first_seen_at,
            str(current_observation.id),
        ):
            observations_by_job_id[job.id] = observation

    items: list[RankedDiscoveredLead] = []
    for job_id, matches in matches_by_job_id.items():
        observation = observations_by_job_id[job_id]
        job = observation.job_lead
        sorted_matches = tuple(sorted(matches, key=_match_sort_key, reverse=True))
        evaluation = evaluations_by_match_id[sorted_matches[0].id]
        eligibility = classify_job_location_eligibility(
            candidate_snapshot,
            _location_signals_for_observation(job, observation),
        )
        if location_eligibility is not None and eligibility.status is not location_eligibility:
            continue
        if (
            location_eligibility is None
            and not include_ineligible
            and eligibility.status is JobLocationEligibilityStatus.INELIGIBLE
        ):
            continue
        items.append(
            RankedDiscoveredLead(
                job=job,
                observation=observation,
                latest_evaluation=evaluation,
                location_eligibility=eligibility,
                saved_search_matches=sorted_matches,
            )
        )
    return sorted(
        items,
        key=lambda item: (
            item.saved_search_matches[0].recommendation_at_match_time
            in {"strong_recommend", "recommend"},
            item.saved_search_matches[0].score_at_match_time or -1.0,
            item.observation.source_updated_at or item.observation.last_seen_at,
            item.observation.first_seen_at,
            str(item.job.id),
        ),
        reverse=True,
    )
