# ADR 0001: Foundation Architecture

## Status

Accepted

## Context

The first slice must prove one trustworthy workflow end to end without drifting into automation-heavy behavior that obscures correctness.

## Decision

- Manual job entry is the first ingestion path so provenance, normalization, and evaluation behavior can be validated before introducing scraping complexity.
- Deterministic scoring comes before LLM evaluation so recommendation behavior is explainable, testable, and stable under version control.
- Career facts are canonical verified data rather than resume-derived text so later resume generation can reuse approved facts without inventing or mutating evidence.
- Scraping, browser automation, and application submission are deferred because they add operational complexity before the core data model and recommendation logic are proven.

## Consequences

- Early product velocity is focused on trust, auditability, and maintainability instead of breadth.
- Every evaluation can be explained from persisted inputs and domain rules.
- Future AI-assisted scoring can add evidence and ranking heuristics without replacing deterministic policy checks.
