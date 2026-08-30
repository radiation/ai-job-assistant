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

Terminal states are immutable except for audit metadata. Human acceptance creates verified candidate evidence, or promotes an advisory duplicate target to verified without creating a duplicate fact. Merging performs explicit narrow enrichment. Extraction alone never verifies a proposal or fact.

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

Daily scheduled discovery is opt-in. It claims due saved searches atomically and records its attempted and completed timestamps without changing manual discovery behavior.

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

An actionable canonical job may create one email notification per saved search. The notification is committed before SMTP delivery is attempted and is deduplicated by saved search and canonical job lead, rather than discovery run; therefore, an existing actionable job can email once on the first scheduled run after scheduling is enabled if no prior notification exists.

Disabled or incomplete email configuration creates no notification, leaving an actionable match eligible for a future configured send. Once SMTP delivery is attempted, confirmed delivery marks the durable notification `succeeded`; SMTP failures mark it `failed` with a bounded failure message. Failed notifications are not retried automatically and rediscovery does not create or send another notification. SMTP delivery is at-least-once at the external-system boundary: a process can fail after SMTP accepts a message but before PostgreSQL records success, so exactly-once email delivery is not claimed.
