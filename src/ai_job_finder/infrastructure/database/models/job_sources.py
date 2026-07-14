from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ai_job_finder.domain.common import utc_now
from ai_job_finder.domain.enums import (
    JobImportRunStatus,
    JobSourceProvider,
    SourceDetectionRunStatus,
)
from ai_job_finder.domain.job_sources import JobSourceConfigurationSnapshot
from ai_job_finder.infrastructure.database.base import Base

if TYPE_CHECKING:
    from ai_job_finder.infrastructure.database.models.jobs import (
        JobLeadModel,
    )

__all__ = [
    "JobImportRunModel",
    "JobSourceConfigurationModel",
    "JobSourceObservationModel",
    "SourceDetectionRunModel",
]


class JobSourceConfigurationModel(Base):
    __tablename__ = "job_source_configurations"
    __table_args__ = (
        UniqueConstraint("provider", "board_token", name="uq_job_source_provider_board_token"),
        Index("ix_job_source_configurations_enabled", "enabled"),
        Index("ix_job_source_configurations_provider", "provider"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), default=JobSourceProvider.GREENHOUSE.value)
    display_name: Mapped[str] = mapped_column(String(200))
    company_name: Mapped[str] = mapped_column(String(200))
    board_token: Mapped[str] = mapped_column(String(200))
    source_url: Mapped[str | None] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str | None] = mapped_column(String(30))
    last_sync_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    import_runs: Mapped[list[JobImportRunModel]] = relationship(
        "JobImportRunModel", back_populates="source_configuration", cascade="all, delete-orphan"
    )
    observations: Mapped[list[JobSourceObservationModel]] = relationship(
        "JobSourceObservationModel",
        back_populates="source_configuration",
        cascade="all, delete-orphan",
    )
    detection_runs: Mapped[list[SourceDetectionRunModel]] = relationship(
        "SourceDetectionRunModel", back_populates="created_source_configuration"
    )

    def to_snapshot(self) -> JobSourceConfigurationSnapshot:
        return JobSourceConfigurationSnapshot(
            id=self.id,
            provider=JobSourceProvider(self.provider),
            display_name=self.display_name,
            company_name=self.company_name,
            board_token=self.board_token,
            source_url=self.source_url,
            enabled=self.enabled,
            last_successful_sync_at=self.last_successful_sync_at,
            last_sync_status=self.last_sync_status,
            last_sync_error=self.last_sync_error,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class SourceDetectionRunModel(Base):
    __tablename__ = "source_detection_runs"
    __table_args__ = (
        CheckConstraint(
            "((status = 'running') AND completed_at IS NULL) OR "
            "((status <> 'running') AND completed_at IS NOT NULL)",
            name="source_detection_runs_completed_at_consistent",
        ),
        Index("ix_source_detection_runs_status", "status"),
        Index("ix_source_detection_runs_started_at", "started_at"),
        Index(
            "ix_source_detection_runs_created_source_configuration_id",
            "created_source_configuration_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    company_name: Mapped[str | None] = mapped_column(String(200))
    input_url: Mapped[str | None] = mapped_column(String(500))
    normalized_url: Mapped[str | None] = mapped_column(String(500))
    final_url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(
        String(30), default=SourceDetectionRunStatus.RUNNING.value, nullable=False
    )
    detected_provider: Mapped[str | None] = mapped_column(String(50))
    candidate_tokens: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    validated_token: Mapped[str | None] = mapped_column(String(200))
    validated_company_name: Mapped[str | None] = mapped_column(String(200))
    validated_job_count: Mapped[int | None] = mapped_column(Integer)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_source_configuration_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("job_source_configurations.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    created_source_configuration: Mapped[JobSourceConfigurationModel | None] = relationship(
        "JobSourceConfigurationModel", back_populates="detection_runs"
    )


class JobImportRunModel(Base):
    __tablename__ = "job_import_runs"
    __table_args__ = (
        CheckConstraint(
            "jobs_fetched >= 0 AND jobs_created >= 0 AND jobs_updated >= 0 AND jobs_unchanged >= 0 "
            "AND jobs_closed >= 0 AND jobs_failed >= 0 AND evaluations_created >= 0 "
            "AND evaluation_failures >= 0",
            name="job_import_runs_nonnegative_counters",
        ),
        CheckConstraint(
            "((status = 'running') AND completed_at IS NULL) OR "
            "((status <> 'running') AND completed_at IS NOT NULL)",
            name="job_import_runs_completed_at_consistent",
        ),
        Index("ix_job_import_runs_source_configuration_id", "source_configuration_id"),
        Index(
            "ix_job_import_runs_single_running_per_source",
            "source_configuration_id",
            unique=True,
            sqlite_where=text("status = 'running'"),
            postgresql_where=text("status = 'running'"),
        ),
        Index("ix_job_import_runs_status", "status"),
        Index("ix_job_import_runs_started_at", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source_configuration_id: Mapped[UUID] = mapped_column(
        ForeignKey("job_source_configurations.id", ondelete="CASCADE")
    )
    provider: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), default=JobImportRunStatus.RUNNING.value)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    jobs_fetched: Mapped[int] = mapped_column(Integer, default=0)
    jobs_created: Mapped[int] = mapped_column(Integer, default=0)
    jobs_updated: Mapped[int] = mapped_column(Integer, default=0)
    jobs_unchanged: Mapped[int] = mapped_column(Integer, default=0)
    jobs_closed: Mapped[int] = mapped_column(Integer, default=0)
    jobs_failed: Mapped[int] = mapped_column(Integer, default=0)
    evaluations_created: Mapped[int] = mapped_column(Integer, default=0)
    evaluation_failures: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    connector_version: Mapped[str] = mapped_column(String(100), default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    source_configuration: Mapped[JobSourceConfigurationModel] = relationship(
        "JobSourceConfigurationModel", back_populates="import_runs"
    )


class JobSourceObservationModel(Base):
    __tablename__ = "job_source_observations"
    __table_args__ = (
        CheckConstraint(
            "((active IS TRUE) AND removed_at IS NULL) OR "
            "((active IS FALSE) AND removed_at IS NOT NULL)",
            name="job_source_observations_active_removed_consistent",
        ),
        UniqueConstraint(
            "source_configuration_id",
            "provider",
            "external_post_id",
            name="uq_job_source_observation_identity",
        ),
        Index("ix_job_source_observations_source_configuration_id", "source_configuration_id"),
        Index(
            "ix_job_source_observations_source_configuration_active",
            "source_configuration_id",
            "active",
        ),
        Index("ix_job_source_observations_job_lead_id", "job_lead_id"),
        Index("ix_job_source_observations_active", "active"),
        Index("ix_job_source_observations_external_internal_job_id", "external_internal_job_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source_configuration_id: Mapped[UUID] = mapped_column(
        ForeignKey("job_source_configurations.id", ondelete="CASCADE")
    )
    job_lead_id: Mapped[UUID] = mapped_column(ForeignKey("job_leads.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(50))
    external_post_id: Mapped[str] = mapped_column(String(200))
    external_internal_job_id: Mapped[str | None] = mapped_column(String(200))
    canonical_url: Mapped[str | None] = mapped_column(String(500))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload_checksum: Mapped[str] = mapped_column(String(64))
    scoring_checksum: Mapped[str] = mapped_column(String(64))
    duplicate_hint_key: Mapped[str] = mapped_column(String(64))
    normalized_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    source_configuration: Mapped[JobSourceConfigurationModel] = relationship(
        "JobSourceConfigurationModel", back_populates="observations"
    )
    job_lead: Mapped[JobLeadModel] = relationship(
        "JobLeadModel", back_populates="source_observations"
    )
