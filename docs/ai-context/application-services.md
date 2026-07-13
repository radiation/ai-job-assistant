# Application Service Map

Application services are the shared use-case layer for JSON API routes, web routes, and CLI commands.

## General Services

Module: `application/services.py`

Contains foundational candidate, career-fact, job-lead, transition, and evaluation flows.

Before adding a service, query CodeGraph for existing equivalent behavior, callers, routes, and tests. Do not create transport-specific duplicates.

## Document Services

Module: `application/document_services.py`

Owns document metadata, storage coordination, text extraction workflow, and document retrieval behavior.

## Fact Extraction

Module: `application/extraction.py`

Owns extraction runs, prompt/schema metadata, result validation, proposal persistence, and review orchestration.

AI output remains a proposal until review. Accepted proposals create draft facts.

## Job Imports

Module: `application/job_imports.py`

Owns import-run creation, overlap checks, connector invocation, normalized posting processing, observation identity, checksums, savepoints, evaluation creation, closure/reactivation, and terminal status.

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
