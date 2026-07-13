# AI Job Finder

Foundation slice for a deterministic, explainable executive job-search platform.

The current product slice centers on a single reviewed candidate profile, a canonical career-fact knowledge base, document-assisted career-fact ingestion, and Greenhouse public job-board discovery. Imported jobs are normalized, evaluated deterministically, and presented in a ranked review queue.

## Stack

- Python 3.14
- uv
- FastAPI
- Jinja2
- HTMX via pinned CDN (`https://unpkg.com/htmx.org@1.9.12`)
- Pydantic v2
- SQLAlchemy 2.x
- Alembic
- PostgreSQL
- pypdf for embedded PDF text extraction
- Vertex AI Gemini direct model inference through Google Application Default Credentials
- pytest
- mypy --strict
- ruff
- pre-commit

## AI Development Context

Agent instructions live in `AGENTS.md`. Focused repository maps for AI-assisted development start at `docs/ai-context/README.md`. CodeGraph setup and validation notes live under `docs/ai-context/codegraph.md`.

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
uv run ai-job-finder-bootstrap --base-url http://localhost:8000 --reset --allow-destructive
uv run ai-job-finder-bootstrap --base-url http://localhost:8000 --document-ingestion
uv run ai-job-finder-bootstrap --base-url http://localhost:8000 --fake-greenhouse
uv run ai-job-finder-sync-source --source-id <uuid>
uv run ai-job-finder-greenhouse-smoke
uv run ai-job-finder-vertex-smoke
uv run ai-job-finder-tests --unit
uv run ai-job-finder-tests --integration --require-postgres
uv run ai-job-finder-tests
uv run ai-job-finder-validate
```

- `ai-job-finder-format` runs Ruff safe fixes and Ruff formatting.
- `ai-job-finder-fast-checks` runs `ruff check .`, `ruff format --check .`, and `mypy .`.
- `ai-job-finder-bootstrap` exercises the candidate knowledge-base slice end-to-end through the public HTTP API and prints a concise acceptance summary.
- `ai-job-finder-bootstrap --document-ingestion` optionally exercises upload, extraction, proposal acceptance, rejection, and duplicate upload handling. Configure the running app with `EXTRACTION_ENABLED=true` and `EXTRACTION_PROVIDER=fake` for this local fake-extractor phase.
- `ai-job-finder-bootstrap --fake-greenhouse` optionally exercises fake Greenhouse source detection, approval, existing-source detection, ambiguity, unsafe URL rejection, create-and-sync, source creation, idempotent import, update, closure, failed import safety, reactivation, and ranked discovery. Start the app with `GREENHOUSE_FAKE_FIXTURE_PATH=/tmp/ai-job-finder-fake-greenhouse.json` and pass the same path through `--fake-greenhouse-fixture-path` if it differs from the environment.
- `ai-job-finder-sync-source --source-id <uuid>` runs the same source import service used by the web and API sync action.
- `ai-job-finder-greenhouse-smoke` is skipped unless `AI_JOB_FINDER_RUN_GREENHOUSE_SMOKE=true`; when enabled it performs one fetch-only call to a configured public Greenhouse board token and does not persist jobs.
- `ai-job-finder-vertex-smoke` is skipped unless `AI_JOB_FINDER_RUN_VERTEX_SMOKE=true`; when enabled it makes one live Vertex call against a small fixture and prints model, prompt version, token usage, and proposal count.
- `ai-job-finder-tests --unit` runs the fast local unit-test layer with no Docker or PostgreSQL dependency.
- `ai-job-finder-tests --integration --require-postgres` runs the PostgreSQL-backed integration layer.
- `ai-job-finder-tests` runs the full suite.
- `ai-job-finder-validate` runs fast checks followed by the full suite.

## Web Console

The API and the thin server-rendered console run in the same FastAPI process. There is no separate frontend build, Node toolchain, or client-side state container.

- Browser URL: `http://127.0.0.1:8000/jobs`
- API docs: `http://127.0.0.1:8000/docs`
- JSON API base: `http://127.0.0.1:8000/api/v1`

Primary HTML routes:

- `/jobs`
- `/jobs/new`
- `/jobs/{job_id}`
- `/candidate`
- `/candidate/edit`
- `/career-facts`
- `/career-facts/new`
- `/career-facts/{fact_id}`
- `/career-facts/{fact_id}/edit`
- `/documents`
- `/documents/new`
- `/documents/{document_id}`
- `/fact-proposals`
- `/fact-proposals/{proposal_id}`
- `/job-sources`
- `/job-sources/new`
- `/job-sources/{source_id}`
- `/job-import-runs/{run_id}`
- `/discover`

