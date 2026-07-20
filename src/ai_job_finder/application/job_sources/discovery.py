from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session

from ai_job_finder.application.job_searches.definitions import get_job_search_definition
from ai_job_finder.application.job_sources.imports import _current_candidate
from ai_job_finder.domain.enums import JobLocationEligibilityStatus, WorkplaceType
from ai_job_finder.domain.job_searches import (
    JobSearchLocationContext,
    evaluate_job_search_match,
)
from ai_job_finder.domain.location_eligibility import (
    JobLocationEligibilityResult,
    JobLocationSignals,
    classify_job_location_eligibility,
)
from ai_job_finder.infrastructure.database.models import (
    JobEvaluationModel,
    JobLeadModel,
    JobSourceObservationModel,
)


@dataclass(frozen=True, slots=True)
class RankedDiscoveredLead:
    job: JobLeadModel
    observation: JobSourceObservationModel
    latest_evaluation: JobEvaluationModel | None
    location_eligibility: JobLocationEligibilityResult


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
    search_definition = (
        get_job_search_definition(session, search_definition_id)
        if search_definition_id is not None
        else None
    )
    latest = _latest_evaluation_subquery().subquery()
    query = (
        select(JobSourceObservationModel, JobLeadModel, JobEvaluationModel)
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
        .where(JobSourceObservationModel.active.is_(True))
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
    items: list[RankedDiscoveredLead] = []
    for observation, job, evaluation in rows:
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
        if search_definition is not None:
            payload = observation.normalized_payload or {}
            offices = payload.get("offices")
            metadata = payload.get("metadata")
            search_match = evaluate_job_search_match(
                search_definition.to_snapshot(),
                job.to_snapshot(),
                evaluation.to_snapshot() if evaluation is not None else None,
                location_context=JobSearchLocationContext(
                    location_text=job.location_text,
                    workplace_type=(
                        WorkplaceType(job.workplace_type) if job.workplace_type else None
                    ),
                    offices=[str(value) for value in offices if isinstance(value, str)]
                    if isinstance(offices, list)
                    else [],
                    metadata=metadata if isinstance(metadata, dict) else {},
                ),
            )
            if not search_match.matched:
                continue
        items.append(
            RankedDiscoveredLead(
                job=job,
                observation=observation,
                latest_evaluation=evaluation,
                location_eligibility=eligibility,
            )
        )
    return sorted(
        items,
        key=lambda item: (
            item.job.posting_status not in {"rejected", "closed"},
            item.latest_evaluation.overall_score if item.latest_evaluation else -1,
            item.observation.source_updated_at or item.observation.last_seen_at,
            item.observation.first_seen_at,
            str(item.job.id),
        ),
        reverse=True,
    )
