"""candidate remote geographies

Revision ID: 0007_remote_geographies
Revises: 0006_source_detection_runs
Create Date: 2026-07-13 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0007_remote_geographies"
down_revision = "0006_source_detection_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidate_profiles",
        sa.Column("acceptable_remote_geographies", sa.JSON(), nullable=True),
    )
    op.execute(
        "UPDATE candidate_profiles "
        "SET acceptable_remote_geographies = '[]' "
        "WHERE acceptable_remote_geographies IS NULL"
    )
    op.alter_column("candidate_profiles", "acceptable_remote_geographies", nullable=False)


def downgrade() -> None:
    op.drop_column("candidate_profiles", "acceptable_remote_geographies")
