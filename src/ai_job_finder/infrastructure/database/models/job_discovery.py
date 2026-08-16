from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ai_job_finder.domain.common import utc_now
from ai_job_finder.domain.job_discovery import (
    JobDiscoveryObservationStatus,
    JobDiscoveryQueryStatus,
    JobDiscoveryRunStatus,
)
from ai_job_finder.infrastructure.database.base import Base

if TYPE_CHECKING:
    from ai_job_finder.infrastructure.database.models.job_searches import (
        JobSearchDefinitionModel,
        JobSearchRunModel,
    )
    from ai_job_finder.infrastructure.database.models.job_sources import (
        JobImportRunModel,
        JobSourceConfigurationModel,
        SourceDetectionRunModel,
    )
    from ai_job_finder.infrastructure.database.models.jobs import JobLeadModel


__all__ = [
    "JobDiscoveryObservationModel",
    "JobDiscoveryQueryModel",
    "JobDiscoveryRunModel",
]


class JobDiscoveryRunModel(Base):
    __tablename__ = "job_discovery_runs"
    __table_args__ = (
        CheckConstraint(
            "generated_query_count >= 0 AND provider_result_count >= 0 AND unique_url_count >= 0 "
            "AND duplicate_count >= 0 AND detected_count >= 0 AND unsupported_count >= 0 "
            "AND ambiguous_count >= 0 AND imported_lead_count >= 0 AND evaluated_count >= 0 "
            "AND final_matched_count >= 0 AND failure_count >= 0",
            name="job_discovery_runs_nonnegative_counters",
        ),
        CheckConstraint(
            "((status = 'running') AND completed_at IS NULL) OR "
            "((status <> 'running') AND completed_at IS NOT NULL)",
            name="job_discovery_runs_completed_at_consistent",
        ),
        Index("ix_job_discovery_runs_search_definition_id", "search_definition_id"),
        Index(
            "ix_job_discovery_runs_single_running_per_definition",
            "search_definition_id",
            unique=True,
            sqlite_where=text("status = 'running'"),
            postgresql_where=text("status = 'running'"),
        ),
        Index("ix_job_discovery_runs_status", "status"),
        Index("ix_job_discovery_runs_started_at", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    search_definition_id: Mapped[UUID] = mapped_column(
        ForeignKey("job_search_definitions.id", ondelete="CASCADE")
    )
    provider: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), default=JobDiscoveryRunStatus.RUNNING.value)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generated_query_count: Mapped[int] = mapped_column(Integer, default=0)
    provider_result_count: Mapped[int] = mapped_column(Integer, default=0)
    unique_url_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    detected_count: Mapped[int] = mapped_column(Integer, default=0)
    unsupported_count: Mapped[int] = mapped_column(Integer, default=0)
    ambiguous_count: Mapped[int] = mapped_column(Integer, default=0)
    imported_lead_count: Mapped[int] = mapped_column(Integer, default=0)
    evaluated_count: Mapped[int] = mapped_column(Integer, default=0)
    final_matched_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text)
    saved_search_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("job_search_runs.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    search_definition: Mapped[JobSearchDefinitionModel] = relationship("JobSearchDefinitionModel")
    saved_search_run: Mapped[JobSearchRunModel | None] = relationship("JobSearchRunModel")
    queries: Mapped[list[JobDiscoveryQueryModel]] = relationship(
        "JobDiscoveryQueryModel",
        back_populates="discovery_run",
        cascade="all, delete-orphan",
    )
    observations: Mapped[list[JobDiscoveryObservationModel]] = relationship(
        "JobDiscoveryObservationModel",
        back_populates="discovery_run",
        cascade="all, delete-orphan",
    )


class JobDiscoveryQueryModel(Base):
    __tablename__ = "job_discovery_queries"
    __table_args__ = (
        CheckConstraint(
            "ordinal > 0 AND requested_result_limit > 0 AND returned_result_count >= 0",
            name="job_discovery_queries_positive_counts",
        ),
        Index("ix_job_discovery_queries_run_id", "discovery_run_id"),
        Index("ix_job_discovery_queries_status", "status"),
        Index("ix_job_discovery_queries_stable_query_id", "stable_query_id"),
        Index(
            "ix_job_discovery_queries_unique_ordinal_per_run",
            "discovery_run_id",
            "ordinal",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    discovery_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("job_discovery_runs.id", ondelete="CASCADE")
    )
    stable_query_id: Mapped[str] = mapped_column(String(64))
    ordinal: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), default=JobDiscoveryQueryStatus.PENDING.value)
    query_text: Mapped[str] = mapped_column(String(300))
    title_phrase: Mapped[str] = mapped_column(String(200))
    target_domain: Mapped[str | None] = mapped_column(String(200))
    location_or_workplace_term: Mapped[str | None] = mapped_column(String(200))
    requested_result_limit: Mapped[int] = mapped_column(Integer)
    returned_result_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    discovery_run: Mapped[JobDiscoveryRunModel] = relationship(
        "JobDiscoveryRunModel", back_populates="queries"
    )
    primary_observations: Mapped[list[JobDiscoveryObservationModel]] = relationship(
        "JobDiscoveryObservationModel",
        back_populates="primary_query",
    )


