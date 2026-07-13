# Prompt Recipes

## Impact Analysis Only

```text
Analyze the requested change without editing code.

Follow AGENTS.md and docs/ai-context/README.md. Read only relevant context and ADRs. Use CodeGraph before broad search.

Return:
1. invariants and decisions
2. domain/lifecycle impact
3. application services and transactions
4. infrastructure adapters
5. persistence/migrations
6. API/web/CLI entry points
7. tests and acceptance coverage
8. abstractions to reuse
9. bounded file set
10. high-impact files to avoid
11. non-goals and risks

Do not implement.
```

## Bounded Implementation

```text
Implement the approved slice using the supplied impact analysis.

Do not repeat broad discovery. Recheck CodeGraph only when a dependency is unclear or the impact surface materially changes.

Preserve invariants, reuse existing services/protocols, keep business logic out of delivery/adapters, add no deferred behavior, avoid opportunistic refactors, and run targeted tests before broad validation.

Report summary, changed files, tests/results, architecture implications, migration notes, limitations, and justified deviations.
```

## Cross-Surface Review

```text
Use CodeGraph to identify every API, web, and CLI caller of the changed application service. Verify schemas, errors, templates, exit codes, and tests. Report inconsistencies without adding new behavior.
```

## Lifecycle Review

```text
Identify enums, validators, timestamps, ORM fields, constraints, migrations, schemas, UI controls, CLI behavior, tests, and audit implications. Preserve terminal-state and immutability guarantees unless explicitly changed.
```

## Integration Change

```text
Keep provider SDK/HTTP/retry/parsing behavior in infrastructure. Keep workflow, persistence, approval, and terminal-state behavior in application services. Normal tests use fakes; live smokes stay opt-in.
```

## CodeGraph Validation

```text
For each trace, give the graph result, verify it against source, identify missing or misleading edges, and recommend indexing or documentation changes. Do not modify application behavior.
```
