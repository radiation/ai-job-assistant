# CodeGraph Setup and Usage

CodeGraph is the local symbol graph used for repository navigation, impact analysis, and trace validation. It supplements source reads, tests, ADRs, and AI-context documents; it is not a source of truth for behavior.

## Local Prerequisite

The validated local CLI is CodeGraph `1.2.0`:

```bash
codegraph --version
```

On this workstation, `codegraph` is a standalone bundle symlinked from `~/.local/bin/codegraph` into `~/.codegraph/versions/v1.2.0`. The bundle package metadata identifies `@colbymchenry/codegraph` and Node `>=20.0.0 <25.0.0` support.

Do not add CodeGraph to `pyproject.toml`, `uv.lock`, Docker images, hooks, or runtime dependencies. Install or upgrade the CLI outside this project, then verify it is on `PATH` before using it here.

Useful maintenance commands:

```bash
codegraph upgrade --check
codegraph upgrade
codegraph install --help
```

`codegraph install` configures MCP/agent integration. It is optional for this repository and is separate from initializing the repository index.

## Repository Initialization

From the repository root:

```bash
codegraph init .
codegraph status . --json
codegraph files -p . --format flat --no-metadata
```

The validated initial index reported:

- `fileCount`: 81
- `nodeCount`: 1578
- `edgeCount`: 4506
- backend: `node-sqlite`
- indexed languages: Python and YAML

The current baseline indexed `src/ai_job_finder/`, `tests/`, `alembic/`, `.github/*.yml`, `.pre-commit-config.yaml`, and `docker-compose.yml`. Markdown docs, TOML files, Jinja templates, and static assets were not part of the validated index.

## Generated State

CodeGraph writes local generated state under `.codegraph/`, including `codegraph.db`. The directory is ignored by the root `.gitignore` and must not be committed.

Check generated-state handling with:

```bash
git status --ignored --short .codegraph
```

Expected result after initialization is an ignored `.codegraph/` entry.

## Refresh Workflow

For normal work after source changes:

```bash
codegraph sync .
codegraph status . --json
```

For a full rebuild:

```bash
codegraph index .
codegraph status . --json
```

If graph results look stale, run `codegraph sync .` first. If the status still looks wrong, run `codegraph index .` and re-check the file list.

No committed `codegraph.json` is currently required. CodeGraph supports a project `codegraph.json` for extension mappings and include/exclude tuning, but the validated zero-config index covers the intended code, test, migration, and workflow surfaces for this repository. Add config only when a concrete, source-verified indexing gap justifies it.

## Query Recipes

Use symbol-level queries first. They are usually more precise than broad exploration.

```bash
codegraph query -p . -j run_job_source_import
codegraph callers -p . -j run_job_source_import
codegraph callees -p . -j run_job_source_import
codegraph impact -p . -j SourcePostingStatus
codegraph affected -p . src/ai_job_finder/application/job_sources/imports.py
codegraph node -p . run_job_source_import --limit 80
```

Use `explore` for discovery when the exact symbol is not known, then switch back to focused commands:

```bash
codegraph explore -p . --max-files 10 source detection ambiguity unsafe url tests
```

Use the file list to confirm indexing scope:

```bash
codegraph files -p . --format flat --no-metadata
```

## Source Verification Rules

Always verify CodeGraph results against source before editing or documenting behavior. This is especially important for:

- SQLAlchemy transactions, `commit()`, rollback, and savepoints
- Alembic migration table names and string-defined schema relationships
- FastAPI decorators, dependency injection, and OpenAPI behavior
- Jinja template references and HTMX routes
- CLI entry-point strings in `pyproject.toml`
- parametrized tests, fixtures, monkeypatches, and fakes
- protocol implementations and runtime object construction

Known limitations from validation:

- `codegraph affected` returned no affected tests for some application modules even when `callers` found relevant tests.
- `callees` can over-resolve common method names. For example, SQLAlchemy `session.commit()` calls were connected to an unrelated test helper `CommitFailingSession.commit` and needed source review.
- Migration strings such as table names are indexed as code text, not semantic ORM-to-migration edges.
- Broad `explore` output can be noisy or truncated; use it as a routing aid only.
- Markdown and TOML were not indexed in the validated run, so AI-context docs and `pyproject.toml` entry points require direct file reads.

## Agent Workflow

Before implementation, combine the AI-context lookup order with CodeGraph:

1. Read `AGENTS.md` and `docs/ai-context/README.md`.
2. Open the focused AI-context document and relevant ADR.
3. Query CodeGraph for symbols, callers, callees, implementations, likely tests, and impact.
4. Verify the graph result against the smallest relevant source files.
5. Produce the bounded impact analysis before editing.

Use `docs/ai-context/codegraph-validation.md` as examples of representative traces and known misses.
