from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
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
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ai_job_finder.domain.common import utc_now
from ai_job_finder.domain.enums import (
    CareerFactProposalReviewStatus,
    ExtractionRunStatus,
    SourceDocumentExtractionStatus,
    SourceDocumentType,
)
from ai_job_finder.infrastructure.database.base import Base

if TYPE_CHECKING:
    from ai_job_finder.infrastructure.database.models.candidate import (
        CandidateProfileModel,
        CareerFactModel,
    )

__all__ = ["CareerFactProposalModel", "ExtractionRunModel", "SourceDocumentModel"]


class SourceDocumentModel(Base):
    __tablename__ = "source_documents"
    __table_args__ = (
        Index(
            "ix_source_documents_candidate_checksum",
            "candidate_profile_id",
            "checksum_sha256",
            unique=True,
        ),
        Index("ix_source_documents_candidate_profile_id", "candidate_profile_id"),
        Index("ix_source_documents_extraction_status", "extraction_status"),
        Index("ix_source_documents_uploaded_at", "uploaded_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    candidate_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE")
    )
    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    byte_size: Mapped[int] = mapped_column(Integer)
    checksum_sha256: Mapped[str] = mapped_column(String(64))
    source_type: Mapped[str] = mapped_column(String(40), default=SourceDocumentType.OTHER.value)
    storage_key: Mapped[str] = mapped_column(String(500))
    extraction_status: Mapped[str] = mapped_column(
        String(40), default=SourceDocumentExtractionStatus.UPLOADED.value
    )
    extracted_text: Mapped[str | None] = mapped_column(Text)
    extraction_error: Mapped[str | None] = mapped_column(Text)
    upload_note: Mapped[str | None] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    candidate_profile: Mapped[CandidateProfileModel] = relationship(
        "CandidateProfileModel", back_populates="source_documents"
    )
    extraction_runs: Mapped[list[ExtractionRunModel]] = relationship(
        "ExtractionRunModel", back_populates="source_document", cascade="all, delete-orphan"
    )
    proposals: Mapped[list[CareerFactProposalModel]] = relationship(
        "CareerFactProposalModel", back_populates="source_document", cascade="all, delete-orphan"
    )


class ExtractionRunModel(Base):
    __tablename__ = "extraction_runs"
    __table_args__ = (
        Index("ix_extraction_runs_source_document_id", "source_document_id"),
        Index("ix_extraction_runs_status", "status"),
        Index("ix_extraction_runs_started_at", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source_document_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE")
    )
    provider: Mapped[str] = mapped_column(String(50))
    model_id: Mapped[str] = mapped_column(String(200))
    prompt_version: Mapped[str] = mapped_column(String(100))
    schema_version: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default=ExtractionRunStatus.RUNNING.value)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_character_count: Mapped[int] = mapped_column(Integer, default=0)
    input_token_count: Mapped[int | None] = mapped_column(Integer)
    output_token_count: Mapped[int | None] = mapped_column(Integer)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    temperature: Mapped[float | None] = mapped_column(Float)
    raw_response: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    source_document: Mapped[SourceDocumentModel] = relationship(
        "SourceDocumentModel", back_populates="extraction_runs"
    )
    proposals: Mapped[list[CareerFactProposalModel]] = relationship(
        "CareerFactProposalModel", back_populates="extraction_run", cascade="all, delete-orphan"
    )


class CareerFactProposalModel(Base):
    __tablename__ = "career_fact_proposals"
    __table_args__ = (
        CheckConstraint("proposed_statement <> ''", name="proposed_statement_not_blank"),
        CheckConstraint("supporting_excerpt <> ''", name="supporting_excerpt_not_blank"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_bounded"),
        Index("ix_career_fact_proposals_source_document_id", "source_document_id"),
        Index("ix_career_fact_proposals_extraction_run_id", "extraction_run_id"),
        Index("ix_career_fact_proposals_candidate_profile_id", "candidate_profile_id"),
        Index("ix_career_fact_proposals_review_status", "review_status"),
        Index("ix_career_fact_proposals_category", "proposed_category"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source_document_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE")
    )
    extraction_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE")
    )
    candidate_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidate_profiles.id", ondelete="CASCADE")
    )
    proposed_category: Mapped[str] = mapped_column(String(50))
    proposed_source_organization: Mapped[str | None] = mapped_column(String(200))
    proposed_statement: Mapped[str] = mapped_column(Text)
    proposed_metric: Mapped[str | None] = mapped_column(String(200))
    proposed_technologies: Mapped[list[str]] = mapped_column(JSON, default=list)
    proposed_leadership_scope: Mapped[str | None] = mapped_column(String(200))
    proposed_business_outcome: Mapped[str | None] = mapped_column(String(500))
    proposed_approved_wording: Mapped[str | None] = mapped_column(Text)
    proposed_evidence_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    supporting_excerpt: Mapped[str] = mapped_column(Text)
    source_location: Mapped[str | None] = mapped_column(String(200))
    confidence: Mapped[float] = mapped_column(Float)
    review_status: Mapped[str] = mapped_column(
        String(30), default=CareerFactProposalReviewStatus.PENDING.value
    )
    duplicate_candidate_fact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("career_facts.id", ondelete="SET NULL")
    )
    accepted_career_fact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("career_facts.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    source_document: Mapped[SourceDocumentModel] = relationship(
        "SourceDocumentModel", back_populates="proposals"
    )
    extraction_run: Mapped[ExtractionRunModel] = relationship(
        "ExtractionRunModel", back_populates="proposals"
    )
    candidate_profile: Mapped[CandidateProfileModel] = relationship(
        "CandidateProfileModel", back_populates="career_fact_proposals"
    )
    duplicate_candidate_fact: Mapped[CareerFactModel | None] = relationship(
        "CareerFactModel", foreign_keys=[duplicate_candidate_fact_id]
    )
    accepted_career_fact: Mapped[CareerFactModel | None] = relationship(
        "CareerFactModel", foreign_keys=[accepted_career_fact_id]
    )
