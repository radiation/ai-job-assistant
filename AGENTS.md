# AI Job Finder Agent Guide

This repository is a deterministic, explainable executive job-search platform. Preserve trust, auditability, explicit workflows, and human approval boundaries.

## Required Discovery Order

Before editing code:

1. Read this file.
2. Read `docs/ai-context/README.md`.
3. Open only the focused AI-context documents relevant to the task.
4. Read the applicable ADR under `docs/decisions/` when changing an established boundary.
5. Inspect API schemas or generated OpenAPI information when transport behavior matters.
6. Use CodeGraph to identify symbols, callers, implementations, dependencies, tests, and likely impact.
7. Open the smallest necessary source-file set.
8. Use broad repository search only when the focused documentation and graph are insufficient.

Do not begin implementation until you can state the bounded impact surface.

## Before Implementation

Produce a concise impact analysis containing:

- domain models, enums, and lifecycle rules involved
- application services and transaction boundaries involved
- infrastructure adapters involved
- persistence models and migrations involved
- API, web, and CLI entry points involved
- unit, integration, acceptance, and smoke coverage involved
- existing abstractions to reuse
- expected files to modify
- high-risk files that should not be changed without a demonstrated need
- explicit non-goals

Avoid rediscovering the entire repository during implementation. If the impact surface changes materially, update the analysis before broadening the edit set.

## Architecture Rules

- `domain` contains deterministic rules, lifecycle validation, scoring, enums, and provider-neutral models.
- `application` orchestrates explicit use cases and transaction behavior.
- `infrastructure` contains SQLAlchemy persistence and provider-specific adapters.
- `api` and `web` are delivery layers and must reuse application services.
- CLI entry points are top-level modules under `src/ai_job_finder/` and must reuse the same application services.
- Domain and application code must not import provider SDKs or depend on FastAPI, Jinja, or SQLAlchemy ORM models.
- AI output is untrusted until reviewed. It must never become verified canonical evidence automatically.
- Deterministic logic owns persistence, state transitions, scoring, matching, resume assembly, and application tracking.
- Preserve human approval for source creation, proposal acceptance, outreach, resumes, and applications.

## Change Discipline

- Reuse existing services and protocols before adding abstractions.
- Do not create parallel domain models, duplicate orchestration paths, or transport-specific business logic.
- Keep provider-specific HTTP, parsing, retries, and SDK behavior inside infrastructure adapters.
- Keep lifecycle transitions centralized in domain code.
- Keep imported source state separate from human workflow state.
- Preserve immutable historical evaluations and auditable run history.
- Use migrations for schema changes. Never mutate production schema through SQLAlchemy metadata.
- Treat `infrastructure/database/models.py`, `application/services.py`, `api/v1/routes.py`, and broad integration tests as high-impact files.
- Do not split large files merely for aesthetics during an unrelated slice.

## Testing

Run the narrowest relevant tests first, then the required validation surface.

```bash
uv run ai-job-finder-fast-checks
uv run ai-job-finder-tests --unit
uv run ai-job-finder-tests --integration --require-postgres
uv run ai-job-finder-tests
uv run ai-job-finder-validate
```

Normal tests and hooks must not call live Vertex, Greenhouse, or arbitrary public URLs. Use fakes and bounded fixtures. Live smoke commands remain opt-in.

## Scope Control

Do not add deferred behavior unless the task explicitly requires it. Common deferred areas include:

- autonomous source creation
- broad web discovery
- browser automation
- scheduling and background workers
- application submission
- referrals
- resume generation
- Lever or Ashby support
- fuzzy cross-source merging
- embeddings or vector search
- OCR
- multi-candidate ownership
- agent frameworks

## Completion Requirements

Report:

- implementation summary
- changed files
- architecture and lifecycle implications
- tests run and results
- migration notes, if applicable
- known limitations
- confirmation that unrelated behavior was not changed
