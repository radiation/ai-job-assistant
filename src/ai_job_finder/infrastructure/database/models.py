from __future__ import annotations

from datetime import datetime
from typing import Any
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

from ai_job_finder.domain.candidate import CandidateProfileSnapshot, CareerFactSnapshot
from ai_job_finder.domain.common import utc_now
from ai_job_finder.domain.enums import (
    CareerFactCategory,
    CareerFactLifecycle,
    CareerFactProposalReviewStatus,
    EvidenceTag,
    ExtractionRunStatus,
    JobImportRunStatus,
    JobSourceProvider,
    PostingStatus,
    ProvenanceType,
    Recommendation,
    RemotePreference,
    SourceDetectionRunStatus,
    SourceDocumentExtractionStatus,
    SourceDocumentType,
    SourcePostingStatus,
    WorkplaceType,
)
from ai_job_finder.domain.evaluation import EvaluationResult
from ai_job_finder.domain.job_lead import JobLeadSnapshot
from ai_job_finder.domain.job_sources import JobSourceConfigurationSnapshot
from ai_job_finder.infrastructure.database.base import Base


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
        back_populates="candidate_profile", cascade="all, delete-orphan"
    )
    source_documents: Mapped[list[SourceDocumentModel]] = relationship(
        back_populates="candidate_profile", cascade="all, delete-orphan"
    )
    career_fact_proposals: Mapped[list[CareerFactProposalModel]] = relationship(
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
            lifecycle_status=CareerFactLifecycle(self.lifecycle_status),
            evidence_tags=[EvidenceTag(value) for value in self.evidence_tags],
            provenance_type=ProvenanceType(self.provenance_type),
            source_reference=self.source_reference,
            verified_at=self.verified_at,
            archived_at=self.archived_at,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


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
        back_populates="source_documents"
    )
    extraction_runs: Mapped[list[ExtractionRunModel]] = relationship(
        back_populates="source_document", cascade="all, delete-orphan"
    )
    proposals: Mapped[list[CareerFactProposalModel]] = relationship(
        back_populates="source_document", cascade="all, delete-orphan"
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

    source_document: Mapped[SourceDocumentModel] = relationship(back_populates="extraction_runs")
    proposals: Mapped[list[CareerFactProposalModel]] = relationship(
        back_populates="extraction_run", cascade="all, delete-orphan"
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

    source_document: Mapped[SourceDocumentModel] = relationship(back_populates="proposals")
    extraction_run: Mapped[ExtractionRunModel] = relationship(back_populates="proposals")
    candidate_profile: Mapped[CandidateProfileModel] = relationship(
        back_populates="career_fact_proposals"
    )
    duplicate_candidate_fact: Mapped[CareerFactModel | None] = relationship(
        foreign_keys=[duplicate_candidate_fact_id]
    )
    accepted_career_fact: Mapped[CareerFactModel | None] = relationship(
        foreign_keys=[accepted_career_fact_id]
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
    source_posting_status: Mapped[str] = mapped_column(
        String(20), default=SourcePostingStatus.OPEN.value, nullable=False
    )
    posting_status: Mapped[str] = mapped_column(String(20), default=PostingStatus.DISCOVERED.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    evaluations: Mapped[list[JobEvaluationModel]] = relationship(
        back_populates="job_lead", cascade="all, delete-orphan"
    )
    source_observations: Mapped[list[JobSourceObservationModel]] = relationship(
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
        back_populates="source_configuration", cascade="all, delete-orphan"
    )
    observations: Mapped[list[JobSourceObservationModel]] = relationship(
        back_populates="source_configuration", cascade="all, delete-orphan"
    )
    detection_runs: Mapped[list[SourceDetectionRunModel]] = relationship(
        back_populates="created_source_configuration"
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
        back_populates="detection_runs"
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
        back_populates="import_runs"
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
        back_populates="observations"
    )
    job_lead: Mapped[JobLeadModel] = relationship(back_populates="source_observations")


def serialize_model(model: Base) -> dict[str, Any]:
    return {column.name: getattr(model, column.name) for column in model.__table__.columns}
