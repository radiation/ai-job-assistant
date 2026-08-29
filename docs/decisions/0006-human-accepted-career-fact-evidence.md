# 0006 Human-Accepted Career Fact Evidence

## Status

Accepted

## Context

Career Fact proposals are generated from untrusted document extraction. A reviewer must explicitly accept a proposal before it can affect deterministic saved-search evaluation. Creating a draft fact after acceptance left that explicit review action unable to contribute evidence.

## Decision

- Extraction creates pending proposals only; it never verifies Career Facts.
- Explicit acceptance is the human verification event.
- Accepting a proposal creates a verified Career Fact with `verified_at` populated.
- When extraction identified an existing duplicate fact, acceptance reuses that fact rather than creating a duplicate. It promotes a draft target to verified and preserves a verified target.
- Candidate evidence freshness advances when acceptance adds verified evidence or materially changes a verified target.
- Direct/manual Career Fact creation retains its existing draft lifecycle semantics.

## Consequences

- Accepted proposal content participates in the next saved-search evaluation without a second lifecycle action.
- Rejected and pending proposals remain non-scoring.
- The accepted-proposal relationship and source-document relationship retain audit provenance for reused target facts.
