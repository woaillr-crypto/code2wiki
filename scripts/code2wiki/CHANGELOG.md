# code2wiki — CHANGELOG

## 0.4.0 — Multi-language + tech-debt cleanup

This release completes the multi-language refactor and pays down four
deferred technical-debt items called out in the original PR summary:

### 4 evolution points landed

1. **`core/*` real code migration** — the 2363-line `analyze_java_project.py`
   monolith has been broken up into clean modules under `core/` and
   `plugins/language_java.py`. The legacy script remains as a 63-line
   deprecation shim that re-exports the public surface.
2. **`core/cross_cutting.py` writer registration** — each plugin now
   registers its cross-cutting contributions with a process-level registry
   instead of writing files directly. The orchestrator emits the merged
   output once every plugin has finished scanning. Single-language projects
   produce byte-identical output; mixed-language projects produce a single
   file per concern with one `## <Language>` section per contributor.
3. **`JavaFileInfo` → generic `FileInfo`** — the dataclass is now
   language-agnostic. Java-specific fields (`feign_clients`, `dubbo_refs`,
   `feign_detail`, `is_mq_producer`, `is_mq_consumer_custom`, `xxl_jobs`)
   are demoted to an `extras` dict under documented `EXTRAS_*` constants.
   `JavaFileInfo` survives as a backwards-compat subclass with `@property`
   bridges so legacy code keeps reading `info.feign_clients` etc.
4. **Regex coverage gaps closed** — Ktor routing DSL, Prisma schemas,
   Django Class-Based Views, and Spring array-form path annotations are
   all detected. See `references/discovery/<lang>.md` for per-language
   detail.

### New mixed-language fixture

`tests/fixtures/mixed/` exercises a Java + TypeScript monorepo. Its
`golden/mixed/02_cross_cutting/mq.md` is the canonical demonstration of
the new merge format:

```
# MQ 消息队列

## Java (Spring + RocketMQ)
### Consumer 清单
...

## TypeScript (NestJS + BullMQ)
### 队列消费
...
```

### Test surface

- 211 tests (up from 40 at Phase 0 baseline)
- 80% line coverage across `core/` + `plugins/` + `cli`
- 6 fixture golden snapshots (java / python / go / kotlin-ktor /
  typescript / mixed) compared byte-for-byte on every CI run
- 17 cross-cutting registry tests
- Regression tests for SystemExit handling, registry leakage, title
  conflicts, the legacy entry point emitting its cross-cutting files,
  and 6 + Django CBV / Prisma / Ktor / Spring-array regex edge cases

### Breaking changes

- `feign_clients` field renamed to `rpc_clients` in `FileInfo`. The legacy
  name remains as a read-only `@property` bridge so consumer code that
  reads `info.feign_clients` keeps working.
- `inventory.json` schema changed: `feign_clients` → `rpc_clients`; new
  `"language"` field added to align Java with the other plugins.
- `analyze_java_project.py` is deprecated. Use
  `scripts/analyze_project.py --language java` instead. The legacy entry
  point still works and prints a `[DEPRECATED]` banner.

### Architecture summary

| Module | Role |
| --- | --- |
| `scripts/analyze_project.py` | New CLI entry point (auto-detects language) |
| `scripts/analyze_java_project.py` | 63-line deprecation shim |
| `core/io.py` | File walking, encoding-tolerant reads, AI-ENRICHED guard |
| `core/markdown.py` | Tables, role labels, naming helpers |
| `core/domain.py` | Domain inference + prefix/synonym merging |
| `core/git.py` | Git history → hot files, contributors, keywords |
| `core/writers.py` | Domain docs, indexes, playbooks, glossary |
| `core/models.py` | `FileInfo`, `ProjectContext`, `GitContext`, `EXTRAS_*` |
| `core/cross_cutting.py` | Registry + merge orchestration |
| `core/detect.py` | Build-manifest + extension language detection |
| `core/registry.py` | Plugin registration |
| `plugins/language_{java,python,go,kotlin,typescript}.py` | Per-language scanners |
