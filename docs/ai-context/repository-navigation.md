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

Include:

```text
src/ai_job_finder/
tests/
alembic/
```

Optionally include `docs/` for text lookup.

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
