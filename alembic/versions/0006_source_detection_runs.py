"""source detection runs

Revision ID: 0006_source_detection_runs
Revises: 0005_greenhouse_discovery
Create Date: 2026-07-12 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0006_source_detection_runs"
down_revision = "0005_greenhouse_discovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_detection_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=True),
        sa.Column("input_url", sa.String(length=500), nullable=True),
        sa.Column("normalized_url", sa.String(length=500), nullable=True),
        sa.Column("final_url", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("detected_provider", sa.String(length=50), nullable=True),
        sa.Column("candidate_tokens", sa.JSON(), nullable=False),
        sa.Column("validated_token", sa.String(length=200), nullable=True),
        sa.Column("validated_company_name", sa.String(length=200), nullable=True),
        sa.Column("validated_job_count", sa.Integer(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_source_configuration_id", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "((status = 'running') AND completed_at IS NULL) OR "
            "((status <> 'running') AND completed_at IS NOT NULL)",
            name="source_detection_runs_completed_at_consistent",
        ),
        sa.ForeignKeyConstraint(
            ["created_source_configuration_id"],
            ["job_source_configurations.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_source_detection_runs_status", "source_detection_runs", ["status"])
    op.create_index("ix_source_detection_runs_started_at", "source_detection_runs", ["started_at"])
    op.create_index(
        "ix_source_detection_runs_created_source_configuration_id",
        "source_detection_runs",
        ["created_source_configuration_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_source_detection_runs_created_source_configuration_id",
        table_name="source_detection_runs",
        if_exists=True,
    )
    op.drop_index(
        "ix_source_detection_runs_started_at",
        table_name="source_detection_runs",
        if_exists=True,
    )
    op.drop_index(
        "ix_source_detection_runs_status",
        table_name="source_detection_runs",
        if_exists=True,
    )
    op.drop_table("source_detection_runs")
