"""foundation slice

Revision ID: 0001_foundation_slice
Revises:
Create Date: 2026-07-10 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0001_foundation_slice"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candidate_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("preferred_locations", sa.JSON(), nullable=False),
        sa.Column("remote_preference", sa.String(length=20), nullable=False),
        sa.Column("target_levels", sa.JSON(), nullable=False),
        sa.Column("target_functions", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_profiles")),
    )

    op.create_table(
        "job_leads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("external_id", sa.String(length=200), nullable=True),
        sa.Column("company_name", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("location_text", sa.String(length=200), nullable=True),
        sa.Column("workplace_type", sa.String(length=20), nullable=True),
        sa.Column("description_raw", sa.Text(), nullable=False),
        sa.Column("description_normalized", sa.Text(), nullable=False),
        sa.Column("compensation_text", sa.String(length=200), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("posting_status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_leads")),
    )

    op.create_index(
        "ix_job_leads_source_external_id_not_null",
        "job_leads",
        ["source", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
        sqlite_where=sa.text("external_id IS NOT NULL"),
    )

    op.create_table(
        "career_facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_profile_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("source_organization", sa.String(length=200), nullable=True),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("metric", sa.String(length=200), nullable=True),
        sa.Column("technologies", sa.JSON(), nullable=False),
        sa.Column("leadership_scope", sa.String(length=200), nullable=True),
        sa.Column("business_outcome", sa.String(length=500), nullable=True),
        sa.Column("approved_wording", sa.Text(), nullable=False),
        sa.Column("verification_status", sa.String(length=20), nullable=False),
        sa.Column("source_reference", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("statement <> ''", name=op.f("ck_career_facts_statement_not_blank")),
        sa.CheckConstraint(
            "approved_wording <> ''", name=op.f("ck_career_facts_approved_wording_not_blank")
        ),
        sa.ForeignKeyConstraint(
            ["candidate_profile_id"],
            ["candidate_profiles.id"],
            name=op.f("fk_career_facts_candidate_profile_id_candidate_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_career_facts")),
    )

    op.create_table(
        "job_evaluations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("candidate_profile_id", sa.Uuid(), nullable=False),
        sa.Column("job_lead_id", sa.Uuid(), nullable=False),
        sa.Column("scoring_version", sa.String(length=50), nullable=False),
        sa.Column("leadership_scope_score", sa.Integer(), nullable=False),
        sa.Column("technical_alignment_score", sa.Integer(), nullable=False),
        sa.Column("location_score", sa.Integer(), nullable=False),
        sa.Column("level_score", sa.Integer(), nullable=False),
        sa.Column("platform_ownership_score", sa.Integer(), nullable=False),
        sa.Column("referral_priority_score", sa.Integer(), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column("recommendation", sa.String(length=30), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_profile_id"],
            ["candidate_profiles.id"],
            name=op.f("fk_job_evaluations_candidate_profile_id_candidate_profiles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_lead_id"],
            ["job_leads.id"],
            name=op.f("fk_job_evaluations_job_lead_id_job_leads"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_evaluations")),
        sa.UniqueConstraint(
            "candidate_profile_id",
            "job_lead_id",
            "scoring_version",
            name=op.f("uq_job_evaluations_candidate_job_version"),
        ),
    )


def downgrade() -> None:
    op.drop_table("job_evaluations")
    op.drop_table("career_facts")
    op.drop_index("ix_job_leads_source_external_id_not_null", table_name="job_leads")
    op.drop_table("job_leads")
    op.drop_table("candidate_profiles")
