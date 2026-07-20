"""saved job searches

Revision ID: 0008_saved_job_searches
Revises: 0007_remote_geographies
Create Date: 2026-07-20 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0008_saved_job_searches"
down_revision = "0007_remote_geographies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_search_definitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("title_include_patterns", sa.JSON(), nullable=False),
        sa.Column("title_exclude_patterns", sa.JSON(), nullable=False),
        sa.Column("target_domains", sa.JSON(), nullable=False),
        sa.Column("target_seniority_levels", sa.JSON(), nullable=False),
        sa.Column("allowed_locations", sa.JSON(), nullable=False),
        sa.Column("allowed_remote_geographies", sa.JSON(), nullable=False),
        sa.Column("allowed_workplace_types", sa.JSON(), nullable=False),
        sa.Column("minimum_score_threshold", sa.Float(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(name)) > 0",
            name="job_search_definitions_name_not_blank",
        ),
        sa.CheckConstraint(
            "minimum_score_threshold >= 0 AND minimum_score_threshold <= 100",
            name="job_search_definitions_threshold_range",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_job_search_definitions_name"),
    )
    op.create_index("ix_job_search_definitions_enabled", "job_search_definitions", ["enabled"])
    op.create_index(
        "ix_job_search_definitions_last_run_at",
        "job_search_definitions",
        ["last_run_at"],
    )

    op.create_table(
        "job_search_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("search_definition_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("candidates_considered", sa.Integer(), nullable=False),
        sa.Column("matched_by_criteria", sa.Integer(), nullable=False),
        sa.Column("evaluated_count", sa.Integer(), nullable=False),
        sa.Column("above_threshold_count", sa.Integer(), nullable=False),
        sa.Column("excluded_count", sa.Integer(), nullable=False),
        sa.Column("failures_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "candidates_considered >= 0 AND matched_by_criteria >= 0 AND evaluated_count >= 0 "
            "AND above_threshold_count >= 0 AND excluded_count >= 0 AND failures_count >= 0",
            name="job_search_runs_nonnegative_counters",
        ),
        sa.CheckConstraint(
            "((status = 'running') AND completed_at IS NULL) OR "
            "((status <> 'running') AND completed_at IS NOT NULL)",
            name="job_search_runs_completed_at_consistent",
        ),
        sa.ForeignKeyConstraint(
            ["search_definition_id"],
            ["job_search_definitions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_job_search_runs_search_definition_id",
        "job_search_runs",
        ["search_definition_id"],
    )
    op.create_index(
        "ix_job_search_runs_single_running_per_definition",
        "job_search_runs",
        ["search_definition_id"],
        unique=True,
        sqlite_where=sa.text("status = 'running'"),
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index("ix_job_search_runs_status", "job_search_runs", ["status"])
    op.create_index("ix_job_search_runs_started_at", "job_search_runs", ["started_at"])

    op.create_table(
        "job_search_matches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("search_definition_id", sa.Uuid(), nullable=False),
        sa.Column("search_run_id", sa.Uuid(), nullable=False),
        sa.Column("job_lead_id", sa.Uuid(), nullable=False),
        sa.Column("job_evaluation_id", sa.Uuid(), nullable=True),
        sa.Column("scoring_version", sa.String(length=50), nullable=True),
        sa.Column("score_at_match_time", sa.Float(), nullable=True),
        sa.Column("recommendation_at_match_time", sa.String(length=30), nullable=True),
        sa.Column("criteria_matched", sa.Boolean(), nullable=False),
        sa.Column("above_threshold", sa.Boolean(), nullable=False),
        sa.Column("matched", sa.Boolean(), nullable=False),
        sa.Column("matched_criteria", sa.JSON(), nullable=False),
        sa.Column("exclusion_reasons", sa.JSON(), nullable=False),
        sa.Column("inferred_domains", sa.JSON(), nullable=False),
        sa.Column("inferred_seniority_levels", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_evaluation_id"],
            ["job_evaluations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["job_lead_id"],
            ["job_leads.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["search_definition_id"],
            ["job_search_definitions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["search_run_id"],
            ["job_search_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "search_run_id",
            "job_lead_id",
            name="uq_job_search_matches_search_run_job_lead",
        ),
    )
    op.create_index(
        "ix_job_search_matches_search_definition_id",
        "job_search_matches",
        ["search_definition_id"],
    )
    op.create_index("ix_job_search_matches_search_run_id", "job_search_matches", ["search_run_id"])
    op.create_index("ix_job_search_matches_job_lead_id", "job_search_matches", ["job_lead_id"])
    op.create_index("ix_job_search_matches_matched", "job_search_matches", ["matched"])


def downgrade() -> None:
    op.drop_index("ix_job_search_matches_matched", table_name="job_search_matches", if_exists=True)
    op.drop_index(
        "ix_job_search_matches_job_lead_id",
        table_name="job_search_matches",
        if_exists=True,
    )
    op.drop_index(
        "ix_job_search_matches_search_run_id",
        table_name="job_search_matches",
        if_exists=True,
    )
    op.drop_index(
        "ix_job_search_matches_search_definition_id",
        table_name="job_search_matches",
        if_exists=True,
    )
    op.drop_table("job_search_matches")

    op.drop_index("ix_job_search_runs_started_at", table_name="job_search_runs", if_exists=True)
    op.drop_index("ix_job_search_runs_status", table_name="job_search_runs", if_exists=True)
    op.drop_index(
        "ix_job_search_runs_single_running_per_definition",
        table_name="job_search_runs",
        if_exists=True,
    )
    op.drop_index(
        "ix_job_search_runs_search_definition_id",
        table_name="job_search_runs",
        if_exists=True,
    )
    op.drop_table("job_search_runs")

    op.drop_index(
        "ix_job_search_definitions_last_run_at",
        table_name="job_search_definitions",
        if_exists=True,
    )
    op.drop_index(
        "ix_job_search_definitions_enabled",
        table_name="job_search_definitions",
        if_exists=True,
    )
    op.drop_table("job_search_definitions")