The main manual workflow is:

1. Open `/candidate` and complete the first-run candidate setup if no active candidate exists.
2. Record career facts under `/career-facts` and verify the reviewed facts that should influence evaluation.
3. Open `/jobs/new`.
4. Enter a job lead manually.
5. Submit the form and land on the job detail page.
6. Update posting status inline.
7. Trigger an evaluation inline once verified career facts exist.

HTMX is used only for job status updates, evaluation refresh on the detail page, and career-fact lifecycle actions. Normal navigation and form submission still render correctly without HTMX.

## Greenhouse Job Discovery

This slice supports only deterministic Greenhouse public source detection and the official public Greenhouse Job Board API. It does not use Harvest APIs, customer credentials, application submission endpoints, broad crawling, search engines, LinkedIn, browser automation, JavaScript execution, scheduling, referrals, resume generation, or application submission.

Source detection starts from a company name, a careers URL, or both. A supplied URL is the primary target. Company-name-only detection generates a small bounded set of conservative token candidates, including lowercased, punctuation-removed, whitespace-collapsed, legal-suffix-stripped, and explicitly supplied alias variants. Generated candidates are shown only after validating through Greenhouse; the app returns `not_detected` or `ambiguous` instead of guessing.

Use `/job-sources/detect`, `/job-source-detections`, `/job-source-detections/{run_id}`, the API endpoints under `/api/v1/source-detections`, or the CLI:

```bash
uv run ai-job-finder-detect-source \
	--company "Duolingo" \
	--url https://careers.duolingo.com
```

Detection persists a `SourceDetectionRun` with terminal status `detected`, `not_detected`, `ambiguous`, `failed`, or `source_created`. The preview shows provider, company input, original/final URL, validated token, job count, sample titles, evidence, observed-versus-generated source, and whether a source already exists. Creating a source is never automatic: use `--create`, `--create-and-sync`, the approval API, or the explicit web buttons. Ambiguous runs require selecting a validated token; the app does not auto-select by job count.

Supported Greenhouse signals are deterministic references to `boards-api.greenhouse.io/v1/boards/<token>/jobs`, `/departments`, `/offices`, `boards.greenhouse.io/<token>`, `job-boards.greenhouse.io/<token>`, and embedded board-token configuration. Generic mentions of Greenhouse are ignored. Linked scripts are inspected only when page HTML does not already yield a validated token, with same-origin scripts by default, known Greenhouse hosts allowed, maximum script count, per-script bytes, total bytes, no recursion, no execution, and the same SSRF checks as page fetches.

The public-page fetcher fails closed: it allows only HTTP/HTTPS, rejects embedded credentials, blocks localhost, loopback, private, link-local, multicast, metadata and other non-public addresses after DNS resolution, validates every redirect target, caps redirects, restricts ports to normal web ports unless configured, sets explicit timeouts, caps bytes, validates content type, retries only transient failures, and never sends cookies or authenticated sessions.

To identify a Greenhouse board token, open a public board URL such as `https://boards.greenhouse.io/acme`; the token is the final path segment, `acme`. Configure it from `/job-sources/new` or through `POST /api/v1/job-sources` with provider `greenhouse`, company name, board token, and optional source URL.

Run a sync from the source detail page, the API, or CLI:

```bash
uv run ai-job-finder-sync-source --source-id <uuid>
```

Each import run is recorded under `/job-import-runs/{run_id}` with terminal status `succeeded`, `failed`, or `partial`, counts, connector version, and a safe error message. The CLI returns exit code `0` only for `succeeded`; `partial` and `failed` return `1`. The ranked review queue is at `/discover` and orders active imported leads by open/actionable workflow status, latest score, and source freshness.

Identity and idempotency use `provider + source configuration + Greenhouse post ID`. Exact source identity reuses the same `JobLead` and `JobSourceObservation`; repeated identical imports do not duplicate jobs or evaluations. Mutable job fields are updated only when the source payload changes, and a new immutable evaluation is created only when scoring-relevant data changes.

