"""saved search evaluation diagnostics

Revision ID: 0010_search_eval_diagnostics
Revises: 0009_external_job_discovery
Create Date: 2026-08-28 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0010_search_eval_diagnostics"
down_revision = "0009_external_job_discovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "job_evaluations",
        sa.Column("score_components", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "job_search_matches",
        sa.Column(
            "exclusion_reason_codes",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        "job_search_matches",
        sa.Column(
            "decision_explanation",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.alter_column("job_evaluations", "score_components", server_default=None)
    op.alter_column("job_search_matches", "exclusion_reason_codes", server_default=None)
    op.alter_column("job_search_matches", "decision_explanation", server_default=None)


def downgrade() -> None:
    op.drop_column("job_search_matches", "decision_explanation")
    op.drop_column("job_search_matches", "exclusion_reason_codes")
    op.drop_column("job_evaluations", "score_components")
