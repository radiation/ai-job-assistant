# 0004 Greenhouse Job Discovery Ingestion

## Status

Accepted

## Context

The application needs a reliable way to discover public jobs, evaluate them against verified candidate evidence, and present a ranked human review queue. The existing architecture already separates domain rules, application services, infrastructure adapters, API routes, and server-rendered web routes.

This slice is intentionally limited to Greenhouse public Job Board API ingestion. It must not add Harvest credentials, application submission, browser automation, scheduling, background workers, fuzzy merging, embeddings, referrals, resume generation, or non-Greenhouse providers.

## Decision

- Add a small provider-neutral `JobSourceConnector` protocol returning normalized postings.
- Keep Greenhouse HTTP, timeout/retry policy, response parsing, and HTML-to-plain-text normalization in `infrastructure.job_sources`.
- Bound Greenhouse response size and job count, keep URL handling to `http` and `https`, and keep workplace-type inference conservative.
- Persist `JobSourceConfiguration`, `JobImportRun`, and `JobSourceObservation` separately from canonical `JobLead`.
- Use `provider + source configuration + Greenhouse post ID` as exact source identity.
- Preserve source provenance and payload checksums on observations while keeping canonical job fields on `JobLead`.
- Track source posting state separately from the user's workflow status.
- Downgrade malformed individual upstream postings to per-item failures when possible instead of failing the entire fetch.
- Use per-posting and per-evaluation savepoints so one posting failure cannot leak partial writes into another.
- Create immutable evaluations only when a job is newly created or scoring-relevant fields change.
- Mark missing observations closed only after a fully successful non-suspicious import for the same source.
- Reactivate reappearing observations without deleting job, observation, import, or evaluation history.
- Add deterministic advisory duplicate hints, but do not automatically merge fuzzy or cross-source matches.
- Reject same-source overlapping imports with a simple database-backed running-run check suitable for one app instance, and surface stale-run timing in the overlap message.
- Expose sync through web, API, and CLI using the same application service.
- Add a file-backed fake connector for tests and acceptance harnesses, and an opt-in fetch-only live Greenhouse smoke command.

## Consequences

- Normal tests and the fake acceptance phase never call live Greenhouse.
- Import runs are auditable even when provider failures, malformed payloads, evaluation failures, or suspicious empty results occur.
- Partial runs are explicit rather than ambiguous: they preserve good work, report item and evaluation failures, and never close unseen jobs.
- The ranked discovery queue can safely mix imported jobs with existing human workflow status because source posting state does not overwrite review/pursuit state.
- The CLI can be used in scripts because `succeeded` returns exit code `0` and `partial` or `failed` return `1`.
- Future Lever or Ashby support can add another connector behind the same protocol without introducing a broad plugin framework now.
- Scheduling remains deferred. Explicit sync keeps failure handling, transaction behavior, and operator review visible while the source model is still young.