Connector parsing is intentionally conservative. The Greenhouse adapter accepts only `http` or `https` source URLs, bounds response size and job count, retries only transient upstream failures, and records malformed individual postings as per-item failures instead of aborting the entire fetch. Workplace type inference is narrow: it uses explicit Greenhouse metadata, location strings, or labeled description lines only, not broad keyword scans across the full description.

Source posting state is separate from human workflow status. `source_posting_status` records whether the source observation is open or closed. `posting_status` remains the user's review/pursuit workflow and is not overwritten by imports.

After a fully successful non-suspicious import, previously active observations from that same source that were not seen are marked removed and linked jobs get source posting state `closed`. Failed, partial, and suspiciously empty imports close nothing. If a removed job reappears, the observation reactivates and history is preserved.

Per-job persistence is isolated with database savepoints. A failure while creating or updating one posting, or while creating its evaluation, does not leak partial writes for that item and does not prevent other postings in the same fetch from being processed. Every run still reaches a truthful terminal state.

Duplicate preparation is deterministic and advisory. Observations store a duplicate hint key derived from normalized company, title, location, URL, description fingerprint, and internal job ID. The application does not fuzzy-merge cross-source jobs and does not use embeddings.

Optional fetch-only live smoke:

```bash
AI_JOB_FINDER_RUN_GREENHOUSE_SMOKE=true \
AI_JOB_FINDER_GREENHOUSE_SMOKE_BOARD_TOKEN=acme \
AI_JOB_FINDER_GREENHOUSE_SMOKE_COMPANY=Acme \
uv run ai-job-finder-greenhouse-smoke
```

Optional read-only source-detection live smoke:

```bash
AI_JOB_FINDER_RUN_SOURCE_DETECTION_SMOKE=true \
AI_JOB_FINDER_SOURCE_DETECTION_SMOKE_URL=https://careers.example.com \
uv run ai-job-finder-source-detection-smoke
```

Normal tests, hooks, and CI do not call live Greenhouse.

Lever and Ashby detection are deferred. Future providers can add provider-specific signal extraction and validation behind the same detection-run and approval boundary without adding broad discovery or automatic source creation.

Same-source overlap is rejected explicitly. Only one `running` import run may exist per source at a time, and stale overlap messages include the existing run start time for diagnosis. Different sources can still sync independently.

## Document-Assisted Career Fact Ingestion

The ingestion workflow reduces manual career-fact entry without trusting AI output automatically:

1. Upload a source document from `/documents/new` or `POST /api/v1/documents`.
2. Extract text from the document detail page or `POST /api/v1/documents/{document_id}/text-extraction`.
3. Start fact extraction explicitly from the document detail page or `POST /api/v1/documents/{document_id}/extractions`.
4. Review proposals under `/fact-proposals` or `/api/v1/fact-proposals`.
5. Edit, accept, reject, or merge each proposal.
6. Accepted proposals create `draft` career facts. The existing verification lifecycle still applies.

Supported upload formats:

- `.txt` with valid UTF-8 text
- `.pdf` with embedded selectable text

Known PDF limitation: scanned/image-only PDFs fail with a clear error because OCR is not implemented in this slice. The application does not send raw binary PDFs to an LLM.

Uploaded bytes are stored outside the database under `LOCAL_DOCUMENT_STORAGE_DIR` through a storage abstraction. Docker Compose mounts this as the `document-storage` volume at `/app/.local/document-storage`. API responses expose document metadata and IDs, not filesystem paths.

Proposal lifecycle:

- `pending`: editable and reviewable
- `accepted`: creates a new draft career fact and links the proposal to it
- `rejected`: retained for audit but not used
- `merged`: links to an existing fact and only performs explicit narrow enrichment

Merging may append technologies and evidence tags, fill empty metric/leadership/business-outcome fields, and replace the canonical statement or approved wording only when the reviewer explicitly chooses those options. Populated canonical fields are not silently overwritten.

Proposals are separate from career facts because source-document extraction is an untrusted drafting aid. This keeps provenance, model metadata, malformed output, rejected suggestions, and duplicate hints auditable without contaminating canonical evidence.

## Vertex AI Gemini Setup

Extraction is disabled by default. Upload and text extraction still work when Vertex is absent; LLM extraction returns a structured `extraction_provider_unavailable` error until configured.

Required environment variables for live Vertex extraction:

```bash
EXTRACTION_ENABLED=true
EXTRACTION_PROVIDER=vertex
VERTEX_PROJECT=your-gcp-project
VERTEX_REGION=us-central1
VERTEX_GEMINI_MODEL_ID=gemini-2.5-flash
EXTRACTION_PROMPT_VERSION=career_fact_extraction_v1
EXTRACTION_SCHEMA_VERSION=career_fact_extraction_schema_v1
EXTRACTION_TEMPERATURE=0
EXTRACTION_TIMEOUT_SECONDS=30
```

Authentication uses Google Application Default Credentials. Local options:

```bash
gcloud auth application-default login
gcloud config set project your-gcp-project
```

For containerized local development, do not bake credentials into the image. Use a Compose override or shell environment that mounts an ADC file or gcloud config directory intentionally, then set `GOOGLE_APPLICATION_CREDENTIALS` if using a service-account JSON file.

Minimum permissions depend on the chosen project policy, but the runtime identity needs access to call Vertex AI generative model inference, typically via `roles/aiplatform.user` or a narrower custom role that allows prediction/generative inference in the configured region.

Run the opt-in live smoke only when billing and credentials are intentionally configured:

```bash
AI_JOB_FINDER_RUN_VERTEX_SMOKE=true \
EXTRACTION_ENABLED=true \
VERTEX_PROJECT=your-gcp-project \
VERTEX_REGION=us-central1 \
uv run ai-job-finder-vertex-smoke
```

Normal tests, hooks, and CI do not call Vertex.

## Extraction Guardrails And Cost Controls

- Extraction is disabled by default.
- Upload size is limited by `MAX_UPLOAD_SIZE_BYTES`.
- Extracted text is limited by `EXTRACTION_MAX_EXTRACTED_CHARACTERS`.
- Deterministic chunking is limited by `EXTRACTION_CHUNK_SIZE` and `EXTRACTION_MAX_CHUNKS`; documents that exceed the configured chunk count fail clearly instead of being partially processed.
- Raw model output may be persisted on extraction runs for debugging, but logs avoid dumping full document contents or raw provider responses by default.
- Extraction uses low/zero temperature and an explicit timeout.
- Upload does not automatically start extraction.
- No automatic retries are performed by the application service.
- Logs include run start/end, document ID, chunk count, provider/model, prompt version, token usage when available, elapsed time, and status, but not full document content by default.
- Structured output is validated with Pydantic, supporting excerpts must be grounded in extracted text, and within-run duplicates are removed before persistence.

## Candidate Knowledge Base Slice

This slice is intentionally single-candidate.

- Exactly one active candidate profile is supported.
- The candidate profile stores typed collections for preferred locations, target levels, and target functions.
- Career facts are canonical reviewed evidence items, not resume fragments.
- Evaluations only consume verified, non-archived career facts.

The current lifecycle for a career fact is:

- `draft`
- `verified`
- `archived`

Allowed transitions:

- `draft` -> `verified`
- `draft` -> `archived`
- `verified` -> `draft`
- `verified` -> `archived`
- `archived` -> `draft`

Material edits to a verified fact return it to `draft`. Archived facts remain stored for audit and provenance but are hidden from the default fact list and excluded from evaluation.

### Evidence Tags

Controlled evidence tags currently supported:

- `people_leadership`
- `manager_of_managers`
- `platform_engineering`
- `developer_experience`
- `developer_productivity`
- `infrastructure`
- `shared_services`
- `ai_enablement`
- `ml_platform`
- `data_platform`
- `global_operations`
- `high_scale`
- `regulated_environment`
- `customer_impact`
- `p_and_l`
- `vendor_management`
- `cost_optimization`
- `reliability`
- `security`
- `observability`
- `ci_cd`
- `cloud`
- `kubernetes`

### Provenance

Each fact carries a typed provenance source plus free-form source reference:

- `resume`
- `performance_review`
- `project_notes`
- `personal_recollection`
- `verified_external_source`
- `other`

## Evaluation Notes

- The scoring version for the current slice is `candidate_evidence_v2`.
- `technical_alignment_score` now uses overlap between verified evidence tags and deterministic job signals.
- `leadership_scope_score` now uses verified leadership evidence and structured leadership fields rather than prose-only inference.
- Explanations now include matched verified evidence, concerns, missing evidence, and the scoring version.
- Historical evaluations remain stored by scoring version, so earlier `foundation_v1` rows are preserved.

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

The `document-storage` named volume stores uploaded document bytes for local development. Remove it with `docker compose down -v` when you want a clean document store.

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

