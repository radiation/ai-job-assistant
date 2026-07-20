# Domain Lifecycles and Invariants

## Candidate

Exactly one active `CandidateProfile` is supported. Application services enforce the rule and persistence provides a backstop.

## Career Fact

```text
draft -> verified
draft -> archived
verified -> draft
verified -> archived
archived -> draft
```

Only verified, non-archived facts affect evaluation. Material edits to verified facts return them to draft. Archived facts remain persisted.

## Source Document

```text
uploaded
text_extracted
extraction_failed
facts_extracted
```

Uploading does not automatically invoke an LLM.

## Career Fact Proposal

```text
pending -> accepted
pending -> rejected
pending -> merged
```

Terminal states are immutable except for audit metadata. Accepting creates a draft fact. Merging performs explicit narrow enrichment. Proposals are never verified automatically.

## Job Lead Workflow Status

```text
discovered -> reviewing
discovered -> rejected
discovered -> closed
reviewing -> pursuing
reviewing -> rejected
reviewing -> closed
pursuing -> rejected
pursuing -> closed
```

`rejected` and `closed` are terminal. Human workflow status is separate from source posting status.

## Job Import Run

```text
succeeded
partial
failed
```

A run exists before fetching. Completed attempts reach truthful terminal states. Same-source overlap is rejected. Historical runs remain.

Missing observations close only after a fully successful, non-suspicious import. Failed, partial, and suspiciously empty imports close nothing.

## Source Detection Run

```text
running -> detected
running -> not_detected
running -> ambiguous
running -> failed
running -> source_created
```

Every attempt is persisted. Ambiguity requires explicit token selection. Detection never creates a source automatically.

## Evaluation

`JobEvaluation` is immutable historical output tied to a scoring version. Current version: `candidate_evidence_v2`.

Create a new evaluation only for a new job or materially changed scoring inputs.

## Job Search Definition

Saved searches are persisted, provider-neutral definitions. `enabled` is operational state only; it does not delete runs or matches.

Definitions contain deterministic title patterns, target domains, target seniority levels, location/workplace rules, and a minimum score threshold.

## Job Search Run

```text
running -> completed
running -> partial
running -> failed
```

Every manual run is persisted before evaluation begins. Historical runs remain. A new run creates a new historical record even when it evaluates the same imported jobs.

`matched_by_criteria` counts leads that satisfied saved-search filters before score checks. `evaluated_count` counts leads for which a current evaluation was successfully used, whether reused or newly created. `above_threshold_count` counts evaluated leads at or above the saved-search minimum score threshold. Final matches are leads that remain after exclusions.

## Job Search Match

One persisted match record exists per job lead per run. Matches retain score-at-run-time, matched criteria, exclusion reasons, inferred domain and seniority, and threshold outcome.
