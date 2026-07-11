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

## Shared Developer Commands

Local use, hooks, and CI share the same `uv run` command surface:

```bash
uv run ai-job-finder-format
uv run ai-job-finder-fast-checks
uv run ai-job-finder-tests --unit
uv run ai-job-finder-tests --integration --require-postgres
uv run ai-job-finder-tests
uv run ai-job-finder-validate
```

- `ai-job-finder-format` runs Ruff safe fixes and Ruff formatting.
- `ai-job-finder-fast-checks` runs `ruff check .`, `ruff format --check .`, and `mypy .`.
- `ai-job-finder-tests --unit` runs the fast local unit-test layer with no Docker or PostgreSQL dependency.
- `ai-job-finder-tests --integration --require-postgres` runs the PostgreSQL-backed integration layer.
- `ai-job-finder-tests` runs the full suite.
- `ai-job-finder-validate` runs fast checks followed by the full suite.

## Docker Compose Development Stack

Treat Docker Compose as the primary local development environment:

```bash
docker compose up
```

The development stack starts in this order:

1. PostgreSQL becomes healthy.
2. The one-shot `migrate` service runs Alembic once.
3. The FastAPI app starts with Uvicorn reload enabled.

The `src` and `alembic` trees are mounted from the host, so normal Python edits do not require a rebuild. Edit files locally and Uvicorn reloads the app automatically.

When you change dependencies or the Dockerfile itself, rebuild explicitly:

```bash
docker compose up --build
```

Inspect migration failures with:

```bash
docker compose logs migrate
```

Stop the stack and remove volumes when needed:

```bash
docker compose down -v
```

## Hook Usage

Run the full pre-commit stage manually:

```bash
uv run pre-commit run --all-files
```

Run the pre-push stage manually:

```bash
uv run pre-commit run --all-files --hook-stage pre-push
```

Pre-commit runs only whitespace/config cleanup, Ruff safe fixes, Ruff formatting, and mypy. Pre-push runs only the unit-test suite, so local hooks do not depend on Docker or PostgreSQL.

## Running Tests Locally

Run unit tests locally:

```bash
uv run ai-job-finder-tests --unit
```

Run PostgreSQL-backed integration tests manually:

```bash
docker compose down -v
docker compose up -d postgres
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/ai_job_finder_test uv run ai-job-finder-tests --integration --require-postgres
```

The Compose PostgreSQL service provisions both `ai_job_finder` and `ai_job_finder_test` on a fresh volume, so the integration-test command can use a dedicated database.

Run the full suite directly when needed:

```bash
uv run ai-job-finder-tests
```

The repository keeps a clear split by directory:

- `tests/unit` for fast unit tests
- `tests/integration` for real-infrastructure integration tests

## Seed Development Data

Seed development data when needed:

```bash
uv run ai-job-finder-seed
```

## Run The API

Start the API directly from the local environment:

```bash
uv run uvicorn ai_job_finder.main:app --reload
```

The API is served at `http://127.0.0.1:8000/api/v1`.

## Expected Local Workflow

1. Run `docker compose up`.
2. Edit Python files locally.
3. Let the Compose-backed app reload automatically.
4. Let pre-commit run on commit.
5. Push changes and let pre-push run the unit-test suite locally.
6. Let GitHub Actions validate quality, unit tests, and PostgreSQL-backed integration tests.

## Emergency Hook Bypass

If you need to bypass hooks temporarily, use Git's standard `--no-verify` flag for `git commit` or `git push`. CI remains the authoritative validation path.

## Test Notes

- Unit tests run without Docker or PostgreSQL.
- Integration tests are intended to run against PostgreSQL.
- The integration fixture strategy still builds schema from SQLAlchemy metadata; this refinement does not replace the existing architecture with an Alembic-only test harness.

## Documentation

- [Architecture](docs/architecture.md)
- [Domain Model](docs/domain-model.md)
- [Architecture Decision 0001](docs/decisions/0001-foundation-architecture.md)