class JobDiscoveryObservationModel(Base):
    __tablename__ = "job_discovery_observations"
    __table_args__ = (
        CheckConstraint("rank >= 0", name="job_discovery_observations_rank_nonnegative"),
        Index("ix_job_discovery_observations_run_id", "discovery_run_id"),
        Index("ix_job_discovery_observations_status", "processing_status"),
        Index(
            "ix_job_discovery_observations_source_detection_run_id",
            "source_detection_run_id",
        ),
        Index(
            "ix_job_discovery_observations_unique_url_per_run",
            "discovery_run_id",
            "normalized_url",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    discovery_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("job_discovery_runs.id", ondelete="CASCADE")
    )
    primary_query_id: Mapped[UUID] = mapped_column(
        ForeignKey("job_discovery_queries.id", ondelete="CASCADE")
    )
    query_ordinals: Mapped[list[int]] = mapped_column(JSON, default=list)
    provider: Mapped[str] = mapped_column(String(50))
    provider_result_id: Mapped[str | None] = mapped_column(String(200))
    discovered_url: Mapped[str] = mapped_column(String(500))
    normalized_url: Mapped[str] = mapped_column(String(500))
    title_hint: Mapped[str | None] = mapped_column(String(200))
    company_hint: Mapped[str | None] = mapped_column(String(200))
    location_hint: Mapped[str | None] = mapped_column(String(200))
    evidence_snippet: Mapped[str | None] = mapped_column(String(1000))
    rank: Mapped[int] = mapped_column(Integer, default=0)
    source_detection_outcome: Mapped[str | None] = mapped_column(String(30))
    source_detection_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("source_detection_runs.id", ondelete="SET NULL")
    )
    source_configuration_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("job_source_configurations.id", ondelete="SET NULL")
    )
    import_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("job_import_runs.id", ondelete="SET NULL")
    )
    imported_job_lead_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("job_leads.id", ondelete="SET NULL")
    )
    processing_status: Mapped[str] = mapped_column(
        String(30), default=JobDiscoveryObservationStatus.PENDING.value
    )
    exclusion_reason: Mapped[str | None] = mapped_column(Text)
    discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    discovery_run: Mapped[JobDiscoveryRunModel] = relationship(
        "JobDiscoveryRunModel", back_populates="observations"
    )
    primary_query: Mapped[JobDiscoveryQueryModel] = relationship(
        "JobDiscoveryQueryModel", back_populates="primary_observations"
    )
    source_detection_run: Mapped[SourceDetectionRunModel | None] = relationship(
        "SourceDetectionRunModel"
    )
    source_configuration: Mapped[JobSourceConfigurationModel | None] = relationship(
        "JobSourceConfigurationModel"
    )
    import_run: Mapped[JobImportRunModel | None] = relationship("JobImportRunModel")
    imported_job_lead: Mapped[JobLeadModel | None] = relationship("JobLeadModel")
