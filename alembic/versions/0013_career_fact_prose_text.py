"""widen career fact prose fields

Revision ID: 0013_career_fact_prose_text
Revises: 0012_normalize_evidence_tags
Create Date: 2026-08-29 00:00:00.000000

Downgrading can fail if values longer than the restored VARCHAR limits have
been persisted. This migration intentionally does not truncate evidence data.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0013_career_fact_prose_text"
down_revision = "0012_normalize_evidence_tags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "career_fact_proposals",
        "proposed_business_outcome",
        existing_type=sa.String(length=500),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        "career_facts",
        "leadership_scope",
        existing_type=sa.String(length=200),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        "career_facts",
        "business_outcome",
        existing_type=sa.String(length=500),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        "career_facts",
        "source_reference",
        existing_type=sa.String(length=500),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "career_facts",
        "source_reference",
        existing_type=sa.Text(),
        type_=sa.String(length=500),
        existing_nullable=False,
    )
    op.alter_column(
        "career_facts",
        "business_outcome",
        existing_type=sa.Text(),
        type_=sa.String(length=500),
        existing_nullable=True,
    )
    op.alter_column(
        "career_facts",
        "leadership_scope",
        existing_type=sa.Text(),
        type_=sa.String(length=200),
        existing_nullable=True,
    )
    op.alter_column(
        "career_fact_proposals",
        "proposed_business_outcome",
        existing_type=sa.Text(),
        type_=sa.String(length=500),
        existing_nullable=True,
    )
