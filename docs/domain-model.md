# Domain Model

## CandidateProfile

Represents the managed search persona. It stores targeting preferences needed to score manually entered jobs.

- Only one active candidate profile is supported in this slice.
- Preferred locations, target levels, and target functions are stored as typed collections rather than comma-delimited strings.

## CareerFact

Represents a reusable reviewed evidence item or accomplishment bundle.

- Facts are canonical data, not resume fragments.
- Facts carry category, source organization, statement, metric, technologies, leadership scope, business outcome, approved wording, and source reference.
- Facts also carry controlled evidence tags plus a typed provenance source.
- Only verified, non-archived facts are usable during evaluation.

### Career Fact Lifecycle

- `draft` -> `verified`, `archived`
- `verified` -> `draft`, `archived`
- `archived` -> `draft`

Verification and archival timestamps are stored explicitly. Editing a verified fact returns it to draft when the content changes. Archived facts are retained for history and provenance but excluded from normal evaluation.

### Evidence Tags

- `people_leadership`
- `manager_of_managers`
- `platform_engineering`
- `developer_experience`
- `developer_productivity`
- `infrastructure`
- `shared_services`
- `ai_enablement`
- `ml_platform`
- `data_platform`
- `global_operations`
- `high_scale`
- `regulated_environment`
- `customer_impact`
- `p_and_l`
- `vendor_management`
- `cost_optimization`
- `reliability`
- `security`
- `observability`
- `ci_cd`
- `cloud`
- `kubernetes`

### Provenance Types

- `resume`
- `performance_review`
- `project_notes`
- `personal_recollection`
- `verified_external_source`
- `other`

## JobLead

Represents a manually entered role with raw and normalized text, explicit provenance, and a controlled posting-status lifecycle.

## JobEvaluation

Represents a deterministic, explainable evaluation of a single job against a single candidate using a versioned scoring configuration.

## Posting Status Lifecycle

- `discovered` -> `reviewing`, `rejected`, `closed`
- `reviewing` -> `pursuing`, `rejected`, `closed`
- `pursuing` -> `rejected`, `closed`
- `rejected` and `closed` are terminal

## Scoring Components

- `level_score`
- `technical_alignment_score` derived from deterministic job-signal overlap with verified evidence tags
- `location_score`
- `platform_ownership_score`
- `leadership_scope_score` supported by verified leadership evidence rather than prose-only inference
- `referral_priority_score` set to `0` in this slice and explicitly documented as deferred

Overall score is a weighted sum using the candidate knowledge base scoring version `candidate_evidence_v2`.
