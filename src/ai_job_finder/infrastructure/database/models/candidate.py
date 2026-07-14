from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ai_job_finder.domain.candidate import CandidateProfileSnapshot, CareerFactSnapshot
from ai_job_finder.domain.common import utc_now
from ai_job_finder.domain.enums import (
    CareerFactCategory,
    CareerFactLifecycle,
    EvidenceTag,
    ProvenanceType,
    RemotePreference,
)
from ai_job_finder.infrastructure.database.base import Base

if TYPE_CHECKING:
    from ai_job_finder.infrastructure.database.models.documents import (
        CareerFactProposalModel,
        SourceDocumentModel,
    )
    from ai_job_finder.infrastructure.database.models.jobs import (
        JobEvaluationModel,
    )

__all__ = ["CandidateProfileModel", "CareerFactModel"]


class CandidateProfileModel(Base):
    __tablename__ = "candidate_profiles"
    __table_args__ = (
        Index(
            "ix_candidate_profiles_single_active",
            "is_active",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200))
    preferred_locations: Mapped[list[str]] = mapped_column(JSON, default=list)
    acceptable_remote_geographies: Mapped[list[str]] = mapped_column(JSON, default=list)
    remote_preference: Mapped[str] = mapped_column(String(20))
    target_levels: Mapped[list[str]] = mapped_column(JSON, default=list)
    target_functions: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    career_facts: Mapped[list[CareerFactModel]] = relationship(
        "CareerFactModel", back_populates="candidate_profile", cascade="all, delete-orphan"
    )
    source_documents: Mapped[list[SourceDocumentModel]] = relationship(
        "SourceDocumentModel", back_populates="candidate_profile", cascade="all, delete-orphan"
    )
    career_fact_proposals: Mapped[list[CareerFactProposalModel]] = relationship(
        "CareerFactProposalModel", back_populates="candidate_profile", cascade="all, delete-orphan"
    )
    evaluations: Mapped[list[JobEvaluationModel]] = relationship(
        "JobEvaluationModel", back_populates="candidate_profile", cascade="all, delete-orphan"
    )

    def to_snapshot(self) -> CandidateProfileSnapshot:
        return CandidateProfileSnapshot(
            id=self.id,
            full_name=self.full_name,
            preferred_locations=list(self.preferred_locations),
            acceptable_remote_geographies=list(self.acceptable_remote_geographies),
            remote_preference=RemotePreference(self.remote_preference),
            target_levels=list(self.target_levels),
            target_functions=list(self.target_functions),
            is_active=self.is_active,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class CareerFactModel(Base):
    __tablename__ = "career_facts"
    __table_args__ = (
        CheckConstraint("statement <> ''", name="statement_not_blank"),
        CheckConstraint("approved_wording <> ''", name="approved_wording_not_blank"),
        Index("ix_career_facts_candidate_profile_id", "candidate_profile_id"),
        Index("ix_career_facts_lifecycle_status", "lifecycle_status"),
        Index("ix_career_facts_category", "category"),
        Index("ix_career_facts_source_organization", "source_organization"),
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
    lifecycle_status: Mapped[str] = mapped_column(String(20))
    evidence_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    provenance_type: Mapped[str] = mapped_column(String(40))
    source_reference: Mapped[str] = mapped_column(String(500))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    candidate_profile: Mapped[CandidateProfileModel] = relationship(
        "CandidateProfileModel", back_populates="career_facts"
    )

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
            lifecycle_status=CareerFactLifecycle(self.lifecycle_status),
            evidence_tags=[EvidenceTag(value) for value in self.evidence_tags],
            provenance_type=ProvenanceType(self.provenance_type),
            source_reference=self.source_reference,
            verified_at=self.verified_at,
            archived_at=self.archived_at,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )
