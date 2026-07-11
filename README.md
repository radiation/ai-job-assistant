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
- pre-commit

## Setup

1. Copy `.env.example` to `.env` and adjust the database URLs if needed.
2. Install dependencies from the committed lockfile:

```bash
uv sync --frozen --all-groups
```

3. Install the local Git hooks:

```bash
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
```

4. Start PostgreSQL for local development and PostgreSQL-backed tests:

```bash
docker compose up -d postgres
```

5. Run migrations for local development:

```bash
uv run alembic upgrade head
```

6. Seed development data when needed:

```bash
uv run ai-job-finder-seed
```

## Shared Developer Commands

Local use, hooks, and CI share the same `uv run` command surface:

```bash
uv run ai-job-finder-format
uv run ai-job-finder-fast-checks
uv run ai-job-finder-tests
uv run ai-job-finder-tests --require-postgres
uv run ai-job-finder-validate
```

- `ai-job-finder-format` runs Ruff safe fixes and Ruff formatting.
- `ai-job-finder-fast-checks` runs `ruff check .`, `ruff format --check .`, and `mypy .`.
- `ai-job-finder-tests` runs the full pytest suite.
- `ai-job-finder-tests --require-postgres` requires a reachable PostgreSQL test database and is what the pre-push hook uses.
- `ai-job-finder-validate` runs fast checks followed by the default pytest suite.

## Hook Usage

Run the full pre-commit stage manually:

```bash
uv run pre-commit run --all-files
```

Run the pre-push stage manually:

```bash
uv run pre-commit run --all-files --hook-stage pre-push
```

The pre-push hook expects PostgreSQL to be reachable. Start it first with:

```bash
docker compose up -d postgres
```

If PostgreSQL is unavailable, the hook fails with a clear error instead of silently falling back to SQLite.

## Running Tests Directly

Run the full suite with the repository's current test harness:

```bash
uv run pytest
```

Run the PostgreSQL-backed path explicitly:

```bash
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/ai_job_finder_test uv run ai-job-finder-tests --require-postgres
```

The integration tests continue using the existing fixture strategy that builds schema from SQLAlchemy metadata. This slice does not force the authoritative test suite to build schema exclusively through Alembic.

## Run The API

Start the API directly from the local environment:

```bash
uv run uvicorn ai_job_finder.main:app --reload
```

The API is served at `http://127.0.0.1:8000/api/v1`.

## Docker Compose Stack

Start the full local stack from a clean state:

```bash
docker compose down -v
docker compose up --build
```

Docker Compose starts services in this order:

1. PostgreSQL becomes healthy.
2. The one-shot `migrate` service runs `uv run alembic upgrade head`.
3. The `app` service starts only after the migration service exits successfully.

Inspect migration failures with:

```bash
docker compose logs migrate
```

This startup path is for local Compose only. It does not add production deployment behavior in this slice.

## Emergency Hook Bypass

If you need to bypass hooks temporarily, use Git's standard `--no-verify` flag for `git commit` or `git push`. CI remains the authoritative validation path.

## Test Notes

- Unit tests run without a database server.
- Integration tests use `TEST_DATABASE_URL` when provided.
- If `TEST_DATABASE_URL` is not set, integration tests fall back to SQLite unless PostgreSQL is explicitly required by the command you run.

## Documentation

- [Architecture](docs/architecture.md)
- [Domain Model](docs/domain-model.md)
- [Architecture Decision 0001](docs/decisions/0001-foundation-architecture.md)
