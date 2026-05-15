<p align="center">
  <h1 align="center">code2wiki</h1>
  <p align="center">
    <strong>AI Agent Skill — Turn 100K–500K+ line backend codebases into structured business knowledge maps in minutes, not weeks.</strong>
  </p>
  <p align="center">
    <a href="#installation">Install</a> · <a href="#effectiveness">Effectiveness</a> · <a href="#中文说明">中文</a> · <a href="#how-it-works">How It Works</a>
  </p>
</p>

---

## The Problem

You have a 200K-line Java/Go/Python backend. A new developer joins — they spend **2–4 weeks** reading code before making meaningful contributions. You ask an LLM to implement a feature — it hallucinates because it has no business context. You try to document — the wiki gets outdated within a month.

**code2wiki** solves this by automatically generating a **Business Context Layer (BCL)** — a living, structured knowledge base that maps business domains, workflows, concepts, risk points, and cross-cutting concerns directly from source code.

## Effectiveness

| Metric | Without code2wiki | With code2wiki | Improvement |
| --- | --- | --- | --- |
| New developer onboarding | 2–4 weeks to productive | 2–3 days to productive | **~80% faster** |
| LLM feature development context | Read entire codebase (hallucination-prone) | Focused BCL docs (~50 files) | **~95% context reduction** |
| Business domain documentation | Manual, 40–80 hours per project | Scanner: 3 min + AI enrichment: 2–4 hours | **~90% time saved** |
| API reverse-lookup accuracy | Requires source code reading | ≥ 67% accuracy from docs alone | **Instant navigability** |
| Documentation freshness | Outdated within weeks | Incremental protection + re-scan | **Always current** |

> Benchmarked on real-world projects: 150K-line Java/Spring monolith (38 domains, 420+ APIs) and 80K-line Go microservice cluster.

## Installation

**code2wiki** is an AI Agent Skill compatible with QoderWork, Claude Code, Cursor, Cline, Codex, and other AI coding agents.

```bash
# Install via skills CLI (recommended)
npx skills add woaillr-crypto/code2wiki

# Or install to a specific agent
npx skills add woaillr-crypto/code2wiki -a claude-code
npx skills add woaillr-crypto/code2wiki -a cursor

# Or install globally
npx skills add woaillr-crypto/code2wiki -g
```

After installation, simply tell your AI agent:

> "Use code2wiki to analyze this project and generate a business context layer."

The agent will automatically invoke the skill, run the scanner, and begin AI enrichment.

### Manual Installation

```bash
git clone https://github.com/woaillr-crypto/code2wiki.git
# Copy the SKILL.md and scripts/ to your agent's skills directory
```

## How It Works

code2wiki operates in two phases — **Scanner** (automated) + **AI Enrichment** (agent-driven):

```
Phase 1: Scanner (3 min for 200K lines)          Phase 2: AI Enrichment (agent-driven)
┌─────────────────────────────────┐              ┌────────────────────────────────────┐
│ Source Code                     │              │ Skeleton Index                     │
│ (Java/Kotlin/Python/Go/TS)     │──── scan ───►│ (file paths, classes, methods,     │
│                                 │              │  call chains, git signals)         │
└─────────────────────────────────┘              └──────────────┬─────────────────────┘
                                                                │
                                                          AI reads 5-10
                                                          core files/domain
                                                                │
                                                                ▼
                                                 ┌────────────────────────────────────┐
                                                 │ Business Context Layer (BCL)       │
                                                 │ • Domain workflows (arrow diagrams)│
                                                 │ • Business concepts & state flows  │
                                                 │ • Risk points (txn/concurrency)    │
                                                 │ • Integration maps (upstream/down) │
                                                 │ • Business rules extraction        │
                                                 └────────────────────────────────────┘
```

### What Makes It Different

| Approach | Output | Business Value |
| --- | --- | --- |
| Code search (grep/IDE) | Raw matches | Zero — still requires human interpretation |
| AST-based doc generators (JavaDoc, Sphinx) | API signatures | Low — no business semantics |
| AI "explain this code" | Per-file summaries | Medium — no cross-domain understanding |
| **code2wiki** | **Domain-organized BCL with workflows, risks, integrations** | **High — LLM can reason about business impact** |

## Supported Stacks

| Language | Frameworks & Detection |
| --- | --- |
| **Java** | Spring Boot, MyBatis, Dubbo, Feign, RocketMQ, XxlJob, Kafka |
| **Kotlin** | Spring Boot, Ktor (routing DSL), Exposed, Coroutines |
| **Python** | Django (CBV+FBV), FastAPI, Flask, SQLAlchemy, Celery, APScheduler |
| **Go** | Gin, Echo, gRPC, GORM, sqlc, robfig/cron, NATS |
| **TypeScript/JS** | NestJS, Express, TypeORM, Prisma, BullMQ, node-cron |

Auto-detection works via build manifests (`pom.xml`, `go.mod`, `pyproject.toml`, `package.json`, etc.) — no configuration needed. Mixed-language monorepos are scanned in parallel with intelligent cross-cutting merge.

## Output Structure

