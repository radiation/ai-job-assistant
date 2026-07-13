# Service Boundaries

## CareerFactExtractor

Provider-neutral boundary for structured proposal extraction.

Implementations:

- fake extractor
- Vertex adapter under `infrastructure/llm/`

Domain and application code do not import Google SDKs.

## Document Storage

Provider-neutral boundary for uploaded bytes.

Initial implementation: local filesystem through `infrastructure/storage.py`.

Clients receive document metadata and IDs, not filesystem paths.

## JobSourceConnector

Provider-neutral boundary for normalized postings and Greenhouse validation.

Implementations:

- Greenhouse connector
- file-backed fake connector

Connectors own provider HTTP, retries, parsing, bounds, and normalization. Application services own workflow, persistence, approval, closure, and evaluations.

## Public Page Fetcher

SSRF-safe boundary for bounded source-detection inspection.

Owns scheme, userinfo, DNS/address, redirects, ports, byte limits, content type, timeouts, retries, and no-cookie/no-JavaScript rules.

## Boundary Rules

Add a boundary when provider behavior must not leak inward, tests need a deterministic fake, or replacement should not change domain rules.

Do not add a framework or registry prematurely.

API, web, and CLI converge at application services.
