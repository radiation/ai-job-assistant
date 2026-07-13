# Current Priorities

## Current Documentation Slice

1. add agent instructions
2. add focused AI-context maps
3. add prompt recipes

No application behavior changes belong in this slice.

CodeGraph installation, configuration, indexing, representative trace validation, and index tuning are follow-up infrastructure work, not part of this documentation-only slice.

## Goal

Reduce repository rediscovery and prevent parallel abstractions or missed cross-surface impacts.

Every future slice should begin with CodeGraph-assisted impact analysis and a bounded file set.

## Implemented Product State

- one active candidate
- canonical reviewed facts
- deterministic evaluation
- document-assisted proposals and review
- Greenhouse source configuration/import
- deterministic Greenhouse source detection
- API, web, CLI, fakes, and acceptance harnesses

## Deferred

- broad discovery
- scheduling/background workers
- Lever/Ashby
- browser automation
- autonomous source creation
- referrals
- resume generation
- applications and tracking
- multi-candidate support
- fuzzy merging
- embeddings/vector search
- OCR
- agent frameworks

## Refactoring Watch List

- `application/services.py`
- `infrastructure/database/models.py`
- `api/v1/routes.py`
- broad integration test files

Do not split these in the current slice.