```
business-context-layer/
├── 00_project_overview.md                 # Tech stack, scale metrics, domain candidates
├── 01_business_domains/
│   └── <domain>/
│       ├── skill.md                       # L1 entry: business summary + rules + risks
│       ├── workflows.md                   # Business flow diagrams (arrow notation)
│       ├── concepts.md                    # Core concepts + state transition diagrams
│       ├── call_chains.md                 # Entry → orchestration → external calls
│       ├── api_map.md / db_map.md         # API & database schema mapping
│       ├── integration_map.md             # Upstream/downstream system interactions
│       └── risk_points.md                 # Transaction/concurrency/cache/idempotency
├── 02_cross_cutting/                      # MQ, scheduling, caching, auth, RPC, observability
├── 03_development_playbooks/              # Step-by-step guides for common changes
├── 04_glossary/                           # Business terms → code entry points
├── 05_indexes/                            # API index, call graph, git activity heatmap
└── 06_auxiliary_knowledge/                # Supplementary context
```

## Layered Context Model (L0→L1→L2→Source)

BCL is designed for **progressive loading** — LLMs load only what they need:

| Layer | Content | Answers |
| --- | --- | --- |
| **L0** | Project overview + glossary + indexes | "What does this system do? What domains exist?" |
| **L1** | Domain `skill.md` (≤60 lines each) | "What does this domain do? Key rules? Risks?" |
| **L2** | Workflows, concepts, integrations, risks | "How does the flow work? Who are upstream/downstream?" |
| **Source** | Actual source files pointed to by L2 | Precise implementation details |

Standard development path: **L0 → locate domain → L1 → relevant L2 → drill into Source**.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  scripts/analyze_project.py  (CLI — 89 lines)       │
└───────────────────────┬─────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│  code2wiki/cli.py  (Orchestrator)                   │
│    1. Auto-detect languages                         │
│    2. Run each language plugin in parallel           │
│    3. Merge cross-cutting contributions             │
│    4. Emit unified output                           │
└───────────────────────┬─────────────────────────────┘
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ plugins/     │ │ core/        │ │ cross_cutting│
│ language_*.py│ │ io, domain,  │ │ Registry     │
│ (5 langs)   │→│ git, writers,│ │ (merge logic)│
│              │ │ models, etc. │ │              │
└──────────────┘ └──────────────┘ └──────────────┘
```

## CLI Reference

```bash
# Basic (auto-detect language)
python3 scripts/analyze_project.py /path/to/project --output ./output

# Specify language: java | python | go | kotlin | typescript
python3 scripts/analyze_project.py /path/to/project --language go

# More candidate domains (default 30, large projects use 40-60)
python3 scripts/analyze_project.py /path/to/project --top-domains 40

# Disable domain merging (debug misclassification)
python3 scripts/analyze_project.py /path/to/project --no-merge

# Force overwrite AI-enriched files (use with caution)
python3 scripts/analyze_project.py /path/to/project --force

# Skip git analysis (CI / shallow clone)
python3 scripts/analyze_project.py /path/to/project --no-git

# Run only one plugin in a monorepo
python3 scripts/analyze_project.py /path/to/project --plugin-only typescript
```

## Quality Assurance

The scanner itself is rigorously tested:

- **212 unit tests** with **80% line coverage**
- **6 fixture projects** (Java, Python, Go, Kotlin-Ktor, TypeScript, Mixed monorepo)
- **Golden snapshot comparison** — byte-for-byte output verification on every change
- **5 rounds of code review** — ~100 findings, all resolved

The generated BCL includes a built-in **quality verification protocol** (API reverse-lookup blind test, structure check, end-to-end requirement simulation).

## Extending

Adding a new language takes ~200 lines:

1. Create `plugins/language_<lang>.py` implementing the `LanguageScanner` protocol
2. Register in `core/registry.py` + add detection in `core/detect.py`
3. Add a fixture project + golden snapshot tests

Full guide: [`docs/07-how-to-extend.md`](docs/07-how-to-extend.md)

## License

MIT

---

## 中文说明

<p align="center">
  <h2 align="center">code2wiki — 让 AI 3 分钟读懂 50 万行代码的业务逻辑</h2>
  <p align="center"><strong>AI Agent Skill：为大型后端项目自动生成业务上下文层（Business Context Layer），把「代码黑箱」变成「业务知识地图」。</strong></p>
</p>

## 痛点

你有一个 20 万行的后端项目。新人入职——**花 2–4 周**才能开始有效产出。你让 AI 做需求开发——它因为没有业务上下文而**频繁幻觉**。你想写文档——**一个月后就过时了**。

**code2wiki** 自动生成结构化的业务上下文层（BCL），直接从源码映射出业务域、流程、概念、风险点、横切关注点，形成一份**活的、可维护的项目知识地图**。

## 效果数据

| 指标 | 没有 code2wiki | 使用 code2wiki | 提升幅度 |
| --- | --- | --- | --- |
| 新人上手时间 | 2–4 周到产出 | 2–3 天到产出 | **缩短 ~80%** |
| LLM 需求开发上下文 | 需读整个代码库（易幻觉） | 聚焦 BCL 文档（~50 个文件） | **上下文缩减 ~95%** |
| 业务文档编写 | 人工编写，40–80 小时 | 扫描器 3 分钟 + AI 富化 2–4 小时 | **节省 ~90% 时间** |
| API 反查准确率 | 需阅读源码 | 仅看文档即可达到 ≥67% 准确率 | **即时可导航** |
| 文档时效性 | 几周内过时 | 增量保护 + 定期重扫 | **持续保鲜** |

> 基准测试项目：15 万行 Java/Spring 单体（38 个业务域、420+ API）；8 万行 Go 微服务集群。

## 安装

**code2wiki** 是一个 AI Agent Skill，兼容 QoderWork、Trea、Claude Code、Cursor、Cline、Codex 等主流 AI 编程助手。

```bash
# 通过 skills CLI 安装（推荐）
npx skills add woaillr-crypto/code2wiki

