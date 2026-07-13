# Testing and Acceptance Map

## Unit Tests

Location: `tests/unit/`.

Unit tests must not require PostgreSQL, Docker, Vertex, Greenhouse, or public URLs.

## Integration Tests

Location: `tests/integration/`.

Important files:

- `test_api.py`
- `test_document_api.py`
- `test_source_detection.py`
- `test_web.py`
- `test_db_constraints.py`

Use integration coverage for persistence, routes, schemas, cross-surface workflows, and constraints.

## Acceptance Harness

```bash
uv run ai-job-finder-bootstrap
```

Optional fake-backed phases cover document ingestion and Greenhouse detection/import. The harness uses public HTTP contracts, not direct database seeding.

## Live Smokes

Opt-in only:

- Greenhouse fetch-only
- source-detection read-only
- Vertex

Normal hooks and CI must not invoke them.

## Test Order

1. focused unit file
2. focused integration file
3. `uv run ai-job-finder-fast-checks`
4. unit suite
5. PostgreSQL integration suite when applicable
6. full validation for broad changes

Lifecycle changes should cover allowed/rejected transitions, timestamps, constraints, error mapping, and web controls.

Import/detection changes should cover success, failures, partial behavior, idempotency, overlap/ambiguity, terminal status, and safety boundaries.
