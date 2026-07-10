# Architecture

The foundation slice keeps deterministic business rules in the domain layer and uses FastAPI and SQLAlchemy only as delivery and persistence adapters.

## Layering

- `domain`: enums, workflow rules, scoring, and immutable snapshots.
- `application`: explicit use-case functions for create, retrieve, transition, and evaluate flows.
- `infrastructure`: SQLAlchemy models, session management, and the seed command.
- `api`: versioned HTTP endpoints and transport schemas.

## Request Flow

1. FastAPI validates request payloads with Pydantic v2 schemas.
2. Application services orchestrate explicit use cases.
3. Domain rules score jobs and validate workflow transitions without depending on web or ORM frameworks.
4. SQLAlchemy persists normalized entities and explainable evaluation output.

## Initial Entity Diagram

```mermaid
erDiagram
    CandidateProfile ||--o{ CareerFact : has
    CandidateProfile ||--o{ JobEvaluation : receives
    JobLead ||--o{ JobEvaluation : produces

    CandidateProfile {
        uuid id PK
        string full_name
        json preferred_locations
        string remote_preference
        json target_levels
        json target_functions
        datetime created_at
        datetime updated_at
    }

    CareerFact {
        uuid id PK
        uuid candidate_profile_id FK
        string category
        string statement
        json technologies
        string verification_status
        string source_reference
        datetime created_at
        datetime updated_at
    }

    JobLead {
        uuid id PK
        string source
        string external_id
        string company_name
        string title
        string workplace_type
        text description_raw
        text description_normalized
        string posting_status
        datetime discovered_at
    }

    JobEvaluation {
        uuid id PK
        uuid candidate_profile_id FK
        uuid job_lead_id FK
        string scoring_version
        int level_score
        int location_score
        int platform_ownership_score
        int leadership_scope_score
        float overall_score
        string recommendation
        text explanation
        datetime evaluated_at
    }
```

## Maintainability Notes

- Workflow transitions are centralized in domain code, not scattered across endpoints.
- Evaluation stores each component score independently so later scoring revisions remain auditable.
- Raw job text is preserved alongside normalized text to keep provenance intact.
- Typed JSON collections are limited to fields that are naturally list-shaped in this slice.