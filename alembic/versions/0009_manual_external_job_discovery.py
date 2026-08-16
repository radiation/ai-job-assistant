"""manual external job discovery

Revision ID: 0009_manual_external_job_discovery
Revises: 0008_saved_job_searches
Create Date: 2026-07-20 00:00:01.000000

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0009_manual_external_job_discovery"
down_revision = "0008_saved_job_searches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_discovery_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("search_definition_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generated_query_count", sa.Integer(), nullable=False),
        sa.Column("provider_result_count", sa.Integer(), nullable=False),
        sa.Column("unique_url_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), nullable=False),
        sa.Column("detected_count", sa.Integer(), nullable=False),
        sa.Column("unsupported_count", sa.Integer(), nullable=False),
        sa.Column("ambiguous_count", sa.Integer(), nullable=False),
        sa.Column("imported_lead_count", sa.Integer(), nullable=False),
        sa.Column("evaluated_count", sa.Integer(), nullable=False),
        sa.Column("final_matched_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("saved_search_run_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "generated_query_count >= 0 AND provider_result_count >= 0 AND unique_url_count >= 0 "
            "AND duplicate_count >= 0 AND detected_count >= 0 AND unsupported_count >= 0 "
            "AND ambiguous_count >= 0 AND imported_lead_count >= 0 AND evaluated_count >= 0 "
            "AND final_matched_count >= 0 AND failure_count >= 0",
            name="job_discovery_runs_nonnegative_counters",
        ),
        sa.CheckConstraint(
            "((status = 'running') AND completed_at IS NULL) OR "
            "((status <> 'running') AND completed_at IS NOT NULL)",
            name="job_discovery_runs_completed_at_consistent",
        ),
        sa.ForeignKeyConstraint(
            ["saved_search_run_id"],
            ["job_search_runs.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["search_definition_id"],
            ["job_search_definitions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_job_discovery_runs_search_definition_id",
        "job_discovery_runs",
        ["search_definition_id"],
    )
    op.create_index(
        "ix_job_discovery_runs_single_running_per_definition",
        "job_discovery_runs",
        ["search_definition_id"],
        unique=True,
        sqlite_where=sa.text("status = 'running'"),
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index("ix_job_discovery_runs_status", "job_discovery_runs", ["status"])
    op.create_index("ix_job_discovery_runs_started_at", "job_discovery_runs", ["started_at"])

    op.create_table(
        "job_discovery_queries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("discovery_run_id", sa.Uuid(), nullable=False),
        sa.Column("stable_query_id", sa.String(length=64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("query_text", sa.String(length=300), nullable=False),
        sa.Column("title_phrase", sa.String(length=200), nullable=False),
        sa.Column("target_domain", sa.String(length=200), nullable=True),
        sa.Column("location_or_workplace_term", sa.String(length=200), nullable=True),
        sa.Column("requested_result_limit", sa.Integer(), nullable=False),
        sa.Column("returned_result_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "ordinal > 0 AND requested_result_limit > 0 AND returned_result_count >= 0",
            name="job_discovery_queries_positive_counts",
        ),
        sa.ForeignKeyConstraint(
            ["discovery_run_id"],
            ["job_discovery_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_job_discovery_queries_run_id",
        "job_discovery_queries",
        ["discovery_run_id"],
    )
    op.create_index("ix_job_discovery_queries_status", "job_discovery_queries", ["status"])
    op.create_index(
        "ix_job_discovery_queries_stable_query_id",
        "job_discovery_queries",
        ["stable_query_id"],
    )
    op.create_index(
        "ix_job_discovery_queries_unique_ordinal_per_run",
        "job_discovery_queries",
        ["discovery_run_id", "ordinal"],
        unique=True,
    )

    op.create_table(
        "job_discovery_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("discovery_run_id", sa.Uuid(), nullable=False),
        sa.Column("primary_query_id", sa.Uuid(), nullable=False),
        sa.Column("query_ordinals", sa.JSON(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("provider_result_id", sa.String(length=200), nullable=True),
        sa.Column("discovered_url", sa.String(length=500), nullable=False),
        sa.Column("normalized_url", sa.String(length=500), nullable=False),
        sa.Column("title_hint", sa.String(length=200), nullable=True),
        sa.Column("company_hint", sa.String(length=200), nullable=True),
        sa.Column("location_hint", sa.String(length=200), nullable=True),
        sa.Column("evidence_snippet", sa.String(length=1000), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("source_detection_outcome", sa.String(length=30), nullable=True),
        sa.Column("source_detection_run_id", sa.Uuid(), nullable=True),
        sa.Column("source_configuration_id", sa.Uuid(), nullable=True),
        sa.Column("import_run_id", sa.Uuid(), nullable=True),
        sa.Column("imported_job_lead_id", sa.Uuid(), nullable=True),
        sa.Column("processing_status", sa.String(length=30), nullable=False),
        sa.Column("exclusion_reason", sa.Text(), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("rank >= 0", name="job_discovery_observations_rank_nonnegative"),
        sa.ForeignKeyConstraint(
            ["discovery_run_id"],
            ["job_discovery_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["import_run_id"],
            ["job_import_runs.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["imported_job_lead_id"],
            ["job_leads.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["primary_query_id"],
            ["job_discovery_queries.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_configuration_id"],
            ["job_source_configurations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_detection_run_id"],
            ["source_detection_runs.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_job_discovery_observations_run_id",
        "job_discovery_observations",
        ["discovery_run_id"],
    )
    op.create_index(
        "ix_job_discovery_observations_status",
        "job_discovery_observations",
        ["processing_status"],
    )
    op.create_index(
        "ix_job_discovery_observations_source_detection_run_id",
        "job_discovery_observations",
        ["source_detection_run_id"],
    )
    op.create_index(
        "ix_job_discovery_observations_unique_url_per_run",
        "job_discovery_observations",
        ["discovery_run_id", "normalized_url"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_job_discovery_observations_unique_url_per_run",
        table_name="job_discovery_observations",
        if_exists=True,
    )
    op.drop_index(
        "ix_job_discovery_observations_source_detection_run_id",
        table_name="job_discovery_observations",
        if_exists=True,
    )
    op.drop_index(
        "ix_job_discovery_observations_status",
        table_name="job_discovery_observations",
        if_exists=True,
    )
    op.drop_index(
        "ix_job_discovery_observations_run_id",
        table_name="job_discovery_observations",
        if_exists=True,
    )
    op.drop_table("job_discovery_observations")

    op.drop_index(
        "ix_job_discovery_queries_unique_ordinal_per_run",
        table_name="job_discovery_queries",
        if_exists=True,
    )
    op.drop_index(
        "ix_job_discovery_queries_stable_query_id",
        table_name="job_discovery_queries",
        if_exists=True,
    )
    op.drop_index(
        "ix_job_discovery_queries_status",
        table_name="job_discovery_queries",
        if_exists=True,
    )
    op.drop_index(
        "ix_job_discovery_queries_run_id",
        table_name="job_discovery_queries",
        if_exists=True,
    )
    op.drop_table("job_discovery_queries")

    op.drop_index(
        "ix_job_discovery_runs_started_at",
        table_name="job_discovery_runs",
        if_exists=True,
    )
    op.drop_index(
        "ix_job_discovery_runs_status",
        table_name="job_discovery_runs",
        if_exists=True,
    )
    op.drop_index(
        "ix_job_discovery_runs_single_running_per_definition",
        table_name="job_discovery_runs",
        if_exists=True,
    )
    op.drop_index(
        "ix_job_discovery_runs_search_definition_id",
        table_name="job_discovery_runs",
        if_exists=True,
    )
    op.drop_table("job_discovery_runs")
