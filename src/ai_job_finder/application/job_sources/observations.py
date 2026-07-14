from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ai_job_finder.application.job_sources._common import _normalize_optional_str
from ai_job_finder.application.job_sources.payload_identity import (
    _normalized_payload,
    _scoring_payload,
    _sha256_json,
    _stored_normalized_payload,
    duplicate_hint_key,
)
from ai_job_finder.domain.common import new_uuid
from ai_job_finder.domain.enums import JobLeadSource, SourcePostingStatus
from ai_job_finder.domain.job_sources import NormalizedJobPosting
from ai_job_finder.infrastructure.database.models import (
    JobLeadModel,
    JobSourceConfigurationModel,
    JobSourceObservationModel,
)


def count_active_job_source_observations(session: Session, source_id: UUID) -> int:
    return _active_observation_count(session, source_id)


def list_active_job_source_observation_counts(session: Session) -> dict[UUID, int]:
    rows = (
        session.execute(
            select(
                JobSourceObservationModel.source_configuration_id,
                func.count(JobSourceObservationModel.id),
            )
            .where(JobSourceObservationModel.active.is_(True))
            .group_by(JobSourceObservationModel.source_configuration_id)
        )
        .tuples()
        .all()
    )
    return dict(rows)


def _apply_job_fields(job_lead: JobLeadModel, posting: NormalizedJobPosting) -> None:
    job_lead.source_url = _normalize_optional_str(posting.source_url)
    job_lead.company_name = posting.company_name.strip()
    job_lead.title = posting.title.strip()
    job_lead.location_text = _normalize_optional_str(posting.location_text)
    job_lead.workplace_type = posting.workplace_type.value if posting.workplace_type else None
    job_lead.description_raw = posting.description_raw.strip()
    job_lead.description_normalized = posting.description_normalized.strip()
    job_lead.compensation_text = _normalize_optional_str(posting.compensation_text)
    job_lead.source_posting_status = SourcePostingStatus.OPEN.value


def _active_observation_count(session: Session, source_id: Any) -> int:
    return (
        session.scalar(
            select(func.count(JobSourceObservationModel.id)).where(
                JobSourceObservationModel.source_configuration_id == source_id,
                JobSourceObservationModel.active.is_(True),
            )
        )
        or 0
    )


def _close_missing_observations(
    session: Session,
    *,
    source_id: Any,
    seen_external_ids: set[str],
    removed_at: Any,
) -> int:
    observations = list(
        session.scalars(
            select(JobSourceObservationModel)
            .options(selectinload(JobSourceObservationModel.job_lead))
            .where(
                JobSourceObservationModel.source_configuration_id == source_id,
                JobSourceObservationModel.active.is_(True),
                JobSourceObservationModel.external_post_id.not_in(seen_external_ids),
            )
        )
    )
    for observation in observations:
        observation.active = False
        observation.removed_at = removed_at
        observation.job_lead.source_posting_status = SourcePostingStatus.CLOSED.value
        session.add(observation)
        session.add(observation.job_lead)
    return len(observations)


def _upsert_observed_job(
    session: Session,
    *,
    source: JobSourceConfigurationModel,
    posting: NormalizedJobPosting,
    observed_at: Any,
    retain_raw_payload: bool,
) -> tuple[JobSourceObservationModel, bool, bool, bool]:
    normalized_payload = _normalized_payload(posting)
    payload_checksum = _sha256_json(normalized_payload)
    scoring_checksum = _sha256_json(_scoring_payload(posting))
    stored_payload = _stored_normalized_payload(posting)
    observation = session.scalar(
        select(JobSourceObservationModel)
        .options(selectinload(JobSourceObservationModel.job_lead))
        .where(
            JobSourceObservationModel.source_configuration_id == source.id,
            JobSourceObservationModel.provider == source.provider,
            JobSourceObservationModel.external_post_id == posting.external_id,
        )
    )
    created = observation is None
    scoring_change = created

    if observation is None:
        job_lead = JobLeadModel(
            id=new_uuid(),
            source=JobLeadSource.GREENHOUSE.value,
            source_url=_normalize_optional_str(posting.source_url),
            external_id=f"{source.id}:{posting.external_id}",
            company_name=posting.company_name.strip(),
            title=posting.title.strip(),
            location_text=_normalize_optional_str(posting.location_text),
            workplace_type=posting.workplace_type.value if posting.workplace_type else None,
            description_raw=posting.description_raw.strip(),
            description_normalized=posting.description_normalized.strip(),
            compensation_text=_normalize_optional_str(posting.compensation_text),
            discovered_at=observed_at,
            source_posting_status=SourcePostingStatus.OPEN.value,
        )
        session.add(job_lead)
        session.flush()
        observation = JobSourceObservationModel(
            id=new_uuid(),
            source_configuration_id=source.id,
            job_lead_id=job_lead.id,
            provider=source.provider,
            external_post_id=posting.external_id,
            external_internal_job_id=_normalize_optional_str(posting.internal_job_id),
            canonical_url=_normalize_optional_str(posting.source_url),
            first_seen_at=observed_at,
            last_seen_at=observed_at,
            source_updated_at=posting.source_updated_at,
            active=True,
            removed_at=None,
            payload_checksum=payload_checksum,
            scoring_checksum=scoring_checksum,
            duplicate_hint_key=duplicate_hint_key(posting),
            normalized_payload=stored_payload,
            raw_payload=posting.raw_payload if retain_raw_payload else None,
        )
        session.add(observation)
        session.flush()
        return observation, created, True, True

    scoring_change = observation.scoring_checksum != scoring_checksum
    payload_changed = observation.payload_checksum != payload_checksum
    reactivated = not observation.active
    observation.last_seen_at = observed_at
    observation.source_updated_at = posting.source_updated_at
    observation.active = True
    observation.removed_at = None
    observation.external_internal_job_id = _normalize_optional_str(posting.internal_job_id)
    observation.canonical_url = _normalize_optional_str(posting.source_url)
    observation.payload_checksum = payload_checksum
    observation.scoring_checksum = scoring_checksum
    observation.duplicate_hint_key = duplicate_hint_key(posting)
    observation.normalized_payload = stored_payload
    observation.raw_payload = posting.raw_payload if retain_raw_payload else None
    _apply_job_fields(observation.job_lead, posting)
    session.add(observation)
    session.add(observation.job_lead)
    return observation, created, payload_changed or reactivated, scoring_change
