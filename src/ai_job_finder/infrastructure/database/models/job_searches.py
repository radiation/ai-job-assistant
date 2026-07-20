from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
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
from ai_job_finder.domain.enums import WorkplaceType
from ai_job_finder.domain.job_searches import (
    JobSearchDefinitionSnapshot,
    JobSearchDomain,
    JobSearchRunStatus,
    JobSearchSeniority,
)
from ai_job_finder.infrastructure.database.base import Base

if TYPE_CHECKING:
    from ai_job_finder.infrastructure.database.models.jobs import (
        JobEvaluationModel,
        JobLeadModel,
    )

__all__ = [
    "JobSearchDefinitionModel",
    "JobSearchMatchModel",
    "JobSearchRunModel",
]


class JobSearchDefinitionModel(Base):
    __tablename__ = "job_search_definitions"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="job_search_definitions_name_not_blank"),
        CheckConstraint(
            "minimum_score_threshold >= 0 AND minimum_score_threshold <= 100",
            name="job_search_definitions_threshold_range",
        ),
        UniqueConstraint("name", name="uq_job_search_definitions_name"),
        Index("ix_job_search_definitions_enabled", "enabled"),
        Index("ix_job_search_definitions_last_run_at", "last_run_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    title_include_patterns: Mapped[list[str]] = mapped_column(JSON, default=list)
    title_exclude_patterns: Mapped[list[str]] = mapped_column(JSON, default=list)
    target_domains: Mapped[list[str]] = mapped_column(JSON, default=list)
    target_seniority_levels: Mapped[list[str]] = mapped_column(JSON, default=list)
    allowed_locations: Mapped[list[str]] = mapped_column(JSON, default=list)
    allowed_remote_geographies: Mapped[list[str]] = mapped_column(JSON, default=list)
    allowed_workplace_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    minimum_score_threshold: Mapped[float] = mapped_column(Float, default=0.0)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    runs: Mapped[list[JobSearchRunModel]] = relationship(
        "JobSearchRunModel",
        back_populates="search_definition",
        cascade="all, delete-orphan",
    )
    matches: Mapped[list[JobSearchMatchModel]] = relationship(
        "JobSearchMatchModel",
        back_populates="search_definition",
        cascade="all, delete-orphan",
    )

    def to_snapshot(self) -> JobSearchDefinitionSnapshot:
        return JobSearchDefinitionSnapshot(
            id=self.id,
            name=self.name,
            enabled=self.enabled,
            title_include_patterns=list(self.title_include_patterns),
            title_exclude_patterns=list(self.title_exclude_patterns),
            target_domains=[JobSearchDomain(value) for value in self.target_domains],
            target_seniority_levels=[
                JobSearchSeniority(value) for value in self.target_seniority_levels
            ],
            allowed_locations=list(self.allowed_locations),
            allowed_remote_geographies=list(self.allowed_remote_geographies),
            allowed_workplace_types=[
                WorkplaceType(value) for value in self.allowed_workplace_types
            ],
            minimum_score_threshold=self.minimum_score_threshold,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class JobSearchRunModel(Base):
    __tablename__ = "job_search_runs"
    __table_args__ = (
        CheckConstraint(
            "candidates_considered >= 0 AND matched_by_criteria >= 0 AND evaluated_count >= 0 "
            "AND above_threshold_count >= 0 AND excluded_count >= 0 AND failures_count >= 0",
            name="job_search_runs_nonnegative_counters",
        ),
        CheckConstraint(
            "((status = 'running') AND completed_at IS NULL) OR "
            "((status <> 'running') AND completed_at IS NOT NULL)",
            name="job_search_runs_completed_at_consistent",
        ),
        Index("ix_job_search_runs_search_definition_id", "search_definition_id"),
        Index(
            "ix_job_search_runs_single_running_per_definition",
            "search_definition_id",
            unique=True,
            sqlite_where=text("status = 'running'"),
            postgresql_where=text("status = 'running'"),
        ),
        Index("ix_job_search_runs_status", "status"),
        Index("ix_job_search_runs_started_at", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    search_definition_id: Mapped[UUID] = mapped_column(
        ForeignKey("job_search_definitions.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(30), default=JobSearchRunStatus.RUNNING.value)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    candidates_considered: Mapped[int] = mapped_column(Integer, default=0)
    matched_by_criteria: Mapped[int] = mapped_column(Integer, default=0)
    evaluated_count: Mapped[int] = mapped_column(Integer, default=0)
    above_threshold_count: Mapped[int] = mapped_column(Integer, default=0)
    excluded_count: Mapped[int] = mapped_column(Integer, default=0)
    failures_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    search_definition: Mapped[JobSearchDefinitionModel] = relationship(
        "JobSearchDefinitionModel", back_populates="runs"
    )
    matches: Mapped[list[JobSearchMatchModel]] = relationship(
        "JobSearchMatchModel",
        back_populates="search_run",
        cascade="all, delete-orphan",
    )


class JobSearchMatchModel(Base):
    __tablename__ = "job_search_matches"
    __table_args__ = (
        UniqueConstraint(
            "search_run_id",
            "job_lead_id",
            name="uq_job_search_matches_search_run_job_lead",
        ),
        Index("ix_job_search_matches_search_definition_id", "search_definition_id"),
        Index("ix_job_search_matches_search_run_id", "search_run_id"),
        Index("ix_job_search_matches_job_lead_id", "job_lead_id"),
        Index("ix_job_search_matches_matched", "matched"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    search_definition_id: Mapped[UUID] = mapped_column(
        ForeignKey("job_search_definitions.id", ondelete="CASCADE")
    )
    search_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("job_search_runs.id", ondelete="CASCADE")
    )
    job_lead_id: Mapped[UUID] = mapped_column(ForeignKey("job_leads.id", ondelete="CASCADE"))
    job_evaluation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("job_evaluations.id", ondelete="SET NULL")
    )
    scoring_version: Mapped[str | None] = mapped_column(String(50))
    score_at_match_time: Mapped[float | None] = mapped_column(Float)
    recommendation_at_match_time: Mapped[str | None] = mapped_column(String(30))
    criteria_matched: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    above_threshold: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    matched: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    matched_criteria: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    exclusion_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    inferred_domains: Mapped[list[str]] = mapped_column(JSON, default=list)
    inferred_seniority_levels: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    search_definition: Mapped[JobSearchDefinitionModel] = relationship(
        "JobSearchDefinitionModel", back_populates="matches"
    )
    search_run: Mapped[JobSearchRunModel] = relationship(
        "JobSearchRunModel", back_populates="matches"
    )
    job_lead: Mapped[JobLeadModel] = relationship("JobLeadModel")
    job_evaluation: Mapped[JobEvaluationModel | None] = relationship("JobEvaluationModel")
