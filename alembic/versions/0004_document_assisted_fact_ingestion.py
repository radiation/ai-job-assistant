"""document assisted career fact ingestion

Revision ID: 0004_document_ingestion
Revises: 0003_evaluation_history
Create Date: 2026-07-11 00:00:02.000000

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0004_document_ingestion"
down_revision = "0003_evaluation_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_profile_id", sa.Uuid(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("extraction_status", sa.String(length=40), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("extraction_error", sa.Text(), nullable=True),
        sa.Column("upload_note", sa.Text(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_profile_id"], ["candidate_profiles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_source_documents_candidate_checksum",
        "source_documents",
        ["candidate_profile_id", "checksum_sha256"],
        unique=True,
    )
    op.create_index(
        "ix_source_documents_candidate_profile_id",
        "source_documents",
        ["candidate_profile_id"],
    )
    op.create_index(
        "ix_source_documents_extraction_status",
        "source_documents",
        ["extraction_status"],
    )
    op.create_index("ix_source_documents_uploaded_at", "source_documents", ["uploaded_at"])

    op.create_table(
        "extraction_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_document_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("prompt_version", sa.String(length=100), nullable=False),
        sa.Column("schema_version", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_character_count", sa.Integer(), nullable=False),
        sa.Column("input_token_count", sa.Integer(), nullable=True),
        sa.Column("output_token_count", sa.Integer(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_document_id"], ["source_documents.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_extraction_runs_source_document_id", "extraction_runs", ["source_document_id"]
    )
    op.create_index("ix_extraction_runs_status", "extraction_runs", ["status"])
    op.create_index("ix_extraction_runs_started_at", "extraction_runs", ["started_at"])

    op.create_table(
        "career_fact_proposals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_document_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_run_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_profile_id", sa.Uuid(), nullable=False),
        sa.Column("proposed_category", sa.String(length=50), nullable=False),
        sa.Column("proposed_source_organization", sa.String(length=200), nullable=True),
        sa.Column("proposed_statement", sa.Text(), nullable=False),
        sa.Column("proposed_metric", sa.String(length=200), nullable=True),
        sa.Column("proposed_technologies", sa.JSON(), nullable=False),
        sa.Column("proposed_leadership_scope", sa.String(length=200), nullable=True),
        sa.Column("proposed_business_outcome", sa.String(length=500), nullable=True),
        sa.Column("proposed_approved_wording", sa.Text(), nullable=True),
        sa.Column("proposed_evidence_tags", sa.JSON(), nullable=False),
        sa.Column("supporting_excerpt", sa.Text(), nullable=False),
        sa.Column("source_location", sa.String(length=200), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("review_status", sa.String(length=30), nullable=False),
        sa.Column("duplicate_candidate_fact_id", sa.Uuid(), nullable=True),
        sa.Column("accepted_career_fact_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_bounded"),
        sa.CheckConstraint("proposed_statement <> ''", name="proposed_statement_not_blank"),
        sa.CheckConstraint("supporting_excerpt <> ''", name="supporting_excerpt_not_blank"),
        sa.ForeignKeyConstraint(
            ["accepted_career_fact_id"], ["career_facts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_profile_id"], ["candidate_profiles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["duplicate_candidate_fact_id"], ["career_facts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["extraction_run_id"], ["extraction_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_document_id"], ["source_documents.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_career_fact_proposals_source_document_id",
        "career_fact_proposals",
        ["source_document_id"],
    )
    op.create_index(
        "ix_career_fact_proposals_extraction_run_id", "career_fact_proposals", ["extraction_run_id"]
    )
    op.create_index(
        "ix_career_fact_proposals_candidate_profile_id",
        "career_fact_proposals",
        ["candidate_profile_id"],
    )
    op.create_index(
        "ix_career_fact_proposals_review_status", "career_fact_proposals", ["review_status"]
    )
    op.create_index(
        "ix_career_fact_proposals_category", "career_fact_proposals", ["proposed_category"]
    )


def downgrade() -> None:
    op.drop_index("ix_career_fact_proposals_category", table_name="career_fact_proposals")
    op.drop_index("ix_career_fact_proposals_review_status", table_name="career_fact_proposals")
    op.drop_index(
        "ix_career_fact_proposals_candidate_profile_id", table_name="career_fact_proposals"
    )
    op.drop_index("ix_career_fact_proposals_extraction_run_id", table_name="career_fact_proposals")
    op.drop_index("ix_career_fact_proposals_source_document_id", table_name="career_fact_proposals")
    op.drop_table("career_fact_proposals")

    op.drop_index("ix_extraction_runs_started_at", table_name="extraction_runs")
    op.drop_index("ix_extraction_runs_status", table_name="extraction_runs")
    op.drop_index("ix_extraction_runs_source_document_id", table_name="extraction_runs")
    op.drop_table("extraction_runs")

    op.drop_index("ix_source_documents_uploaded_at", table_name="source_documents")
    op.drop_index("ix_source_documents_extraction_status", table_name="source_documents")
    op.drop_index("ix_source_documents_candidate_profile_id", table_name="source_documents")
    op.drop_index("ix_source_documents_candidate_checksum", table_name="source_documents")
    op.drop_table("source_documents")
