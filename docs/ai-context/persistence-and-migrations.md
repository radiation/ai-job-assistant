# Persistence and Migration Map

## ORM

Primary model hub:

- `src/ai_job_finder/infrastructure/database/models.py`

Session/base:

- `infrastructure/database/session.py`
- `infrastructure/database/base.py`

Treat `models.py` as high impact.

## Migration History

- `0001_foundation_slice.py`
- `0002_candidate_knowledge_base_slice.py`
- `0003_evaluation_history_and_created_at.py`
- `0004_document_assisted_fact_ingestion.py`
- `0005_greenhouse_job_discovery.py`
- `0006_source_detection_runs.py`

Schema changes require a new Alembic migration. Do not edit applied migrations unless explicitly required.

## Persistence Invariants

Protect one active candidate, source identity/idempotency, immutable history, observation provenance, run status/overlap, and foreign-key links.

Inspect `tests/integration/test_db_constraints.py` for constraint changes.

## Transaction Safety

Import savepoints isolate posting and evaluation failures. Preserve truthful totals, no unsafe closure, and historical records.

## JSON Fields

Use typed JSON for naturally list-shaped or structured evidence fields, not core lifecycle state or identity.

## Test Schema Note

Integration fixtures currently build schema from SQLAlchemy metadata. Alembic remains the production schema history.
