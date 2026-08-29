"""normalize legacy evidence tag labels

Revision ID: 0012_normalize_evidence_tags
Revises: 0011_proposal_scope_text
Create Date: 2026-08-29 00:00:00.000000

"""

from __future__ import annotations

from alembic import op

revision = "0012_normalize_evidence_tags"
down_revision = "0011_proposal_scope_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _normalize_tags("career_facts", "evidence_tags")
    _normalize_tags("career_fact_proposals", "proposed_evidence_tags")


def downgrade() -> None:
    pass


def _normalize_tags(table_name: str, column_name: str) -> None:
    op.execute(
        f"""
        UPDATE {table_name}
        SET {column_name} = (
            SELECT jsonb_agg(normalized_value ORDER BY first_position)::json
            FROM (
                SELECT
                    CASE value
                        WHEN 'Manager Of Managers' THEN 'manager_of_managers'
                        WHEN 'Ml Platform' THEN 'ml_platform'
                        WHEN 'P And L' THEN 'p_and_l'
                        WHEN 'Ci Cd' THEN 'ci_cd'
                        ELSE value
                    END AS normalized_value,
                    MIN(position) AS first_position
                FROM jsonb_array_elements_text({table_name}.{column_name}::jsonb)
                    WITH ORDINALITY AS tag(value, position)
                GROUP BY 1
            ) AS normalized_tags
        )
        WHERE {column_name}::text LIKE '%Manager Of Managers%'
           OR {column_name}::text LIKE '%Ml Platform%'
           OR {column_name}::text LIKE '%P And L%'
           OR {column_name}::text LIKE '%Ci Cd%'
        """
    )
