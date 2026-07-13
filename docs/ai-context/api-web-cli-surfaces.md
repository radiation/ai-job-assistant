# API, Web, and CLI Surfaces

## JSON API

- `src/ai_job_finder/api/v1/routes.py`
- `src/ai_job_finder/api/v1/schemas.py`
- `src/ai_job_finder/api/dependencies.py`
- `src/ai_job_finder/api/errors.py`

Business rules belong in domain and application services.

Before changing an endpoint, inspect schemas, service callers, matching web/CLI surfaces, integration tests, and OpenAPI behavior.

## Server-Rendered Web

- `src/ai_job_finder/web/routes/`
- `src/ai_job_finder/web/templates/`
- `src/ai_job_finder/web/dependencies.py`

Jinja2 plus narrow HTMX fragments; not a SPA. Web routes call application services directly, not internal HTTP.

## CLI and Harness Modules

- `bootstrap.py`
- `detect_source.py`
- `sync_source.py`
- `greenhouse_smoke.py`
- `source_detection_smoke.py`
- `live_smoke.py`
- `dev.py`

Commands are registered in `pyproject.toml`.

CLI behavior should reuse application services, retain deterministic exit codes, and keep smokes opt-in.

## Cross-Surface Validation

For a changed use case, query CodeGraph for API, web, CLI, schemas, dependencies, and tests. A cross-surface change is incomplete when only one delivery path changes without an explicit reason.
