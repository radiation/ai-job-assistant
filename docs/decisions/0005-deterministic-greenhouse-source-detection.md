# 0005 Deterministic Greenhouse Source Detection

## Status

Accepted

## Context

Operators need a faster way to configure public Greenhouse sources when they know a company name, a careers URL, or both. The system already has a Greenhouse connector, source configuration service, import service, API, CLI, web UI, Docker setup, and fake acceptance harness. Detection must not become broad discovery: no web search, crawling, LinkedIn, browser automation, JavaScript execution, other ATS providers, scheduling, or autonomous source creation.

Public-page fetching introduces SSRF risk, and Greenhouse references in HTML are not enough by themselves. A detected token must validate through the public Greenhouse Job Board API before it can be presented for approval.

## Decision

- Persist every detection attempt as `SourceDetectionRun` with statuses `running`, `detected`, `not_detected`, `ambiguous`, `failed`, and `source_created`.
- Start each run in `running` and require a terminal status for every completed attempt.
- Store concise structured evidence and candidate metadata, not raw page HTML.
- Add a small SSRF-safe public-page fetcher abstraction that allows only HTTP/HTTPS, rejects userinfo and non-public resolved addresses, validates every redirect target, caps redirects, restricts ports, sets explicit timeouts, caps response bytes, validates content type, retries transient failures only, sends no cookies, and executes no JavaScript.
- Detect only deterministic Greenhouse signals: public board API URLs, board links, job-board links, and embedded board-token configuration. Generic Greenhouse mentions are ignored.
- Inspect bounded same-origin and known Greenhouse linked scripts only if page HTML does not already produce a validated token. Do not recursively crawl assets.
- Generate company-name candidates only from conservative deterministic variants and explicit aliases. Present generated candidates only when Greenhouse validation succeeds.
- Reuse the Greenhouse connector boundary for read-only board-token validation, including valid empty boards, malformed provider responses, invalid tokens, and provider unavailability.
- Mark multiple validated candidates as `ambiguous` and require explicit selection. Do not rank or auto-select by job count.
- Keep source creation and sync behind explicit human approval. Approval reuses the existing source creation and import services and links the run to the created or existing source configuration.
- Expose the workflow through versioned API endpoints, `/job-sources/detect`, `/job-source-detections`, `/job-source-detections/{run_id}`, and `ai-job-finder-detect-source`.
- Add an opt-in read-only live smoke command for known public careers pages; skip it in hooks and normal CI.

## Consequences

- Detection is auditable and repeatable without creating sources automatically.
- SSRF defenses are centralized in one fetcher rather than scattered through parsing code.
- Company-name-only detection is intentionally conservative and may return `not_detected` even when a broader web search could find the company.
- Ambiguity is surfaced to the operator instead of hidden behind heuristics.
- Lever and Ashby can be added later by introducing provider-specific signal extraction and validation behind the same persisted run and approval boundary.
- Broad discovery remains deferred until the source model, evidence format, and review workflow have more production use.
