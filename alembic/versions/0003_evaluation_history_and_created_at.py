"""allow immutable evaluation history

Revision ID: 0003_evaluation_history
Revises: 0002_candidate_kb
Create Date: 2026-07-11 00:00:01.000000

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003_evaluation_history"
down_revision = "0002_candidate_kb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "job_evaluations",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.execute("UPDATE job_evaluations SET created_at = evaluated_at WHERE created_at IS NULL")
    op.alter_column("job_evaluations", "created_at", nullable=False)
    op.drop_constraint(
        op.f("uq_job_evaluations_candidate_job_version"),
        "job_evaluations",
        type_="unique",
    )


def downgrade() -> None:
    op.create_unique_constraint(
        op.f("uq_job_evaluations_candidate_job_version"),
        "job_evaluations",
        ["candidate_profile_id", "job_lead_id", "scoring_version"],
    )
    op.drop_column("job_evaluations", "created_at")
