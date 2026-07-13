# AI Context Index

These files are concise repository maps for development agents. They supplement, rather than replace, the README, architecture document, domain model, ADRs, source code, OpenAPI information, and CodeGraph.

Open only the documents relevant to the task.

## Lookup Order

After reading `AGENTS.md` and this index, keep focused context ahead of broad search:

1. focused AI-context document
2. applicable ADR
3. OpenAPI or schema information when transport behavior matters
4. CodeGraph for symbols, callers, implementations, dependencies, tests, and likely impact
5. smallest relevant source-file set
6. broad search fallback

Before implementation, produce the impact analysis described in `AGENTS.md` and `repository-navigation.md`. If the impact surface changes materially, update the analysis before broadening the edit set.

For CodeGraph setup, refresh commands, validation examples, and known limitations, read `codegraph.md` and `codegraph-validation.md`.

## Task-to-Document Map

### Domain enum, state, scoring, or lifecycle change

Read:

- `domain-lifecycles.md`
- `architecture.md`
- `persistence-and-migrations.md`
- the relevant ADR

### Application workflow or transaction change

Read:

- `application-services.md`
- `service-boundaries.md`
- `testing-and-acceptance.md`
- the relevant ADR

### API, web, or CLI change

Read:

- `api-web-cli-surfaces.md`
- `application-services.md`
- `testing-and-acceptance.md`

Inspect OpenAPI/schema information and query CodeGraph for all callers of the shared service.

### Database model or migration change

Read:

- `persistence-and-migrations.md`
- `domain-lifecycles.md`
- `testing-and-acceptance.md`

### Greenhouse import or source-detection change

Read:

- `external-integrations.md`
- `application-services.md`
- `service-boundaries.md`
- ADR 0004 or 0005

### Document ingestion or Vertex change

Read:

- `external-integrations.md`
- `domain-lifecycles.md`
- `application-services.md`
- ADR 0003

### Test-only or acceptance-harness change

Read:

- `testing-and-acceptance.md`
- the context document for the behavior under test

### Planning a new product slice

Read:

- `current-priorities.md`
- `architecture.md`
- `repository-navigation.md`
- applicable ADRs

### CodeGraph setup, indexing, or validation

Read:

- `codegraph.md`
- `codegraph-validation.md`
- `repository-navigation.md`

## Source of Truth

- Executable behavior: source code and tests
- Persisted schema history: Alembic migrations
- Accepted architectural intent: ADRs
- Current broad product behavior: README and architecture docs
- Navigation and agent workflow: this directory, `AGENTS.md`, and CodeGraph
- CodeGraph setup and validation: `codegraph.md` and `codegraph-validation.md`

When documentation and code disagree, investigate before editing. Do not silently choose one.
