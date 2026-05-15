# 项目改造文档

本目录记录了 code2wiki 从「Java-only 单体扫描器」升级到「多语言插件式架构」的完整过程。

## 阅读顺序

按时间线 / 依赖关系排列，从最高层到细节：

| 文档 | 内容 | 适合 |
| --- | --- | --- |
| [01-overview.md](./01-overview.md) | 项目背景、改造前后对比、最终成果一览 | 新人快速理解 |
| [02-architecture.md](./02-architecture.md) | 新架构详解：插件系统、core/* 分层、CrossCutting Registry | 想理解代码结构 |
| [03-phase-by-phase.md](./03-phase-by-phase.md) | 6 个 Phase 的实施细节、每个 Phase 的产出与验收 | 想复盘整个过程 |
| [04-tech-debt-cleanup.md](./04-tech-debt-cleanup.md) | 4 项技术债的根因、修复方案、影响 | 想了解每个改动的「为什么」 |
| [05-testing-strategy.md](./05-testing-strategy.md) | Golden snapshot 框架、6 fixture 设计、覆盖率策略 | 想加新语言/新测试 |
| [06-code-review-findings.md](./06-code-review-findings.md) | 全周期 5 次 code-review 累计 ~20 个 finding 的修复记录 | 想避免相同坑 |
| [07-how-to-extend.md](./07-how-to-extend.md) | 如何添加新语言插件、新 cross-cutting 类型、新 extras key | 想做扩展开发 |

## 一句话总结

把 2363 行的 Java 单体扫描器拆成插件式多语言架构（Java/Python/Go/Kotlin/TypeScript），同步清理 4 项技术债，通过 6 个分阶段交付 + 严格的 byte-identical 闸门保证零回归，最终 212 测试全绿、80% 覆盖率达标、混合语言 Monorepo 真正可用。
