# Quality Gates

Run these checks before declaring a Business Context Layer complete. The
checks apply to all supported languages (Java, Kotlin, Python, Go,
TypeScript/JavaScript) — see `discovery/<lang>.md` for language-specific
detection details.

## Coverage Gate

- Root `SKILL.md` exists and has valid skill frontmatter with only `name` and `description`.
- Project overview names the system, tech stack, modules, and major business capabilities.
- Top API prefixes are mapped to domains.
- Top tables / ORM entities / mappers are mapped to domains.
- 入口（Controller / Handler / NestJS controller / FastAPI router / gRPC service）、业务服务、MQ consumer、scheduler、external client 都出现在 indexes 里。
- Every high-confidence domain has all required domain files.
- Cross-cutting docs exist for auth, permission, transaction, idempotency, cache, MQ, scheduler, and observability, even if some sections say `未发现明确证据`.
- If auxiliary knowledge exists, `06_auxiliary_knowledge/auxiliary_knowledge.md` clearly labels it as optional, lower-priority material.

## Business Usefulness Gate

- Domain names are business terms, not technical package names when avoidable.
- Each domain has business boundary, core concepts, workflows, entrypoints, data model, integrations, and risks.
- Each important claim cites exact files/classes/methods or says `需要确认`.
- A future developer can locate where to implement a typical requirement in under 5 minutes.

## Stability Gate

- The output does not require model memory to understand; it is self-contained Markdown plus JSON.
- Generated files avoid absolute speculation.
- Large raw lists are placed in indexes, not in prose-heavy domain explanations.
- The update playbook tells future agents how to refresh docs after code changes.

## Red Flags

- The output depends on `.claude/skills`, `.cursor`, `.agents`, personal notes, or other external handcrafted knowledge to be useful.
- Output is organized mainly by 技术分层（controller / service / repository / handler / model）而非业务能力.
- Domains are only package names without business interpretation.
- No risk points are documented.
- No exact file paths are provided.
- The generated skeleton was not enriched after script execution.
