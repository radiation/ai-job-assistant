# GitHub Copilot Instructions

This repository is a deterministic, explainable executive job-search platform. Preserve trust, auditability, explicit workflows, and human approval boundaries.

Before implementation, read `AGENTS.md` and `docs/ai-context/README.md`, then open only the focused context documents relevant to the task. Use this lookup order after the focused context is identified:

1. focused AI context
2. applicable ADR
3. OpenAPI or schema information when transport behavior matters
4. CodeGraph for symbols, callers, implementations, dependencies, tests, and likely impact
5. smallest relevant source-file set
6. broad search fallback

Produce a concise impact analysis before changing code. Include domain/lifecycle impact, application services and transactions, infrastructure adapters, persistence and migrations, API/web/CLI surfaces, tests, abstractions to reuse, likely files, high-impact files to avoid, explicit non-goals, and risks.

Keep provider-specific HTTP, SDK, retry, parsing, and storage behavior in infrastructure. Keep deterministic rules and lifecycle validation in domain code. Keep orchestration and transaction behavior in application services. API, web, and CLI delivery code must reuse application services.

Do not add deferred product behavior unless explicitly requested. In particular, do not add broad discovery, browser automation, scheduling, background workers, autonomous source creation, application submission, referrals, resume generation, Lever/Ashby support, fuzzy merging, embeddings, OCR, multi-candidate ownership, or agent frameworks.

For this AI-context foundation slice, do not change application behavior, Python source, tests, migrations, dependencies, Docker/runtime configuration, CI/hooks, or public contracts.
