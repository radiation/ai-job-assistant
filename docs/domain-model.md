# Domain Model

## CandidateProfile

Represents the managed search persona. It stores targeting preferences needed to score manually entered jobs.

## CareerFact

Represents a verified, reusable career fact. Facts are canonical data, not resume fragments. Only verified facts are usable during evaluation.

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
- `technical_alignment_score` set to `0` in this slice and explicitly documented as deferred
- `location_score`
- `platform_ownership_score`
- `leadership_scope_score`
- `referral_priority_score` set to `0` in this slice and explicitly documented as deferred

Overall score is a weighted sum using the foundation scoring version `foundation_v1`.
