"""allow full extracted proposal leadership scope

Revision ID: 0011_proposal_scope_text
Revises: 0010_search_eval_diagnostics
Create Date: 2026-08-29 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0011_proposal_scope_text"
down_revision = "0010_search_eval_diagnostics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "career_fact_proposals",
        "proposed_leadership_scope",
        existing_type=sa.String(length=200),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "career_fact_proposals",
        "proposed_leadership_scope",
        existing_type=sa.Text(),
        type_=sa.String(length=200),
        existing_nullable=True,
    )
