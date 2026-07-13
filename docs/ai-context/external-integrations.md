# External Integrations

## Vertex AI Gemini

- protocol: `CareerFactExtractor`
- adapter: `infrastructure/llm/vertex.py`
- fake: `infrastructure/llm/fake.py`
- prompt: `infrastructure/llm/prompts/career_fact_extraction_v1.md`

Guardrails include disabled-by-default configuration, explicit invocation, structured output, validation, versioned prompt/schema, low temperature, bounds, timeout, and no live calls in normal tests.

## Local Document Storage

Implementation: `infrastructure/storage.py`.

The database stores storage keys and metadata. API responses do not expose filesystem paths.

## Greenhouse

- adapter: `infrastructure/job_sources/greenhouse.py`
- fake: `infrastructure/job_sources/fake.py`

Connector owns public API calls, timeouts, retries, response/job bounds, malformed-item isolation, normalization, conservative workplace inference, and token validation.

Application services own persistence, evaluations, closure, overlap, approval, and terminal states.

## Public Careers-Page Fetching

Implementation: `infrastructure/public_fetcher.py`.

This is a bounded fetcher, not a crawler or browser. No JavaScript, cookies, authentication, private-network access, recursive crawling, or broad search.

## Deferred Providers

Lever and Ashby remain deferred. Do not add a broad plugin framework before a second provider proves the extension points.
