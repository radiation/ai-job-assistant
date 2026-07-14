# CodeGraph Validation Report

This report records the initial CodeGraph installation, indexing, and representative validation traces for the AI Job Finder repository. It is an AI-development infrastructure artifact only; it does not change application behavior.

## Environment

- CLI: CodeGraph `1.2.0`
- Location: standalone bundle under `~/.codegraph/versions/v1.2.0`, symlinked from `~/.local/bin/codegraph`
- Initialization: `codegraph init .`
- Status command: `codegraph status . --json`
- Baseline result: 81 files, 1578 nodes, 4506 edges, backend `node-sqlite`
- Indexed languages: Python and YAML
- Generated state: `.codegraph/`, ignored by root `.gitignore`

## Validation Method

For each trace, CodeGraph was used to locate likely symbols, callers, callees, and impacted files. Results were then checked against source files, tests, and migrations. A trace is considered accurate only when the graph result matched direct source inspection.

## Trace Results

### 1. Greenhouse Source Detection End to End

Graph approach:

```bash
codegraph query -p . -j create_source_detection_run
codegraph callers -p . -j create_source_detection_run
codegraph query -p . -j approve_source_detection_run
codegraph callers -p . -j approve_source_detection_run
```

Graph summary: CodeGraph located the application service in `application/source_detection.py` and found API, web, CLI, and test callers.

Source verification: Direct reads confirmed detection persists a run before external detection, records terminal states after errors, validates selected tokens, creates or reuses source configurations only through explicit approval, and optionally invokes import through `run_job_source_import` after approval.

Accuracy: Useful for call routing and surface discovery.

Misses and limits: Source reads were required for SSRF controls, linked-script limits, ambiguity behavior, token selection semantics, and transaction timing.

Adjustment: Keep CodeGraph as the first impact tool after focused docs, but require source verification for safety behavior and transaction ownership.

### 2. Greenhouse Import End to End

Graph approach:

```bash
codegraph query -p . -j run_job_source_import
codegraph callers -p . -j run_job_source_import
codegraph callees -p . -j run_job_source_import
codegraph node -p . run_job_source_import --limit 80
```

Graph summary: CodeGraph located the shared import service and API, web, CLI, source-detection, and test callers.

Source verification: Direct reads confirmed a `JobImportRun` is created before connector fetch, postings and evaluations are isolated with nested savepoints, failed items do not abort the whole import, terminal run status is persisted truthfully, and successful non-suspicious imports close missing observations.

Accuracy: Strong for identifying shared entry points and dependent surfaces.

Misses and limits: `callees` over-resolved common method names such as `commit`; SQLAlchemy transaction/savepoint behavior required direct inspection.

Adjustment: Document transaction traces as source-verified, not graph-only.

### 3. Document Upload Through Proposal Acceptance

Graph approach:

```bash
codegraph query -p . -j upload_source_document
codegraph callers -p . -j upload_source_document
codegraph query -p . -j start_extraction_run
codegraph callers -p . -j start_extraction_run
codegraph query -p . -j accept_career_fact_proposal
codegraph callers -p . -j accept_career_fact_proposal
```

Graph summary: CodeGraph identified document service functions and API/web/test callers.

Source verification: Direct reads confirmed upload, text extraction, extraction-run persistence, proposal review, and acceptance. Accepted proposals create `CareerFactModel` records with lifecycle `draft`; AI-generated proposals never become verified canonical facts automatically.

Accuracy: Good for shared service and caller discovery.

Misses and limits: Storage behavior, provider availability, proposal review semantics, and lifecycle defaults required source reads.

Adjustment: Add setup documentation reminding agents that AI output remains untrusted until human review and later lifecycle verification.

### 4. Every Path Creating `CareerFact`

Graph approach:

```bash
codegraph callers -p . -j create_career_fact
codegraph query -p . -j CareerFactModel
codegraph callers -p . -j accept_career_fact_proposal
```

Graph summary: CodeGraph found manual career-fact creation through `application/services.py` and proposal acceptance through `application/documents/proposals.py`.

Source verification: Manual creation uses the application service and deterministic lifecycle rules. Proposal acceptance creates a draft fact and links the proposal to the accepted fact. Merge links a proposal to an existing fact and only performs explicit narrow enrichment.

Accuracy: Good for named function paths.

Misses and limits: Direct model construction paths require source review because graph queries for `CareerFactModel` include model definitions, schemas, tests, and non-creation references.

Adjustment: Preserve guidance to query both service functions and ORM model references, then classify creations manually.

### 5. Every Path Creating `JobEvaluation`

Graph approach:

```bash
codegraph callers -p . -j create_job_evaluation
codegraph query -p . -j JobEvaluationModel
codegraph callers -p . -j _create_evaluation
```

Graph summary: CodeGraph found manual evaluation creation through `application/services.py`, import-triggered immutable evaluations through `application/job_sources/imports.py`, and API/web/test callers.

Source verification: Manual evaluation reuses deterministic scoring. Imports create new immutable evaluations for new or scoring-changed postings. Migration `0003` added `created_at` and removed the unique constraint that previously blocked immutable evaluation history.

Accuracy: Good for service routing and import linkage.

Misses and limits: Whether an import creates a new evaluation depends on checksum comparisons and source state, which required direct source inspection.

Adjustment: Record evaluation-history migration as part of validation because graph links do not explain the persistence semantics.

