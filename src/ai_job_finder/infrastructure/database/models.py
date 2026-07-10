from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
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

from ai_job_finder.domain.candidate import CandidateProfileSnapshot, CareerFactSnapshot
from ai_job_finder.domain.common import utc_now
from ai_job_finder.domain.enums import (
    CareerFactCategory,
    PostingStatus,
    Recommendation,
    RemotePreference,
    VerificationStatus,
    WorkplaceType,
)
from ai_job_finder.domain.evaluation import EvaluationResult
from ai_job_finder.domain.job_lead import JobLeadSnapshot
from ai_job_finder.infrastructure.database.base import Base


class CandidateProfileModel(Base):
    __tablename__ = "candidate_profiles"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200))
    preferred_locations: Mapped[list[str]] = mapped_column(JSON, default=list)
    remote_preference: Mapped[str] = mapped_column(String(20))
    target_levels: Mapped[list[str]] = mapped_column(JSON, default=list)
    target_functions: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    career_facts: Mapped[list[CareerFactModel]] = relationship(
        back_populates="candidate_profile", cascade="all, delete-orphan"
    )
    evaluations: Mapped[list[JobEvaluationModel]] = relationship(
        back_populates="candidate_profile", cascade="all, delete-orphan"
    )

    def to_snapshot(self) -> CandidateProfileSnapshot:
        return CandidateProfileSnapshot(
            id=self.id,
            full_name=self.full_name,
            preferred_locations=list(self.preferred_locations),
            remote_preference=RemotePreference(self.remote_preference),
            target_levels=list(self.target_levels),
            target_functions=list(self.target_functions),
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class CareerFactModel(Base):
    __tablename__ = "career_facts"
    __table_args__ = (
        CheckConstraint("statement <> ''", name="statement_not_blank"),
        CheckConstraint("approved_wording <> ''", name="approved_wording_not_blank"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    candidate_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE")
    )
    category: Mapped[str] = mapped_column(String(50))
    source_organization: Mapped[str | None] = mapped_column(String(200))
    statement: Mapped[str] = mapped_column(Text)
    metric: Mapped[str | None] = mapped_column(String(200))
    technologies: Mapped[list[str]] = mapped_column(JSON, default=list)
    leadership_scope: Mapped[str | None] = mapped_column(String(200))
    business_outcome: Mapped[str | None] = mapped_column(String(500))
    approved_wording: Mapped[str] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(String(20))
    source_reference: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    candidate_profile: Mapped[CandidateProfileModel] = relationship(back_populates="career_facts")

    def to_snapshot(self) -> CareerFactSnapshot:
        return CareerFactSnapshot(
            id=self.id,
            candidate_profile_id=self.candidate_profile_id,
            category=CareerFactCategory(self.category),
            source_organization=self.source_organization,
            statement=self.statement,
            metric=self.metric,
            technologies=list(self.technologies),
            leadership_scope=self.leadership_scope,
            business_outcome=self.business_outcome,
            approved_wording=self.approved_wording,
            verification_status=VerificationStatus(self.verification_status),
            source_reference=self.source_reference,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


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
    posting_status: Mapped[str] = mapped_column(String(20), default=PostingStatus.DISCOVERED.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    evaluations: Mapped[list[JobEvaluationModel]] = relationship(
        back_populates="job_lead", cascade="all, delete-orphan"
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
    __table_args__ = (
        UniqueConstraint(
            "candidate_profile_id", "job_lead_id", "scoring_version", name="candidate_job_version"
        ),
    )

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

    candidate_profile: Mapped[CandidateProfileModel] = relationship(back_populates="evaluations")
    job_lead: Mapped[JobLeadModel] = relationship(back_populates="evaluations")

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


def serialize_model(model: Base) -> dict[str, Any]:
    return {column.name: getattr(model, column.name) for column in model.__table__.columns}
