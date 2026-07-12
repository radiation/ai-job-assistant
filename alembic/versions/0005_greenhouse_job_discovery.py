"""greenhouse job discovery ingestion

Revision ID: 0005_greenhouse_discovery
Revises: 0004_document_ingestion
Create Date: 2026-07-12 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0005_greenhouse_discovery"
down_revision = "0004_document_ingestion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "job_leads",
        sa.Column(
            "source_posting_status",
            sa.String(length=20),
            nullable=False,
            server_default="open",
        ),
    )
    op.create_table(
        "job_source_configurations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=False),
        sa.Column("board_token", sa.String(length=200), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_successful_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.String(length=30), nullable=True),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "board_token", name="uq_job_source_provider_board_token"),
    )
    op.create_index(
        "ix_job_source_configurations_enabled", "job_source_configurations", ["enabled"]
    )
    op.create_index(
        "ix_job_source_configurations_provider", "job_source_configurations", ["provider"]
    )

    op.create_table(
        "job_import_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_configuration_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("jobs_fetched", sa.Integer(), nullable=False),
        sa.Column("jobs_created", sa.Integer(), nullable=False),
        sa.Column("jobs_updated", sa.Integer(), nullable=False),
        sa.Column("jobs_unchanged", sa.Integer(), nullable=False),
        sa.Column("jobs_closed", sa.Integer(), nullable=False),
        sa.Column("jobs_failed", sa.Integer(), nullable=False),
        sa.Column("evaluations_created", sa.Integer(), nullable=False),
        sa.Column("evaluation_failures", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("connector_version", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "jobs_fetched >= 0 AND jobs_created >= 0 AND jobs_updated >= 0 "
            "AND jobs_unchanged >= 0 AND jobs_closed >= 0 AND jobs_failed >= 0 "
            "AND evaluations_created >= 0 AND evaluation_failures >= 0",
            name="job_import_runs_nonnegative_counters",
        ),
        sa.CheckConstraint(
            "((status = 'running') AND completed_at IS NULL) OR "
            "((status <> 'running') AND completed_at IS NOT NULL)",
            name="job_import_runs_completed_at_consistent",
        ),
        sa.ForeignKeyConstraint(
            ["source_configuration_id"], ["job_source_configurations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_job_import_runs_source_configuration_id",
        "job_import_runs",
        ["source_configuration_id"],
    )
    op.create_index(
        "ix_job_import_runs_single_running_per_source",
        "job_import_runs",
        ["source_configuration_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
        sqlite_where=sa.text("status = 'running'"),
    )
    op.create_index("ix_job_import_runs_status", "job_import_runs", ["status"])
    op.create_index("ix_job_import_runs_started_at", "job_import_runs", ["started_at"])

    op.create_table(
        "job_source_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_configuration_id", sa.Uuid(), nullable=False),
        sa.Column("job_lead_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("external_post_id", sa.String(length=200), nullable=False),
        sa.Column("external_internal_job_id", sa.String(length=200), nullable=True),
        sa.Column("canonical_url", sa.String(length=500), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_checksum", sa.String(length=64), nullable=False),
        sa.Column("scoring_checksum", sa.String(length=64), nullable=False),
        sa.Column("duplicate_hint_key", sa.String(length=64), nullable=False),
        sa.Column("normalized_payload", sa.JSON(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "((active IS TRUE) AND removed_at IS NULL) OR "
            "((active IS FALSE) AND removed_at IS NOT NULL)",
            name="job_source_observations_active_removed_consistent",
        ),
        sa.ForeignKeyConstraint(["job_lead_id"], ["job_leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_configuration_id"], ["job_source_configurations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_configuration_id",
            "provider",
            "external_post_id",
            name="uq_job_source_observation_identity",
        ),
    )
    op.create_index(
        "ix_job_source_observations_source_configuration_id",
        "job_source_observations",
        ["source_configuration_id"],
    )
    op.create_index(
        "ix_job_source_observations_source_configuration_active",
        "job_source_observations",
        ["source_configuration_id", "active"],
    )
    op.create_index(
        "ix_job_source_observations_job_lead_id",
        "job_source_observations",
        ["job_lead_id"],
    )
    op.create_index("ix_job_source_observations_active", "job_source_observations", ["active"])
    op.create_index(
        "ix_job_source_observations_external_internal_job_id",
        "job_source_observations",
        ["external_internal_job_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_job_source_observations_external_internal_job_id",
        table_name="job_source_observations",
        if_exists=True,
    )
    op.drop_index(
        "ix_job_source_observations_active",
        table_name="job_source_observations",
        if_exists=True,
    )
    op.drop_index(
        "ix_job_source_observations_job_lead_id",
        table_name="job_source_observations",
        if_exists=True,
    )
    op.drop_index(
        "ix_job_source_observations_source_configuration_active",
        table_name="job_source_observations",
        if_exists=True,
    )
    op.drop_index(
        "ix_job_source_observations_source_configuration_id",
        table_name="job_source_observations",
        if_exists=True,
    )
    op.drop_table("job_source_observations")
    op.drop_index("ix_job_import_runs_started_at", table_name="job_import_runs", if_exists=True)
    op.drop_index("ix_job_import_runs_status", table_name="job_import_runs", if_exists=True)
    op.drop_index(
        "ix_job_import_runs_single_running_per_source",
        table_name="job_import_runs",
        if_exists=True,
    )
    op.drop_index(
        "ix_job_import_runs_source_configuration_id",
        table_name="job_import_runs",
        if_exists=True,
    )
    op.drop_table("job_import_runs")
    op.drop_index("ix_job_source_configurations_provider", table_name="job_source_configurations")
    op.drop_index("ix_job_source_configurations_enabled", table_name="job_source_configurations")
    op.drop_table("job_source_configurations")
    op.drop_column("job_leads", "source_posting_status")
