# 0003 Document-Assisted Career Fact Ingestion

## Status

Accepted

## Context

The candidate knowledge base needs less manual data entry, but this single-user internal tool cannot let generated content become trusted evidence automatically. The application already separates deterministic domain logic, application services, infrastructure adapters, JSON API routes, and server-rendered web routes.

## Decision

- Use direct Vertex Gemini model inference through a provider-neutral `CareerFactExtractor` protocol.
- Keep Vertex SDK usage under `infrastructure.llm`; domain and application services do not import provider SDKs.
- Request structured JSON output constrained by a schema and parse it into Pydantic models.
- Store versioned prompts in source control and persist prompt/schema versions on every extraction run.
- Persist source documents, extraction runs, and career-fact proposals as separate entities.
- Require human review before AI output can create or enrich canonical career facts.
- Accepted proposals create draft career facts; existing verification rules remain the only path to verified evidence.
- Store uploaded files in local filesystem storage first, behind a small storage interface that can be replaced by cloud storage later.
- Do not introduce an agent framework, autonomous tool use, embeddings, vector search, OCR, GCS, or a background worker system in this slice.

## Consequences

- The upload and text-extraction workflow works even when Vertex is disabled or unconfigured.
- LLM extraction has explicit cost controls: upload size, extracted character limit, chunk limit, timeout, disabled-by-default configuration, low temperature, and no automatic extraction on upload.
- The review queue preserves failed runs and rejected proposals for audit and debugging.
- Duplicate detection is deterministic and advisory; reviewers explicitly accept, reject, or merge proposals.
- Cloud storage and richer asynchronous execution can be added later without changing the proposal review boundary.
