# Repository Navigation and CodeGraph

## Required Lookup Order

1. `AGENTS.md`
2. relevant `docs/ai-context/` file
3. applicable ADR
4. OpenAPI/schema information when relevant
5. CodeGraph
6. smallest relevant source-file set
7. broad text search only as fallback

## CodeGraph Scope

Use CodeGraph as a navigation and impact-analysis aid, then verify graph results against source before editing.

Setup and validation details live in `codegraph.md` and `codegraph-validation.md`.

Include:

```text
src/ai_job_finder/
tests/
alembic/
```

Optionally include `docs/` for text lookup.

Validated baseline indexing currently includes Python source, tests, Alembic migrations, selected YAML workflow/config files, and `docker-compose.yml`. It does not include Markdown docs, `pyproject.toml`, Jinja templates, or static assets.

Exclude:

```text
.git/
.venv/
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
.local/
src/ai_job_assistant.egg-info/
uploaded documents
local document storage
generated artifacts
```

`.codegraph/` is generated local index state and is ignored by the root `.gitignore`.

No committed `codegraph.json` is currently required. Add one only if a source-verified indexing gap requires project-specific extension or exclude tuning.

## Refresh Commands

```bash
codegraph sync .
codegraph status . --json
codegraph files -p . --format flat --no-metadata
```

Use `codegraph index .` for a full rebuild when incremental sync appears stale.

## Query Recipes

- Who calls this service?
- Which API, web, and CLI surfaces share it?
- What implements this protocol?
- What depends on this enum or model?
- Which tests exercise this call path?
- Where is this entity created or updated?
- Which migration introduced it?
- Where are transaction/savepoint boundaries?
- Which paths create `CareerFact` or `JobEvaluation`?
- What changes if this lifecycle or connector method changes?

## Impact Analysis Template

```text
Goal:
Relevant ADRs:
Domain impact:
Application services:
Infrastructure adapters:
Persistence/migrations:
API/web/CLI:
Tests:
Likely files:
High-impact files to avoid:
Non-goals:
Risks:
```

## Initial Validation Queries

1. Trace source detection from API, web, and CLI through persistence.
2. Trace Greenhouse import end to end.
3. Trace document upload through proposal acceptance.
4. Find every path creating a `CareerFact`.
5. Find every path creating a `JobEvaluation`.
6. Identify persisted lifecycles.
7. Identify services shared by API and web.
8. Locate import savepoints and transaction ownership.
9. Find ambiguity and SSRF tests.
10. Find migration history for persisted run entities.

Verify graph results against source and record misses.

Known validation cautions:

- `affected` can miss relevant tests; use `callers` and targeted test reads.
- Common method names such as `commit` may over-resolve to unrelated helpers.
- Alembic string table names are not semantic ORM-to-migration edges.
- Route decorators, dependency injection, Jinja templates, settings, CLI entry-point strings, and parametrized tests need direct source verification.
