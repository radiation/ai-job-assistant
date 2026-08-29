"""add scheduled saved-search discovery and actionable notification state

Revision ID: 0014_scheduled_discovery
Revises: 0013_career_fact_prose
Create Date: 2026-08-29 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0014_scheduled_discovery"
down_revision = "0013_career_fact_prose_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "job_search_definitions",
        sa.Column(
            "scheduled_discovery_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "job_search_definitions",
        sa.Column(
            "scheduled_discovery_cadence",
            sa.String(length=30),
            nullable=False,
            server_default="daily",
        ),
    )
    op.add_column(
        "job_search_definitions",
        sa.Column("next_scheduled_discovery_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "job_search_definitions",
        sa.Column(
            "last_scheduled_discovery_attempted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "job_search_definitions",
        sa.Column(
            "last_scheduled_discovery_completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_job_search_definitions_scheduled_discovery_due",
        "job_search_definitions",
        ["scheduled_discovery_enabled", "next_scheduled_discovery_at"],
    )
    op.create_table(
        "job_search_actionable_notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("search_definition_id", sa.Uuid(), nullable=False),
        sa.Column("job_lead_id", sa.Uuid(), nullable=False),
        sa.Column("job_search_match_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=30), nullable=False),
        sa.Column("delivery_status", sa.String(length=30), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "delivery_status IN ('pending', 'succeeded', 'failed')",
            name="job_search_actionable_notifications_delivery_status_valid",
        ),
        sa.ForeignKeyConstraint(["job_lead_id"], ["job_leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["job_search_match_id"], ["job_search_matches.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["search_definition_id"], ["job_search_definitions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "search_definition_id",
            "job_lead_id",
            name="uq_job_search_actionable_notifications_search_job_lead",
        ),
    )
    op.create_index(
        "ix_job_search_actionable_notifications_delivery_status",
        "job_search_actionable_notifications",
        ["delivery_status"],
    )
    op.alter_column("job_search_definitions", "scheduled_discovery_enabled", server_default=None)
    op.alter_column("job_search_definitions", "scheduled_discovery_cadence", server_default=None)


def downgrade() -> None:
    op.drop_index(
        "ix_job_search_actionable_notifications_delivery_status",
        table_name="job_search_actionable_notifications",
    )
    op.drop_table("job_search_actionable_notifications")
    op.drop_index(
        "ix_job_search_definitions_scheduled_discovery_due",
        table_name="job_search_definitions",
    )
    op.drop_column("job_search_definitions", "last_scheduled_discovery_completed_at")
    op.drop_column("job_search_definitions", "last_scheduled_discovery_attempted_at")
    op.drop_column("job_search_definitions", "next_scheduled_discovery_at")
    op.drop_column("job_search_definitions", "scheduled_discovery_cadence")
    op.drop_column("job_search_definitions", "scheduled_discovery_enabled")
