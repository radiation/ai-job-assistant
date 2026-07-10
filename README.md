# AI Job Finder

Foundation slice for a deterministic, explainable executive job-search platform.

## Stack

- Python 3.14
- uv
- FastAPI
- Pydantic v2
- SQLAlchemy 2.x
- Alembic
- PostgreSQL
- pytest
- mypy --strict
- ruff

## Setup

1. Copy `.env.example` to `.env` and adjust the database URLs.
2. Start PostgreSQL:

```bash
docker compose up -d postgres
```

3. Install dependencies:

```bash
uv sync --all-groups
```

4. Run migrations:

```bash
uv run alembic upgrade head
```

5. Seed development data:

```bash
uv run ai-job-finder-seed
```

## Run The API

```bash
uv run uvicorn ai_job_finder.main:app --reload
```

The API is served at `http://127.0.0.1:8000/api/v1`.

## Quality Command

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest
```

## Test Notes

- Unit tests run without a database server.
- Integration tests default to `TEST_DATABASE_URL` when provided.
- If `TEST_DATABASE_URL` is not set, integration tests fall back to SQLite and separate PostgreSQL-only invariants are still covered by the migration and runtime validation path.

## Documentation

- [Architecture](docs/architecture.md)
- [Domain Model](docs/domain-model.md)
- [Architecture Decision 0001](docs/decisions/0001-foundation-architecture.md)