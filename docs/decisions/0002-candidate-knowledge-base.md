# ADR 0002: Candidate Knowledge Base Slice

## Status

Accepted

## Context

The application needs a trustworthy candidate understanding workflow before it adds any document extraction, resume parsing, or LLM behavior.

The product is also intentionally single-user and single-candidate in this phase. The main risk is drifting into unreviewed inferred data before the system has a durable review loop.

## Decision

- Canonical career facts are the source of truth for downstream evaluation rather than unreviewed resume text or parsed document fragments.
- Career facts use an explicit lifecycle of `draft`, `verified`, and `archived` instead of a verification boolean or loosely defined statuses.
- Evidence tags come from a controlled vocabulary rather than free-form tags or LLM-derived classifications so deterministic scoring stays testable and auditable.
- Provenance is modeled explicitly with a typed source and a human-readable source reference.
- The slice supports exactly one active candidate profile. Application services enforce that invariant and persistence adds a unique active-candidate backstop.
- Document ingestion, resume parsing, and LLM extraction are deferred until reviewed evidence workflows exist, because ingestion without review would create low-trust facts that pollute scoring.

## Consequences

- Candidate setup, profile editing, and fact review become first-class workflows in the server-rendered console and JSON API.
- Deterministic scoring can cite matched verified evidence directly and can exclude draft or archived facts cleanly.
- The current scope avoids introducing candidate switching, ownership, or multi-user abstractions too early.
- Multi-candidate support remains feasible later by relaxing the active-candidate constraint and threading candidate selection through the existing services without rewriting the core fact or scoring model.
