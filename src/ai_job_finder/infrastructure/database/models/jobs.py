from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Float,
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
from ai_job_finder.domain.enums import (
    PostingStatus,
    Recommendation,
    SourcePostingStatus,
    WorkplaceType,
)
from ai_job_finder.domain.evaluation import EvaluationResult
from ai_job_finder.domain.job_lead import JobLeadSnapshot
from ai_job_finder.infrastructure.database.base import Base

if TYPE_CHECKING:
    from ai_job_finder.infrastructure.database.models.candidate import (
        CandidateProfileModel,
    )
    from ai_job_finder.infrastructure.database.models.job_sources import (
        JobSourceObservationModel,
    )

__all__ = ["JobEvaluationModel", "JobLeadModel"]


class JobLeadModel(Base):
    __tablename__ = "job_leads"
    __table_args__ = (
        Index(
            "ix_job_leads_source_external_id_not_null",
            "source",
            "external_id",
            unique=True,
            sqlite_where=text("external_id IS NOT NULL"),
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source: Mapped[str] = mapped_column(String(50))
    source_url: Mapped[str | None] = mapped_column(String(500))
    external_id: Mapped[str | None] = mapped_column(String(200))
    company_name: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(200))
    location_text: Mapped[str | None] = mapped_column(String(200))
    workplace_type: Mapped[str | None] = mapped_column(String(20))
    description_raw: Mapped[str] = mapped_column(Text)
    description_normalized: Mapped[str] = mapped_column(Text)
    compensation_text: Mapped[str | None] = mapped_column(String(200))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    source_posting_status: Mapped[str] = mapped_column(
        String(20), default=SourcePostingStatus.OPEN.value, nullable=False
    )
    posting_status: Mapped[str] = mapped_column(String(20), default=PostingStatus.DISCOVERED.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    evaluations: Mapped[list[JobEvaluationModel]] = relationship(
        "JobEvaluationModel", back_populates="job_lead", cascade="all, delete-orphan"
    )
    source_observations: Mapped[list[JobSourceObservationModel]] = relationship(
        "JobSourceObservationModel", back_populates="job_lead", cascade="all, delete-orphan"
    )

    def to_snapshot(self) -> JobLeadSnapshot:
        workplace_type = WorkplaceType(self.workplace_type) if self.workplace_type else None
        return JobLeadSnapshot(
            id=self.id,
            source=self.source,
            source_url=self.source_url,
            external_id=self.external_id,
            company_name=self.company_name,
            title=self.title,
            location_text=self.location_text,
            workplace_type=workplace_type,
            description_raw=self.description_raw,
            description_normalized=self.description_normalized,
            compensation_text=self.compensation_text,
            discovered_at=self.discovered_at,
            posting_status=PostingStatus(self.posting_status),
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class JobEvaluationModel(Base):
    __tablename__ = "job_evaluations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    candidate_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE")
    )
    job_lead_id: Mapped[UUID] = mapped_column(ForeignKey("job_leads.id", ondelete="CASCADE"))
    scoring_version: Mapped[str] = mapped_column(String(50))
    leadership_scope_score: Mapped[int] = mapped_column(Integer)
    technical_alignment_score: Mapped[int] = mapped_column(Integer)
    location_score: Mapped[int] = mapped_column(Integer)
    level_score: Mapped[int] = mapped_column(Integer)
    platform_ownership_score: Mapped[int] = mapped_column(Integer)
    referral_priority_score: Mapped[int] = mapped_column(Integer)
    overall_score: Mapped[float] = mapped_column(Float)
    recommendation: Mapped[str] = mapped_column(String(30))
    explanation: Mapped[str] = mapped_column(Text)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    candidate_profile: Mapped[CandidateProfileModel] = relationship(
        "CandidateProfileModel", back_populates="evaluations"
    )
    job_lead: Mapped[JobLeadModel] = relationship("JobLeadModel", back_populates="evaluations")

    def to_snapshot(self) -> EvaluationResult:
        return EvaluationResult(
            id=self.id,
            candidate_profile_id=self.candidate_profile_id,
            job_lead_id=self.job_lead_id,
            scoring_version=self.scoring_version,
            leadership_scope_score=self.leadership_scope_score,
            technical_alignment_score=self.technical_alignment_score,
            location_score=self.location_score,
            level_score=self.level_score,
            platform_ownership_score=self.platform_ownership_score,
            referral_priority_score=self.referral_priority_score,
            overall_score=self.overall_score,
            recommendation=Recommendation(self.recommendation),
            explanation=self.explanation,
            evaluated_at=self.evaluated_at,
        )
