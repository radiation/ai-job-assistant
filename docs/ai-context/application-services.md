# Application Service Map

Application services are the shared use-case layer for JSON API routes, web routes, and CLI commands.

## General Services

Module: `application/services.py`

Contains foundational candidate, career-fact, job-lead, transition, and evaluation flows.

Before adding a service, query CodeGraph for existing equivalent behavior, callers, routes, and tests. Do not create transport-specific duplicates.

## Document Services

Package: `application/documents/`

Owns document metadata, storage coordination, extraction-run orchestration, proposal review flows, and document retrieval behavior.

Use the package root for stable document workflows consumed by API, web, or tests. Keep duplicate matching and other low-level helpers in internal modules.

## Fact Extraction

Module: `application/extraction.py`

Owns extraction runs, prompt/schema metadata, result validation, proposal persistence, and review orchestration.

AI output remains a proposal until review. Accepted proposals create draft facts.

## Job Imports

Package: `application/job_sources/`

Owns source-configuration workflows, import-run creation, overlap checks, connector invocation, payload identity, observation lifecycle, discovery ranking, savepoints, evaluation creation, closure/reactivation, and terminal status.

When one application module accumulates workflows with distinct change reasons, split it into a feature package with an intentional root API. Keep transaction ownership explicit in the owning workflow module.

## Source Detection

Module: `application/source_detection.py`

Owns persisted detection runs, URL/company candidate orchestration, token validation, ambiguity, approval, optional sync reuse, and terminal-state guarantees.

## Transaction Expectations

Before changing a workflow, locate:

- session creation
- commit and rollback ownership
- flushes
- savepoints
- terminal-run handling after external failures
- shared transaction behavior across API, web, and CLI

Do not move commit ownership casually.
