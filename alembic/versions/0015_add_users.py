"""add local users for external identities

Revision ID: 0015_add_users
Revises: 0014_scheduled_discovery
Create Date: 2026-08-30 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0015_add_users"
down_revision = "0014_scheduled_discovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("identity_provider", sa.String(length=80), nullable=False),
        sa.Column("external_subject", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("identity_provider <> ''", name="ck_users_identity_provider_not_blank"),
        sa.CheckConstraint("external_subject <> ''", name="ck_users_external_subject_not_blank"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint(
            "identity_provider",
            "external_subject",
            name="uq_users_identity_provider_external_subject",
        ),
    )


def downgrade() -> None:
    op.drop_table("users")
