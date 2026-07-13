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
