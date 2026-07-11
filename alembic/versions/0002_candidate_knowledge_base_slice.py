"""candidate knowledge base slice

Revision ID: 0002_candidate_kb
Revises: 0001_foundation_slice
Create Date: 2026-07-11 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0002_candidate_kb"
down_revision = "0001_foundation_slice"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidate_profiles",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index(
        "ix_candidate_profiles_single_active",
        "candidate_profiles",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
        sqlite_where=sa.text("is_active = 1"),
    )

    op.add_column(
        "career_facts",
        sa.Column("lifecycle_status", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "career_facts",
        sa.Column("evidence_tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "career_facts",
        sa.Column(
            "provenance_type",
            sa.String(length=40),
            nullable=False,
            server_default="other",
        ),
    )
    op.add_column(
        "career_facts",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "career_facts",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute(
        """
        UPDATE career_facts
        SET lifecycle_status = CASE
            WHEN verification_status = 'verified' THEN 'verified'
            ELSE 'draft'
        END
        """
    )
    op.execute(
        """
        UPDATE career_facts
        SET verified_at = updated_at
        WHERE verification_status = 'verified'
        """
    )

    op.alter_column("career_facts", "lifecycle_status", nullable=False)
    op.drop_column("career_facts", "verification_status")

    op.create_index(
        "ix_career_facts_candidate_profile_id",
        "career_facts",
        ["candidate_profile_id"],
    )
    op.create_index("ix_career_facts_lifecycle_status", "career_facts", ["lifecycle_status"])
    op.create_index("ix_career_facts_category", "career_facts", ["category"])
    op.create_index(
        "ix_career_facts_source_organization",
        "career_facts",
        ["source_organization"],
    )


def downgrade() -> None:
    op.drop_index("ix_career_facts_source_organization", table_name="career_facts")
    op.drop_index("ix_career_facts_category", table_name="career_facts")
    op.drop_index("ix_career_facts_lifecycle_status", table_name="career_facts")
    op.drop_index("ix_career_facts_candidate_profile_id", table_name="career_facts")

    op.add_column(
        "career_facts",
        sa.Column(
            "verification_status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
    )
    op.execute(
        """
        UPDATE career_facts
        SET verification_status = CASE
            WHEN lifecycle_status = 'verified' THEN 'verified'
            ELSE 'pending'
        END
        """
    )

    op.drop_column("career_facts", "archived_at")
    op.drop_column("career_facts", "verified_at")
    op.drop_column("career_facts", "provenance_type")
    op.drop_column("career_facts", "evidence_tags")
    op.drop_column("career_facts", "lifecycle_status")

    op.drop_index("ix_candidate_profiles_single_active", table_name="candidate_profiles")
    op.drop_column("candidate_profiles", "is_active")
