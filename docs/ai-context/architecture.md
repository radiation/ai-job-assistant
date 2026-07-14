# Architecture Map

## Shape

```text
src/ai_job_finder/
  domain/
  application/
  infrastructure/
  api/
  web/
  top-level CLI and smoke modules
```

Dependency direction:

```text
api / web / CLI
        |
        v
   application
        |
        v
      domain

infrastructure implements boundaries used by application code
```

## Layer Responsibilities

### Domain

Location: `src/ai_job_finder/domain/`

Owns enums, lifecycle rules, deterministic scoring, provider-neutral snapshots and value objects, workflow validation, and domain errors.

Must not depend on FastAPI, Jinja, SQLAlchemy ORM models, Vertex SDKs, or provider HTTP clients.

### Application

Location: `src/ai_job_finder/application/`

Owns explicit use cases, orchestration, transaction behavior, run lifecycle handling, and reuse across API, web, and CLI.

Important modules:

- `services.py`
- `document_services.py`
- `extraction.py`
- `job_imports.py`
- `source_detection.py`

### Infrastructure

Location: `src/ai_job_finder/infrastructure/`

Owns SQLAlchemy persistence, Greenhouse and fake connectors, Vertex and fake extractors, local storage, text extraction, and SSRF-safe public fetching.

Provider-specific SDKs, HTTP policy, parsing, retries, and normalization stay here.

### Delivery

- JSON API: `src/ai_job_finder/api/`
- Web: `src/ai_job_finder/web/`
- CLI/smokes: top-level modules under `src/ai_job_finder/`

The API v1 router is an explicit package under `api/v1/routes/`; `router.py` owns the `/api/v1` prefix and each feature module owns its handlers. Broad web workflows use route packages under `web/routes/` while focused route modules can remain single files.

Delivery code must call application services rather than reproduce business logic.

## Architectural Priorities

- explainability over opaque automation
- deterministic policy before LLM judgment
- verified canonical facts over resume-derived text
- explicit human approval at reputation-sensitive boundaries
- auditable history over destructive updates
- provider-neutral boundaries without premature frameworks
- one use-case path shared by API, web, and CLI

## High-Impact Files

- `application/services.py`
- `infrastructure/database/models/`
- `api/v1/routes/`
- `api/v1/schemas.py`
- `tests/integration/api/`
- `tests/integration/web/`

Use CodeGraph before changing them. Do not refactor them opportunistically.