# 安装到指定 Agent
npx skills add woaillr-crypto/code2wiki -a claude-code
npx skills add woaillr-crypto/code2wiki -a cursor

# 全局安装
npx skills add woaillr-crypto/code2wiki -g
```

安装后，直接对你的 AI 助手说：

> "用 code2wiki 分析这个项目，生成业务上下文层。"

Agent 会自动调用 Skill，运行扫描器，并开始 AI 富化。

### 手动安装

```bash
git clone https://github.com/woaillr-crypto/code2wiki.git
# 将 SKILL.md 和 scripts/ 复制到你的 Agent skills 目录
```

## 工作原理

两阶段执行：**扫描器**（自动化，3 分钟）+ **AI 富化**（Agent 驱动，2–4 小时）

**Phase 1 — 扫描器生成骨架**：静态分析源码，产出目录骨架、文件索引、调用链、Git 热点、域聚合。这一步是纯代码级索引——有路径、类名、方法签名，但**没有业务语义**。

**Phase 2 — AI 富化**：Agent 根据优先级打分选择 5–15 个核心域，读取每个域的 5–10 个关键文件，将索引重写为：业务流程图、概念解释、状态流转、风险评估、集成关系。这一步让 BCL 从「代码索引」升级为「业务知识库」。

## 为什么不同于现有工具

| 方案 | 产出 | 业务价值 |
| --- | --- | --- |
| 代码搜索 (grep/IDE) | 原始匹配结果 | 零——仍需人工解读 |
| AST 文档生成器 (JavaDoc/Sphinx) | API 签名 | 低——没有业务语义 |
| AI「解释这段代码」 | 单文件摘要 | 中等——无跨域理解 |
| **code2wiki** | **按域组织的 BCL：流程图 + 风险 + 集成关系** | **高——LLM 可推理业务影响** |

## 支持的技术栈

| 语言 | 框架与生态 |
| --- | --- |
| **Java** | Spring Boot, MyBatis, Dubbo, Feign, RocketMQ, XxlJob, Kafka |
| **Kotlin** | Spring Boot, Ktor (routing DSL), Exposed, Coroutines |
| **Python** | Django (CBV+FBV), FastAPI, Flask, SQLAlchemy, Celery, APScheduler |
| **Go** | Gin, Echo, gRPC, GORM, sqlc, robfig/cron, NATS |
| **TypeScript/JS** | NestJS, Express, TypeORM, Prisma, BullMQ, node-cron |

自动识别语言（基于构建文件 + 源码后缀），混合语言 Monorepo 并行扫描 + 智能合并。

## 适用场景

- **新人 Onboarding**：2 天内理解业务全貌，不再靠口口相传
- **AI 需求开发**：给 LLM 精准的业务上下文，减少幻觉和返工
- **技术债评估**：通过风险清单和调用链快速定位高危区域
- **代码审查**：了解改动涉及的域间依赖和下游影响
- **微服务治理**：跨服务调用链梳理、MQ Topic 全景图

## 质量保障

扫描器本身经过严格测试：212 个单元测试、80% 行覆盖率、6 个 fixture 项目（Java/Python/Go/Kotlin/TypeScript/混合 Monorepo）逐字节 golden snapshot 对比。

生成的 BCL 内置质量验证协议：API 反查盲测（≥67% 准确率）、结构完整性检查、端到端需求模拟。

## 命令参考

```bash
python3 scripts/analyze_project.py /path/to/project --output ./output    # 基本用法
python3 scripts/analyze_project.py /path/to/project --language python     # 指定语言
python3 scripts/analyze_project.py /path/to/project --top-domains 40      # 更多候选域
python3 scripts/analyze_project.py /path/to/project --no-merge            # 禁用域聚合
python3 scripts/analyze_project.py /path/to/project --force               # 强制覆盖
python3 scripts/analyze_project.py /path/to/project --no-git              # 跳过 Git 分析
python3 scripts/analyze_project.py /path/to/project --plugin-only typescript  # 单插件模式
```

## 扩展

新增一门语言只需 ~200 行代码。完整指南见 [`docs/07-how-to-extend.md`](docs/07-how-to-extend.md)。

## 许可证

MIT
