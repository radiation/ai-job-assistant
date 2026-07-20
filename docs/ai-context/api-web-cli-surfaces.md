# API, Web, and CLI Surfaces

## JSON API

- `src/ai_job_finder/api/v1/routes/`
	- `router.py` owns the `/api/v1` prefix and include order.
	- feature route modules own endpoint handlers and local dependencies.
- `src/ai_job_finder/api/v1/schemas.py`
- `src/ai_job_finder/api/dependencies.py`
- `src/ai_job_finder/api/errors.py`

Business rules belong in domain and application services.

Before changing an endpoint, inspect schemas, service callers, matching web/CLI surfaces, integration tests, and OpenAPI behavior.

Saved-search endpoints live beside the existing source and job routes. The current surface includes CRUD, enable/disable, manual run creation, run listing, and run-match detail.

Run responses expose separate counts for considered leads, criteria matches before score checks, evaluations successfully used, threshold passes, exclusions, and failures.

## Server-Rendered Web

- `src/ai_job_finder/web/routes/`
	- `candidate/`, `documents/`, and `job_sources/` are route packages grouped by workflow.
	- `jobs.py` remains the focused jobs route module.
- `src/ai_job_finder/web/templates/`
- `src/ai_job_finder/web/dependencies.py`

Jinja2 plus narrow HTMX fragments; not a SPA. Web routes call application services directly, not internal HTTP.

Saved-search pages live under `/job-searches` and `/job-search-runs`. The discovered-job queue at `/discover` also supports saved-search filtering.

Saved-search web pages distinguish criteria matching, threshold passes, and final saved-search matches in run summaries.

## CLI and Harness Modules

- `bootstrap/`
- `detect_source.py`
- `sync_source.py`
- `greenhouse_smoke.py`
- `source_detection_smoke.py`
- `live_smoke.py`
- `dev.py`
- `calibrate_scoring.py`

Commands are registered in `pyproject.toml`.

CLI behavior should reuse application services, retain deterministic exit codes, and keep smokes opt-in.

The calibration CLI is deterministic, reads only version-controlled fixtures by default, and returns non-zero when expectations fail.

The current default fixture is a synthetic smoke/regression set rather than a representative candidate-specific calibration set.

## Cross-Surface Validation

For a changed use case, query CodeGraph for API, web, CLI, schemas, dependencies, and tests. A cross-surface change is incomplete when only one delivery path changes without an explicit reason.
