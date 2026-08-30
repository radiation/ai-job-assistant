from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ai_job_finder.application.job_searches import (
    get_job_search_definition,
    list_job_search_matches,
)
from ai_job_finder.domain.common import new_uuid, utc_now
from ai_job_finder.domain.enums import Recommendation
from ai_job_finder.domain.job_discovery import JobDiscoveryRunStatus
from ai_job_finder.infrastructure.database.models import (
    JobDiscoveryRunModel,
    JobSearchActionableNotificationModel,
    JobSearchDefinitionModel,
)

DAILY_DISCOVERY_CADENCE = "daily"
_ACTIONABLE_RECOMMENDATIONS = (
    Recommendation.STRONG_RECOMMEND.value,
    Recommendation.RECOMMEND.value,
)

ScheduledDiscoveryRunner = Callable[[UUID], JobDiscoveryRunModel]
InAppNotificationDelivery = Callable[[JobSearchActionableNotificationModel], None]


@dataclass(frozen=True, slots=True)
class ScheduledDiscoveryResult:
    search_definition_id: UUID
    discovery_run_id: UUID
    notification_count: int


def configure_scheduled_discovery(
    session: Session,
    *,
    search_definition_id: UUID,
    enabled: bool,
    cadence: str,
    now: datetime | None = None,
) -> JobSearchDefinitionModel:
    if cadence != DAILY_DISCOVERY_CADENCE:
        raise ValueError("Only daily scheduled discovery is supported.")
    search = get_job_search_definition(session, search_definition_id)
    search.scheduled_discovery_enabled = enabled
    search.scheduled_discovery_cadence = cadence
    search.next_scheduled_discovery_at = _as_utc(now or utc_now()) if enabled else None
    session.add(search)
    session.commit()
    session.refresh(search)
    return search


def list_due_scheduled_discoveries(
    session: Session,
    *,
    now: datetime | None = None,
) -> list[JobSearchDefinitionModel]:
    due_at = _as_utc(now or utc_now())
    return list(
        session.scalars(
            select(JobSearchDefinitionModel)
            .where(
                JobSearchDefinitionModel.enabled.is_(True),
                JobSearchDefinitionModel.scheduled_discovery_enabled.is_(True),
                JobSearchDefinitionModel.next_scheduled_discovery_at.is_not(None),
                JobSearchDefinitionModel.next_scheduled_discovery_at <= due_at,
            )
            .order_by(
                JobSearchDefinitionModel.next_scheduled_discovery_at.asc(),
                JobSearchDefinitionModel.id.asc(),
            )
        )
    )


def run_due_scheduled_discoveries(
    session: Session,
    *,
    run_discovery: ScheduledDiscoveryRunner,
    deliver_in_app_notification: InAppNotificationDelivery | None = None,
    now: datetime | None = None,
) -> list[ScheduledDiscoveryResult]:
    attempted_at = _as_utc(now or utc_now())
    results: list[ScheduledDiscoveryResult] = []
    for due_search in list_due_scheduled_discoveries(session, now=attempted_at):
        if not _claim_scheduled_discovery(
            session,
            search_definition_id=due_search.id,
            attempted_at=attempted_at,
        ):
            continue
        try:
            run = run_discovery(due_search.id)
        except Exception:
            session.rollback()
            continue

        _record_scheduled_completion(
            session,
            search_definition_id=due_search.id,
            completed_at=run.completed_at or attempted_at,
        )
        notification_count = 0
        if run.saved_search_run_id is not None and run.status != JobDiscoveryRunStatus.FAILED.value:
            notification_count = deliver_newly_actionable_notifications(
                session,
                search_run_id=run.saved_search_run_id,
                deliver_in_app_notification=deliver_in_app_notification,
            )
        results.append(
            ScheduledDiscoveryResult(
                search_definition_id=due_search.id,
                discovery_run_id=run.id,
                notification_count=notification_count,
            )
        )
    return results


def deliver_newly_actionable_notifications(
    session: Session,
    *,
    search_run_id: UUID,
    deliver_in_app_notification: InAppNotificationDelivery | None = None,
) -> int:
    delivered_count = 0
    for record in list_job_search_matches(session, search_run_id=search_run_id, matched_only=True):
        match = record.match
        if match.recommendation_at_match_time not in _ACTIONABLE_RECOMMENDATIONS:
            continue
        notification = JobSearchActionableNotificationModel(
            id=new_uuid(),
            search_definition_id=match.search_definition_id,
            job_lead_id=match.job_lead_id,
            job_search_match_id=match.id,
            channel="in_app",
            delivery_status="pending",
        )
        session.add(notification)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            continue
        session.refresh(notification)
        _deliver_in_app_notification(
            session,
            notification=notification,
            delivery=deliver_in_app_notification,
        )
        delivered_count += 1
    return delivered_count


def list_actionable_notifications(
    session: Session,
    *,
    search_definition_id: UUID,
) -> list[JobSearchActionableNotificationModel]:
    return list(
        session.scalars(
            select(JobSearchActionableNotificationModel)
            .where(
                JobSearchActionableNotificationModel.search_definition_id == search_definition_id
            )
            .order_by(JobSearchActionableNotificationModel.created_at.desc())
        )
    )


def _claim_scheduled_discovery(
    session: Session,
    *,
    search_definition_id: UUID,
    attempted_at: datetime,
) -> bool:
    active_run_exists = (
        select(JobDiscoveryRunModel.id)
        .where(
            JobDiscoveryRunModel.search_definition_id == search_definition_id,
            JobDiscoveryRunModel.status == JobDiscoveryRunStatus.RUNNING.value,
        )
        .exists()
    )
    claim = session.execute(
        update(JobSearchDefinitionModel)
        .where(
            JobSearchDefinitionModel.id == search_definition_id,
            JobSearchDefinitionModel.enabled.is_(True),
            JobSearchDefinitionModel.scheduled_discovery_enabled.is_(True),
            JobSearchDefinitionModel.next_scheduled_discovery_at.is_not(None),
            JobSearchDefinitionModel.next_scheduled_discovery_at <= attempted_at,
            ~active_run_exists,
        )
        .values(
            last_scheduled_discovery_attempted_at=attempted_at,
            next_scheduled_discovery_at=attempted_at + timedelta(days=1),
        )
        .returning(JobSearchDefinitionModel.id)
    ).scalar_one_or_none()
    session.commit()
    return claim is not None


def _record_scheduled_completion(
    session: Session,
    *,
    search_definition_id: UUID,
    completed_at: datetime,
) -> None:
    search = get_job_search_definition(session, search_definition_id)
    search.last_scheduled_discovery_completed_at = _as_utc(completed_at)
    session.add(search)
    session.commit()


def _deliver_in_app_notification(
    session: Session,
    *,
    notification: JobSearchActionableNotificationModel,
    delivery: InAppNotificationDelivery | None,
) -> None:
    notification.attempted_at = utc_now()
    try:
        if delivery is not None:
            delivery(notification)
    except Exception as exc:
        notification.delivery_status = "failed"
        notification.failure_message = str(exc)[:1000]
        notification.sent_at = None
    else:
        notification.delivery_status = "succeeded"
        notification.failure_message = None
        notification.sent_at = notification.attempted_at
    session.add(notification)
    session.commit()


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
