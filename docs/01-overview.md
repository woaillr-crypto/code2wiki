# 改造总览

## 背景

code2wiki 是一个为大型后端代码库自动生成「业务上下文层」（Business Context Layer）的扫描器。让 LLM 在做需求开发前，先理解业务域、入口、数据模型、风险点，再进入具体代码。

改造前的状态：

- **仅支持 Java/Spring**：扫描器是一个 2363 行的单体脚本 `scripts/analyze_java_project.py`，硬编码 Spring/MyBatis/Dubbo/Feign/RocketMQ/XxlJob 全套 Java 生态特征
- **架构无扩展性**：想加 Python/Go 支持 = 复制整套脚本重写
- **混合语言 Monorepo 几乎不可用**：scanner 假设单一语言

## 改造目标

| 目标 | 说明 |
| --- | --- |
| **多语言支持** | Java + Python + Go + Kotlin + TypeScript 五种主流后端语言 |
| **插件式架构** | 添加新语言 = 写一个 `language_<lang>.py`，不动核心 |
| **混合项目** | Java + TS Monorepo 一键扫描，cross-cutting 文件自动合并 |
| **零回归** | 既有 Java 项目输出 byte-identical（每个 phase 严格闸门） |
| **技术债清零** | 4 项历史问题（详见 `04-tech-debt-cleanup.md`）全部解决 |

## 改造前后对比

### 代码规模

| 模块 | 改造前 | 改造后 |
| --- | --- | --- |
| `analyze_java_project.py` | **2363 行单体** | **106 行 deprecation shim** |
| 多语言插件 | 不存在 | 5 个独立 plugin，总计 ~2300 行 |
| 共享 core 层 | 不存在 | 9 个模块，总计 ~1140 行 |
| 测试套件 | 极少 | **212 个测试**，覆盖率 80% |
| Fixture 项目 | 0 | 6 个（5 单语言 + 1 mixed Monorepo） |

### 功能对比

| 能力 | 改造前 | 改造后 |
| --- | --- | --- |
| 支持语言 | Java | Java / Python / Go / Kotlin / TypeScript |
| 自动检测语言 | ❌ | ✅（基于 build manifest + 文件后缀） |
| 混合项目 | ❌（第二个 plugin 覆盖第一个的 cross-cutting） | ✅（自动合并为 `## Java` + `## TypeScript` 双段） |
| Ktor routing DSL | ❌ | ✅（嵌套 route 拼接、字符串/注释跳过、深度限制） |
| Prisma schema | ❌ | ✅（model + @@map + fields 解析） |
| Django CBV | ❌（误识别为 service） | ✅（识别 30+ 个 DRF/Django view 基类） |
| Spring 数组形 path | ❌（漏字段） | ✅（`path = ["/x", "/y"]` / `arrayOf(...)`） |
| Java 旧脚本 | 主入口 | 带 `[DEPRECATED]` 提示的 shim |
| 新 CLI 入口 | 不存在 | `scripts/analyze_project.py`（auto-detect） |

### 输出对比（mixed fixture 的 mq.md）

**改造前**（bug：TS 覆盖了 Java）：

```markdown
# 队列消费 (BullMQ)

| 类 | 队列/Job | 业务域 | 文件 |
| --- | --- | --- | --- |
| CartProcessor | cart.checkout | cart | frontend-ts/src/cart/cart.processor.ts |
```

Java 的 RocketMQ Consumer 信息**完全丢失**。

**改造后**（正确合并）：

```markdown
# MQ 消息队列

## Java (RocketMQ / Feign)

### 本项目的 MQ 实现方式

本项目使用 **RocketMQ** 作为消息中间件。

### Consumer 清单

| 业务域 | Consumer 类 | 说明 | 文件 |
| --- | --- | --- | --- |
| cart | CartCheckoutConsumer | - | backend-java/src/main/java/com/example/shop/cart/CartCheckoutConsumer.java |

## TypeScript (NestJS / BullMQ / TypeORM)

| 类 | 队列/Job | 业务域 | 文件 |
| --- | --- | --- | --- |
| CartProcessor | cart.checkout | cart | frontend-ts/src/cart/cart.processor.ts |
```

Java 的 `##` 子标题自动降级为 `###` 嵌入到 Java section 下，文档层级保持合理。

## 最终交付清单

### 新增的代码

- `scripts/analyze_project.py` — 新 CLI 入口（auto-detect 语言）
- `scripts/code2wiki/` — 整个包结构
  - `core/io.py / markdown.py / domain.py / git.py / writers.py / models.py` — 共享逻辑
  - `core/cross_cutting.py` — 跨语言合并的 registry
  - `core/detect.py / registry.py` — 插件发现 + 语言识别
  - `cli.py` — 编排
  - `plugins/base.py` — LanguageScanner 协议
  - `plugins/language_{java,python,go,kotlin,typescript}.py` — 5 语言插件
  - `tests/` — 212 个测试 + 6 fixture + golden snapshots
  - `CHANGELOG.md` — 0.4.0 发布说明

### 修改的代码

- `scripts/analyze_java_project.py` — 2363 行 → 106 行 deprecation shim
- `SKILL.md` — 支持的语言段、命令更新
- `references/context-model.md` — 跨语言合并规则
- `references/discovery/java.md`（迁移自 `java-discovery.md`）+ 4 个新增 discovery 文档
- `references/quality-gates.md` — 语言中立化

### 验收成绩

- **212 个测试通过**
- **80% 代码行覆盖率**
- **6 个 fixture × snapshot 全 byte-identical**
- **5 次 code-review × ~20 个 finding × 全部修复**

## 后续可演进点（已主动留白）

- `core/git.py` 的 8 行未覆盖路径需要更细的 git 状态测试
- `plugins/language_java.py` 还有 165 行未覆盖（Spring 罕见 dispatch 路径）
- Kotlin Spring 与 Ktor 共存的混合项目（当前要求二选一）
- Rust / C# / PHP 等新语言（已为插件式架构铺好路）
