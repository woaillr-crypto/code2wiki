# Business Context Layer Model

## Goal

The Business Context Layer (BCL) is a business-facing map of a backend
codebase (Java/Spring, Python/FastAPI/Django, Go/Gin, Kotlin/Ktor,
TypeScript/NestJS, …). It helps an LLM answer:

1. Which business domain owns this requirement?
2. Which concepts, workflows, APIs, tables, jobs, messages, and integrations are involved?
3. Which code should be inspected or changed first?
4. What risks must be handled before implementation is considered safe?

## Domain Document Semantics

- `skill.md`: the domain's activation guide. It should say when to use the domain, business boundary, key files, and modification checklist.
- `concepts.md`: business vocabulary, domain entities, state machines, identifiers, and ambiguous terms.
- `workflows.md`: end-to-end business flows with triggers, actors, decisions, side effects, and failure branches.
- `api_map.md`: inbound HTTP/RPC entrypoints mapped to use cases.
- `db_map.md`: tables/entities/mappers, key fields, lifecycle, and data compatibility concerns.
- `code_entrypoints.md`: Controllers, Services, Managers, Repositories, clients, validators, converters, tests.
- `integration_map.md`: MQ topics, external APIs, scheduled jobs, callbacks, files, and third-party systems.
- `risk_points.md`: concurrency, transaction, idempotency, permissions, cache, retries, eventual consistency, legacy behavior.
- `examples.md`: real or inferred requirement examples and where to change code.

## Cross-Cutting Document Semantics

Cross-cutting docs are for concerns reused by many domains: auth, permission,
transaction, idempotency, cache, MQ, scheduler, and observability. They must
point back to domains and exact code files.

### Multi-language merging

Each language plugin contributes its findings to the cross-cutting registry.
When **only one** plugin is active for a project (e.g. a pure-Java backend),
the cross-cutting file is the plugin's contribution verbatim:
``# <Title>`` followed by the plugin's body.

When **two or more** plugins are active for the same project (a Monorepo
with Java backend + TypeScript frontend, say), the orchestrator merges all
contributors into a single file under one ``# <Title>``:

```
# MQ 消息队列

## Java (Spring + RocketMQ)

### Consumer 清单
...

## TypeScript (NestJS + BullMQ)

### 队列消费
...
```

Plugin sub-headings (``##``) are automatically demoted to ``###`` inside
the merged sections so the document hierarchy stays sensible. The Java
section always renders first because the language ids are sorted
alphabetically — this gives mono-repos a stable diff regardless of
plugin discovery order.

## Index Semantics

Indexes are machine-friendly navigation aids. Keep them dense and path-rich:

- API path -> Controller -> domain -> use case
- table/entity -> mapper/repository -> domain
- class -> role -> domain
- dependency -> caller -> risk

## Quality Bar

A BCL is useful only if it can drive code changes. Avoid architecture essays. Prefer concrete maps, exact paths, and short business explanations.