### 6. Persisted Lifecycles and State Machines

Graph approach:

```bash
codegraph query -p . -j CareerFactLifecycle
codegraph query -p . -j JobImportRunStatus
codegraph query -p . -j SourceDetectionRunStatus
codegraph impact -p . -j SourcePostingStatus
```

Graph summary: CodeGraph found enum definitions and many import sites in domain, application, API/web schemas, infrastructure models, and tests.

Source verification: Direct reads confirmed persisted lifecycle/status values for career facts, source documents, extraction runs, proposals, job import runs, source detections, source posting state, and human posting workflow state.

Accuracy: Good for enum usage discovery.

Misses and limits: Graph output does not distinguish persisted enum semantics from presentation/schema references. Migrations define persisted columns using string table and column names.

Adjustment: Keep `domain-lifecycles.md` and `persistence-and-migrations.md` as required source context before enum changes.

### 7. Services Shared by API and Web

Graph approach:

```bash
codegraph callers -p . -j create_career_fact
codegraph callers -p . -j update_job_lead_status
codegraph callers -p . -j start_extraction_run
codegraph callers -p . -j run_job_source_import
```

Graph summary: CodeGraph found shared application services called by API routes, web routes, CLI commands, and tests.

Source verification: Direct reads confirmed API and web are delivery layers that call application services for career facts, document ingestion, proposal review, source detection, source approval, import sync, job status updates, and evaluation creation.

Accuracy: Strong for avoiding parallel API/web logic.

Misses and limits: FastAPI dependency injection, route decorators, schema serialization, and Jinja template references need direct reads.

Adjustment: Navigation docs now explicitly call out decorator, DI, and template relationships as source-verification areas.

### 8. Transaction and Savepoint Boundaries

Graph approach:

```bash
codegraph query -p . -j run_job_source_import
codegraph query -p . -j _persist_terminal_run_state
codegraph query -p . -j begin_nested
```

Graph summary: CodeGraph routed to the import service and transaction helper functions.

Source verification: Direct reads confirmed run creation, per-posting savepoints, evaluation savepoints, terminal-state persistence, session factory configuration, and API/web dependency ownership.

Accuracy: Useful as a pointer, not as transaction proof.

Misses and limits: SQLAlchemy `Session` methods and common method names are not reliable semantic graph edges.

Adjustment: Transaction boundaries must be validated through source and tests before behavior changes.

### 9. Source-Detection Ambiguity and SSRF Coverage

Graph approach:

```bash
codegraph explore -p . --max-files 10 ambiguous source detection unsafe URL localhost private redirect linked scripts content type oversized provider malformed tests
codegraph callers -p . -j create_source_detection_run
```

Graph summary: CodeGraph found source detection tests, public fetcher tests, Greenhouse connector tests, and integration coverage.

Source verification: Direct reads confirmed tests for ambiguity, explicit selection, unsafe URL terminal runs, existing-source detection, create-and-sync, private/loopback/localhost URL rejection, redirect validation, content-type and byte limits, malformed postings, and provider errors.

Accuracy: Good for surfacing relevant safety tests.

Misses and limits: Broad `explore` output was noisy and sometimes truncated. Parametrized cases and monkeypatch behavior require direct test reads.

Adjustment: Use `explore` for routing only, then inspect targeted tests directly.

### 10. Migration History for Persisted Run Entities

Graph approach:

```bash
codegraph explore -p . --max-files 10 migrations ExtractionRun JobImportRun SourceDetectionRun JobSourceObservation JobSourceConfiguration source_documents job_import_runs
```

Graph summary: CodeGraph surfaced the migration files and ORM model references.

Source verification: Direct reads confirmed `0002` introduced career-fact lifecycle and single active candidate, `0003` enabled immutable evaluation history, `0004` added source documents, extraction runs, and career-fact proposals, `0005` added Greenhouse source configuration/import/observation tables and source posting status, and `0006` added source detection runs.

Accuracy: Useful for finding likely migration files.

Misses and limits: CodeGraph does not semantically connect Alembic string table names to ORM classes or application services.

Adjustment: Migration validation remains a direct Alembic read, with CodeGraph as discovery support only.

## Additional Validation Questions

- Application service callers: CodeGraph found API, web, CLI, and tests for the shared service functions checked above.
- Protocol implementations: Queries for `JobSourceConnector`, `CareerFactExtractor`, `PublicPageFetcher`, and `GreenhouseBoardValidator` found production and fake implementations, but runtime construction still needs direct source verification.
- Posting status impact: `SourcePostingStatus` and `PostingStatus` have separate import and human workflow responsibilities; graph results require domain and persistence context to avoid conflating them.
- CLI entry points: The validated index did not include `pyproject.toml`, so console-script strings require direct `pyproject.toml` inspection.
- Invisible relationships: Route decorators, schema generation, Jinja templates, settings-driven provider selection, and Alembic table-name strings are only partially visible to the graph.

## Configuration Decisions

- Added root `.gitignore` coverage for `.codegraph/` so the local SQLite index is never committed.
- Did not add a committed `codegraph.json`; the zero-config index covered the intended Python, test, migration, YAML, and Docker Compose surfaces.
- Did not add CodeGraph to project dependencies or runtime setup.
- Updated AI-context docs to require source verification for graph-derived findings.