Run only the web integration tests when iterating on the server-rendered console:

```bash
uv run pytest tests/integration/test_web.py
```

The repository keeps a clear split by directory:

- `tests/unit` for fast unit tests
- `tests/integration` for real-infrastructure integration tests

## Seed Development Data

Seed development data when needed:

```bash
uv run ai-job-finder-seed
```

## API Bootstrap Harness

The repository also includes an API-driven bootstrap and acceptance harness for the candidate knowledge-base slice. This is not a database seed path. It validates the running application exclusively through the public API routes a real client would use.

Prerequisites:

1. Start the Docker Compose stack.
2. Wait for the `app` service to become healthy and respond on `http://localhost:8000`.

Start the stack:

```bash
docker compose up --build
```

Run the harness against the local stack:

```bash
uv run ai-job-finder-bootstrap --base-url http://localhost:8000 --reset --allow-destructive
```

Useful options:

- `--base-url` overrides the API origin. Default: `http://localhost:8000`
- `--timeout` sets the per-request timeout in seconds.
- `--readiness-timeout` controls how long the harness waits for `/api/v1/health` before failing.
- `--reset` requests destructive reset of the bootstrap-owned candidate slice.
- `--allow-destructive` is required with `--reset`.
- `--allow-non-localhost-destructive` is required if destructive reset targets anything other than `localhost` or `127.0.0.1`.
- `--verbose` prints HTTP progress while the harness runs.
- `--json-output path/to/file.json` writes structured run metadata and per-phase outcomes.
- `--document-ingestion` runs the optional fake-extractor document-ingestion phase. Start the app with `EXTRACTION_ENABLED=true EXTRACTION_PROVIDER=fake` for this phase.
- `--fake-greenhouse` runs the optional fake-Greenhouse detection and import phase. Start the app with `GREENHOUSE_FAKE_FIXTURE_PATH=/tmp/ai-job-finder-fake-greenhouse.json` so the server uses the file-backed fake connector, then run the harness with the same path.

Expected summary output is concise:

```text
PASS candidate created
PASS second candidate rejected
PASS 5 draft facts created
PASS draft facts excluded from scoring
PASS verified evidence increased platform alignment
PASS verified edit returned fact to draft
PASS archived fact excluded
PASS filters validated
PASS comparative evaluations validated

# with --document-ingestion
PASS document ingestion acceptance flow validated

# with --fake-greenhouse
PASS fake Greenhouse import acceptance flow validated

Acceptance checks: 10 passed, 0 failed
```

Safety model:

- The harness uses stable ownership markers in candidate naming, career-fact `source_reference`, and job `external_id` values.
- Normal reruns reuse bootstrap-owned jobs and facts rather than creating duplicates.
- Destructive reset is limited to the single active candidate slice through a development-only API route, which cascades only that candidate's career facts and evaluations.
- Destructive reset is refused unless `--reset --allow-destructive` is supplied.
- Destructive reset is also refused for non-localhost targets unless `--allow-non-localhost-destructive` is supplied.
- The harness does not delete unrelated jobs or user-created records.
- The optional document-ingestion phase uses public upload and proposal-review API routes. It does not require live Vertex access when the app is configured with the fake extractor.
- The optional fake-Greenhouse phase uses public source-detection/source/import/discovery API routes. It does not call live Greenhouse when the app is configured with the file-backed fake connector.

JSON output captures:

- base URL and reset mode
- created and reused identifiers
- per-phase pass or fail records
- total passed and failed assertions

Difference between related tools:

- Seed data populates local development content directly and is intended for convenience.
- Automated tests verify code behavior in controlled test environments.
- The bootstrap harness validates the live running application through HTTP, using public API contracts and acceptance-style assertions.

## Run The API

Start the API directly from the local environment:

```bash
uv run uvicorn ai_job_finder.main:app --reload
```

The web console is served at `http://127.0.0.1:8000/jobs` and the JSON API is served at `http://127.0.0.1:8000/api/v1`.

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
- [Architecture Decision 0002](docs/decisions/0002-candidate-knowledge-base.md)
- [Architecture Decision 0003](docs/decisions/0003-document-assisted-career-fact-ingestion.md)
- [Architecture Decision 0004](docs/decisions/0004-greenhouse-job-discovery-ingestion.md)
- [Architecture Decision 0005](docs/decisions/0005-deterministic-greenhouse-source-detection.md)
