---
name: code2wiki
description: 为大型后端项目生成和维护面向业务的 Business Context Layer（业务语义层 / 项目知识地图）。当需要总结、梳理、文档化、wiki 化、构建上下文、创建领域 skill、提升 LLM 对既有后端代码库的理解时使用——尤其适用于 10w+ 行、50w+ 行这类需求主要由业务驱动而不是技术模块驱动的系统。支持 Java/Spring、Kotlin（Spring/Ktor）、Python（Django/FastAPI/Flask）、Go（Gin/Echo/gRPC）、TypeScript/JavaScript（NestJS/Express）等多种后端栈；扫描器自动识别项目语言，混合语言 Monorepo 会并行扫描所有命中插件。也适用于多级业务域目录、项目知识地图、API/Database/Code Entrypoint 映射、风险清单、分层上下文（L0/L1/L2/Source）建设等任务。
---

# code2wiki

## 使命

为后端项目构建完整的 Business Context Layer（BCL，业务语义层 / 业务上下文层），让后续 LLM 做需求开发时，先理解**业务域、业务流程、核心概念和风险点**，再进入具体代码。

**核心原则**：扫描器做骨架索引，AI 做业务理解。最终交付物必须包含人能读懂的业务解释，而不仅仅是代码索引表格。

## 术语对照（多语言）

下文出现的角色性术语在不同语言里有不同的写法，本 skill 不绑定任何单一语言：

| 通用角色 | Java / Kotlin (Spring) | Kotlin (Ktor) | Python (Django/FastAPI/Flask) | Go (Gin/Echo) | TypeScript (NestJS/Express) |
| --- | --- | --- | --- | --- | --- |
| HTTP 入口 | `@RestController` | Routing DSL | View / Resource / Router function | Handler | `@Controller` / Route handler |
| 业务编排 | `@Service` / Manager | `class XxxService` | Service / UseCase / 模块函数 | Service / UseCase | Service / Provider |
| 数据访问 | `@Repository` / Mapper | DAO 类 | Repository / Manager / ORM Query | Repository / sqlc / GORM | Repository / Prisma client |
| 异步消费 | `@RocketMQMessageListener` / `@KafkaListener` | Kafka/Rabbit consumer | Celery task / RQ worker | Kafka/NATS consumer | BullMQ worker / Kafka consumer |
| 定时任务 | `@Scheduled` / XxlJob | k8s CronJob / quartz | Celery beat / APScheduler / `manage.py` cmd | `robfig/cron` | `node-cron` / agenda |
| RPC | Dubbo / Feign / gRPC | Ktor client | gRPC / `httpx` | gRPC | gRPC / tRPC |
| 事务 | `@Transactional` | Exposed transaction | `@transaction.atomic` / session.begin | `db.Begin()` | `prisma.$transaction` / TypeORM transaction |
| 数据载荷 | DTO / Entity | data class | Pydantic / dataclass / Django Model | struct | DTO class / interface |
| 状态枚举 | `enum` | `enum class` | `enum.Enum` / `TextChoices` | iota 常量 | `enum` / 常量联合类型 |

当 SKILL 中出现 "Controller / Service / Consumer / DTO" 等术语时，统一替换为目标项目实际使用的对应物。

## 两阶段执行流程

### Phase 1：扫描器生成骨架

1. 确认目标项目路径和输出目录。
2. 运行扫描器（默认自动识别语言）：

```bash
python3 scripts/analyze_project.py /path/to/project --output /path/to/output --top-domains 40
```

显式指定语言（当自动识别误判或想限定单一语言时）：

```bash
python3 scripts/analyze_project.py /path/to/project --language python --output /path/to/output
```

3. 扫描器会自动产出：
   - 目录骨架、`inventory.json`、`generation_report.md`
   - `00_project_overview.md`：技术栈、规模数字、候选业务域
   - 每个域目录下的 `skill.md`/`workflows.md`/`concepts.md`/`api_map.md`/`db_map.md`/`code_entrypoints.md`/`integration_map.md`/`risk_points.md`/`examples.md`/`call_chains.md`
   - `02_cross_cutting/`：MQ、定时任务、缓存、事务、并发、认证、RPC、可观测性
   - `03_development_playbooks/`、`04_glossary/`、`05_indexes/`、`06_auxiliary_knowledge/`
4. **域聚合**：扫描器自动将碎片域按前缀合并（如 `employee-active-check` + `employee-medal` + `employee-logic` → 统一到 `employee`），合并日志记录在 `domain_merge_log.md`。聚合策略不一定 100% 准确，富化前先扫一眼这个 log，发现错误合并就用 `--no-merge` 重跑或事后手工拆分。
5. **调用链生成**：每个域自动生成 `call_chains.md`（入口→编排→外部调用的静态调用关系），全局生成 `05_indexes/call_graph.md`。静态分析对动态调用、反射、注入回调无能为力——遇到这类调用要回源码确认。
6. **增量保护**：如果输出目录已有 AI 富化过的文件（标记 `<!-- AI-ENRICHED -->`），scanner 会**跳过**这些文件。用 `--force` 强制覆盖。
7. **Git 历史分析**：自动分析 git log（最近 90 天），产出 `05_indexes/git_activity.md`（热点文件 Top 30、域活跃度排行、活跃贡献者、commit 消息业务关键词）。这些信号帮助判断哪些域是近期开发重点、哪些文件改动最频繁需要优先富化。用 `--no-git` 禁用（CI 环境或浅克隆仓库）。
8. 这些产出是**代码级索引**——有文件路径、类名、方法签名、调用链、风险信号、git 活跃度，但**没有业务语义**。

#### 多语言 Monorepo

- 不传 `--language` 时，扫描器扫描根目录的构建文件（`pom.xml`/`build.gradle*`/`pyproject.toml`/`requirements.txt`/`go.mod`/`package.json` 等）和源码扩展名，**并行**运行所有命中插件。
- 多语言合并产出会出现在同一份 `02_cross_cutting/*.md` 里，按 `## <Language>` 分节。
- Debug 时可以用 `--plugin-only typescript` 锁定单插件。
- 如果 Monorepo 内子项目相互独立，**建议拆开扫描**，每个子项目一个 BCL 输出目录，再在 `00_project_overview.md` 手工加交叉引用。

### Phase 2：AI 富化（关键阶段）

扫描器完成后，**必须**对核心业务域执行 AI 富化。这是让 BCL 从"代码索引"变成"业务知识库"的关键。

#### 富化范围 & 优先级打分

按以下信号给每个候选域打分（先看 `05_indexes/business_domain_map.md` + `05_indexes/git_activity.md`），通常富化前 5-15 个域：

| 信号 | 来源 | 权重含义 |
| --- | --- | --- |
| 文件数 ≥ 10 | `00_project_overview.md` 候选域表 | 域规模够大，值得文档 |
| 近 90 天 commit ≥ 20 | `05_indexes/git_activity.md` 域活跃度榜 | 近期改动多 = 最需要文档 |
| 含 git 热点 Top 30 文件 | `05_indexes/git_activity.md` 热点文件榜 | 高频改动文件 = 业务核心 |
| 含入口 + 编排 + 异步消费的完整链路 | `<domain>/code_entrypoints.md` | 流程完整，富化产出价值高 |
| 包含风险信号（事务/并发/缓存） | `<domain>/risk_points.md` | 易出 bug，文档收益高 |

打分 ≥ 3 项满足的域优先富化。打分 < 2 项的域跳过，保留 scanner 索引即可。

#### 富化步骤（对每个选中的域执行）

**Step 0：标记文件为 AI 富化**

在每个要重写的文件**顶部第一行**写入标记（替换 scanner 标记）：

```
<!-- AI-ENRICHED -->
```

这样下次重跑 scanner 时不会覆盖你的工作。

**Step A：读调用链，建立流程骨架**

先读该域的 `call_chains.md`，**这是富化效率最高的入口**——它已经把入口→编排→外部调用的静态链路画出来了。读法：

1. 找出域里所有入口（HTTP/MQ/Cron）：每个入口都是一个"业务流程"的起点。
2. 顺着调用边一路展开 1-2 层，把"哪些入口共享同一段下游编排"识别出来——这些往往是一个领域里的核心 Use Case。
3. 圈出跨域调用边（指向其它域的 Service/RPC/MQ Topic）：这些就是 `integration_map.md` 要写的上下游关系。
4. 圈出"事务/锁/缓存"出现的位置：这些是 `risk_points.md` 要写的风险。

确定要读的源文件清单后，**只读 5-10 个核心文件**，不要试图读完整个域：

- 入口（Controller/View/Router/Handler）：理解 API 路径、请求参数、响应结构
- 主编排（Service/UseCase/Manager）：理解核心业务逻辑、规则、异常路径
- 异步消费（MQ Consumer / Celery task / BullMQ worker）：理解触发条件、幂等策略
- 关键数据载荷（Entity/DTO/Model/struct）：理解字段业务含义
- 状态枚举（enum / TextChoices / iota 常量）：理解状态定义和流转

阅读策略：用 grep/rg 搜 `throw`/`raise`/`return *Error`/`status`/`@Transactional`/`@transaction.atomic`/`db.Begin` 等关键词跳读，不要逐行通读。

**Step B：重写 skill.md — 域级摘要入口**

skill.md 是域的 L1 入口，**总长不超过 60 行**。固定结构：

1. `## 概述`（2-3 句业务描述，**非技术人员能看懂**）
2. `## 核心流程概览`（每个流程一句话 + 指向 `workflows.md` 的引用，3-7 个）
3. `## 关键业务规则`（3-5 条规则的表格：规则 / 说明 / 代码位置）
4. `## 风险提示`（3-5 条：事务/并发/缓存/幂等/外部依赖）
5. 保留 scanner 生成的索引信息（API 入口数、文件统计等），不要全部删光

**详细内容放到对应的 L2 文件中（workflows / concepts / risk_points / integration_map），不要全塞进 skill.md。**

**Step C：重写 workflows.md — 业务流程详细图**

这是流程的主阵地，**必须替换掉 scanner 的方法签名表格**。每个核心流程用箭头/缩进步骤图描述：

```markdown
## 下单流程

用户提交订单 → POST /orders（入口：OrderController.createOrder / orders.create_order / OrderHandler.Create）
    ↓
订单编排层
    ├── 校验库存（RPC: InventoryService.reserve / inventory_client.reserve）
    ├── 扣减积分（事务保护，与本地订单写入同一事务）
    └── 发送异步消息（topic=ORDER_CREATED，触发 fulfillment 域）
```

每个流程必须标注：**触发方式 / 关键类或函数 / 数据变更点 / 异步副作用 / 失败回滚策略**。

**Step D：重写 concepts.md — 业务含义 + 状态流转**

**替换掉 scanner 的 DTO 字段列表**，改为业务概念表 + 状态流转图：

```markdown
## 核心概念

| 概念 | 代码实体 | 业务含义 |
|------|----------|----------|
| 订单 | Order (entity / Pydantic model / Go struct) | 用户一次购买行为 |
| 订单项 | OrderItem | 订单中的单个商品行 |

## 状态流转

CREATED(待支付) → PAID(已支付) → SHIPPED(已发货) → DELIVERED(已收货)
                                      ↘ REFUNDED(已退款，可从 PAID/SHIPPED 进入)

终态：DELIVERED / CANCELLED / REFUNDED（不可逆）
```

每个状态必须标注：业务含义、能从哪些状态进入、可以触发哪些动作、终态标记。

**Step E：补充 integration_map.md — 上下游交互**

**在 scanner 表格之前插入"上游 / 下游 / 共享存储"三段**：

```markdown
## 上游系统（谁会调用本域）
| 系统 | 交互方式 | 触发场景 |

## 下游系统（本域会调用谁）
| 系统 | 交互方式（HTTP/RPC/MQ） | 用途 |

## 共享存储（本域读写的数据库/缓存/对象存储）
| 存储 | 表/Key | 读 / 写 / 双向 |
```

**Step F：补充业务规则到 skill.md**

从代码的 if / switch / 校验逻辑 / 异常抛出中提取规则：

```markdown
## 关键业务规则
| 规则 | 说明 | 代码位置 |
| 同一用户每天最多下 10 单 | 防刷限制 | OrderService.checkDailyLimit:42 |
| 退款必须在签收 7 天内 | 售后窗口 | RefundService.validateWindow:88 |
```

**Step G：风险点提取**

写入 `risk_points.md`：

- 事务边界：哪些方法被 `@Transactional` / `@transaction.atomic` / `tx.Begin` 包裹，事务粒度是否过大、有没有 RPC/IO 在事务内
- 并发风险：是否有共享状态、是否用了分布式锁、有没有 race condition
- 缓存一致性：是否有先写库再更新缓存（或反过来）的双写问题
- 幂等性：MQ Consumer / 退款 / 支付回调是否做了幂等
- 外部依赖故障：下游服务挂掉 / 超时 / 限流时的降级路径

#### 富化完成标准（Per-Domain Checklist）

每个被富化的域必须满足：

- [ ] 所有被重写的文件顶部有 `<!-- AI-ENRICHED -->` 标记
- [ ] `skill.md` ≤ 60 行，有业务概述 + 规则 + 风险（摘要入口）
- [ ] `workflows.md` 至少 1 个箭头/步骤图流程（替换方法签名表格）
- [ ] `concepts.md` 核心概念有业务含义（替换 DTO 字段列表）
- [ ] 状态枚举有流转图（放 `concepts.md` 或 `04_glossary/status_codes.md`）
- [ ] `integration_map.md` 有上下游系统说明（不只是 scanner 的 RPC 引用表）
- [ ] `risk_points.md` 至少 3 条具体风险（带代码位置，不是空话）

#### 何时停止富化

满足任一条件即可停止：

- 已富化域累计覆盖 ≥ 80% 的 git 活跃度（看 `git_activity.md` 域活跃度榜）
- 已富化域累计覆盖 ≥ 70% 的 API（看 `05_indexes/api_index.md`）
- 已富化 10-15 个域，且 Phase 3 验证全部通过

剩余域**保留 scanner 索引即可**，作为 L1/L2 框架，等下次需求开发触达时再按需富化（参考"Post-Dev 工作流"）。

### Phase 3：质量自验证

完成 Phase 2 后，**必须**做以下验证（不能跳过）：

**验证 1：API 反查测试（盲测）**

从 `05_indexes/api_index.md` 中随机选 3 个 API 路径，**只看 BCL 文档不看源码**，尝试回答：

1. 这个 API 属于哪个业务域？
2. 这个 API 做了什么业务操作？（用 1-2 句业务语言描述，不要复述函数名）
3. 修改这个 API 可能影响哪些下游？（MQ Topic / 下游服务 / 数据库表）

然后打开源码验证答案。每个 API 评分：
- 全对 = 1 分
- 部分对（域对了，但业务/下游答错或模糊）= 0.5 分
- 错误或答不上来 = 0 分

3 个 API 总分 ≥ 2.0 通过；< 2.0 说明该域 BCL 质量不够，**回到 Phase 2 继续富化**该域。

**验证 2：结构检查**

- [ ] 每个富化域的 `skill.md` 顶部有 `<!-- AI-ENRICHED -->` 标记
- [ ] 每个富化域有 2-3 句非技术人员能看懂的业务概述
- [ ] `workflows.md` 至少 1 个箭头流程图
- [ ] `02_cross_cutting/mq.md` 有项目特定的 MQ 架构说明（如 Topic 命名约定、消息格式、重试策略）
- [ ] `04_glossary/business_terms.md` 有 5+ 个业务术语 → 代码入口映射

**验证 3：需求模拟（端到端）**

用一个假想的需求（如"给 XX 功能新增一个状态 SUSPENDED"）走一遍 BCL 的定位流程：

1. 用 `03_development_playbooks/locate_business_domain.md` 找到域
2. 读该域 `skill.md` 了解业务背景
3. 读 `concepts.md` 状态流转图，判断 SUSPENDED 应插入哪里
4. 读 `call_chains.md` 找出所有要改的入口和编排函数
5. 读 `risk_points.md` 评估事务/并发/MQ 兼容性影响

如果上面任一步走不通，说明对应文件富化不够。

**最终输出**

完成 Phase 3 后，回复中说明：
- 输出目录路径
- 已富化的域列表（标注每个域的优先级打分）
- 未富化的域（标注原因：规模小 / 不活跃 / 暂不需要）
- 验证 1/2/3 的结果
- 下一步建议（哪些域可以延后富化、哪些 cross-cutting 文件需要补强）

***

## 需求开发后的 BCL 维护（Post-Dev 工作流）

每次完成需求开发后，应更新 BCL 以保持知识库的准确性：

### 快速更新（每次需求后 2 分钟）

1. 找到涉及的业务域目录 `01_business_domains/<domain>/`
2. 在 `examples.md` 末尾追加本次需求记录：

```markdown
### YYYY-MM-DD: <需求标题>
- **变更内容**：<简述做了什么>
- **修改文件**：<列出改动的核心文件>
- **新增/变更的 API**：<如有>
- **新增/变更的 MQ Topic / 定时任务**：<如有>
- **风险发现**：<开发中发现的新风险>
```

3. 如果改变了流程或新增了状态，更新 `workflows.md` 和 `concepts.md` 的状态流转图。
4. 如果新增了 API / 数据表 / MQ Topic / 定时任务，更新对应的 `*_map.md`。
5. 如果涉及跨域调用，更新源/目标域的 `integration_map.md`。

### 定期刷新（每月或大版本后）

重跑 scanner 刷新索引（AI 富化内容受增量保护不会丢失）：

```bash
python3 scripts/analyze_project.py /path/to/project --output /path/to/bcl
```

### Git 集成建议

在项目 `CLAUDE.md` 中加入提醒：

```markdown
完成需求开发后，如果涉及核心业务流程变更，请更新 BCL：
- 更新 .code2wiki/business-context-layer/01_business_domains/<域>/examples.md
- 必要时更新 workflows.md / concepts.md / integration_map.md
```

***

## 多项目 / 微服务场景

当一个系统由多个微服务组成（如 `order-service` + `payment-service` + `inventory-service`）：

### 独立生成 + 交叉引用

1. 为每个项目独立生成 BCL：

```bash
python3 scripts/analyze_project.py /path/to/order   --output /output/order-bcl
python3 scripts/analyze_project.py /path/to/payment --output /output/payment-bcl
```

2. 在每个 BCL 的 `00_project_overview.md` 中手动添加关联项目说明：

```markdown
## 关联项目

| 项目 | 关系 | BCL 位置 |
|------|------|----------|
| payment-service   | 下游，本项目通过 RPC 调用 | ../payment-bcl/ |
| inventory-service | 上游，库存变更 MQ 通知本项目 | ../inventory-bcl/ |
```

### RPC 接口对照

扫描器会自动检测项目使用的 RPC 框架并生成对应的 cross-cutting 文件：

- **Java/Kotlin + Dubbo**：生成 `02_cross_cutting/dubbo_rpc.md`，列出所有 `@DubboReference` 引用的服务。跨项目对照时，从消费方的 `dubbo_rpc.md`，对照提供方的 `@DubboService`，建立接口映射。
- **Java/Kotlin + Feign + 注册中心**：生成 `02_cross_cutting/feign_rpc.md`，列出所有 `@FeignClient` 定义的远程服务名、路径前缀、接口方法。跨项目对照时，从调用方的 `feign_rpc.md` 服务名，对照目标服务的 HTTP API。
- **Go / TypeScript / Python + gRPC**：生成 `02_cross_cutting/rpc_grpc.md`，列出本项目实现的 `*Server` 接口及客户端使用的桩。跨项目对照时按 service 名称对齐。
- **HTTP 直连（Python `httpx`、Go `http.Client`、TS `axios/fetch`）**：scanner 会列出在源码中出现的 base URL/host，但不识别远程服务身份，需要 AI 富化时手工归类到 `integration_map.md`。
- 多种框架可共存（如部分模块走 Dubbo、部分走 Feign），scanner 会同时生成对应文件。
- 各语言识别细节见 `references/discovery/<lang>.md`。

### MQ Topic 对照

从一个项目的 `02_cross_cutting/mq.md` 的 Producer 列表，对照其它项目的 Consumer 列表，建立消息流向全景图。建议在某个"主"项目（通常是订单/工作流主流程所在服务）的 `00_project_overview.md` 维护一张全局 Topic→Producer→Consumer 矩阵图。

## 命令参考

```bash
# 基本用法（语言自动检测）
python3 scripts/analyze_project.py /path/to/project --output /path/to/output

# 显式指定语言（auto/java/python/go/kotlin/typescript）
python3 scripts/analyze_project.py /path/to/project --language python

# 增加候选域数量（默认 30，大型项目可调到 40-60）
python3 scripts/analyze_project.py /path/to/project --top-domains 40

# 禁用域聚合（怀疑误合并时调试用）
python3 scripts/analyze_project.py /path/to/project --no-merge

# 强制覆盖 AI 富化过的文件（慎用，会丢失已富化内容）
python3 scripts/analyze_project.py /path/to/project --force

# 跳过 git 历史分析（CI 环境或浅克隆仓库）
python3 scripts/analyze_project.py /path/to/project --no-git

# 混合语言项目里只跑指定插件（debug）
python3 scripts/analyze_project.py /path/to/monorepo --plugin-only typescript

# verbose 模式打印插件 trace
python3 scripts/analyze_project.py /path/to/project -v

# 默认输出（不指定 --output 时）
<project>/.code2wiki/business-context-layer
```

## 输出目录结构

```text
business-context-layer/
  SKILL.md                              # AI 使用本 BCL 的操作手册
  00_project_overview.md                # 技术栈、关键数字、候选业务域
  01_business_domains/
    <domain>/
      skill.md                          # ★ L1 域入口：业务概述 + 代码索引
      concepts.md                       # 核心概念 + 业务含义 + 状态流转
      workflows.md                      # 业务流程图（箭头/步骤描述）
      api_map.md                        # API 路径 → 业务用途
      db_map.md                         # 数据模型 + 字段含义
      code_entrypoints.md               # 全部文件按角色索引
      integration_map.md                # 上下游系统 + MQ/RPC 交互
      risk_points.md                    # 事务/并发/缓存/幂等风险
      examples.md                       # 常见变更指南 + 历史需求记录
      call_chains.md                    # ★ 静态调用链（AI 画流程图用）
  02_cross_cutting/
    mq.md                               # MQ 架构说明 + Consumer/Producer 清单
    scheduler.md                        # 定时任务清单 + 说明
    cache.md                            # 缓存类清单
    transaction.md                      # 事务边界使用分布
    concurrency.md                      # 锁/并发使用分布
    auth.md                             # 认证/权限
    dubbo_rpc.md                        # Dubbo RPC 清单（检测到 Dubbo 时生成）
    feign_rpc.md                        # Feign + 注册中心清单（检测到 Feign 时生成）
    rpc_grpc.md                         # gRPC 清单（Go/TS/Python 项目）
    observability.md
  03_development_playbooks/
    locate_business_domain.md
    modify_existing_flow.md
    add_new_api.md
    add_db_field.md
    add_mq_consumer.md
    troubleshoot_bug.md
  04_glossary/
    business_terms.md                   # 业务术语 → 代码入口
    status_codes.md                     # 状态码/枚举 → 含义 → 流转
    error_codes.md
  05_indexes/
    api_index.md
    database_index.md
    code_entrypoint_index.md
    business_domain_map.md
    dependency_index.md
    git_activity.md                     # ★ Git 热点文件、域活跃度、贡献者、commit 关键词
    call_graph.md                       # ★ 全局调用关系图
  06_auxiliary_knowledge/
    auxiliary_knowledge.md
  inventory.json
  generation_report.md
  domain_merge_log.md                   # 域聚合日志
```

## 业务优先规则

- **按业务能力组织目录**，不按 Controller/Service/Repository 这类技术分层组织。
- **主结论必须来自目标项目自身**的源码、配置、构建文件、测试、SQL、Mapper XML、README/docs 等一手材料。
- 如果存在 `.claude/skills`、`.cursor/rules`、`.agents` 等外挂人工知识库，可以作为可选增强信号单独汇总到 `06_auxiliary_knowledge/auxiliary_knowledge.md`；但不能让 BCL 依赖它们才能工作。
- **优先使用产品、运营、客服、业务专家会使用的名称**（而不是开发的内部代号或英文缩写）。
- 不确定的内容必须显式标注 `需要确认`，**不要编造业务事实**。
- 所有生成文档都要服务于后续编码，**必须包含精确文件路径和类/函数名**。

## AI 富化时的代码阅读策略

- 每个域只读核心文件（入口 + 主编排 + 关键异步消费），不要试图读完所有文件。
- 从入口的路由路径和方法名推断业务用途。
- 从主编排的方法体中提取业务规则（if/switch/校验/异常抛出）。
- 从异步消费的处理逻辑推断异步副作用和触发条件。
- 从枚举/常量定义推断状态流转。
- 优先用 `grep` / `rg` 搜索关键词，不要逐行通读源码：
  - 事务：`@Transactional` / `@transaction.atomic` / `tx.Begin` / `prisma.$transaction`
  - 状态变更：`status =` / `setStatus(` / `state =`
  - 异常：`throw new` / `raise ` / `return *Error` / `panic(`
  - 锁：`@Lock` / `synchronized` / `Lock.acquire` / `sync.Mutex` / `Redisson`
  - 缓存：`@Cacheable` / `redis.get` / `cache.set`

## 分层上下文（L0 / L1 / L2 / Source）

BCL 把项目知识切成四层，让 LLM 按需求加载，不必一次性塞满 context window：

- **L0（全局门面）**：`00_project_overview.md`、`04_glossary/*`、`05_indexes/*`
  → 回答"项目是干啥的 / 有哪些业务域 / 整体架构长什么样"
- **L1（域入口）**：`01_business_domains/<domain>/skill.md`
  → 回答"这个域是干啥的 / 有哪些主流程 / 关键规则和风险是什么"
- **L2（域细节）**：`workflows.md` / `concepts.md` / `api_map.md` / `db_map.md` / `integration_map.md` / `risk_points.md` / `examples.md` / `call_chains.md`
  → 回答"具体流程怎么走 / 状态怎么流转 / 上下游有谁 / 改动有什么风险"
- **Source**：L2 指向的真实源码文件
  → 实际编码和精确逻辑确认

需求开发的标准路径：L0 → 定位到域 → L1 → 读相关 L2 → 钻进 Source。

## 参考资料

仅在需要时读取：

- `references/context-model.md`：BCL 的语义模型和各类文件职责
- `references/discovery/_common.md`：跨语言通用的域/角色识别规则
- `references/discovery/java.md`：Java/Spring 项目发现规则
- `references/discovery/kotlin.md`：Kotlin (Spring/Ktor) 发现规则
- `references/discovery/python.md`：Python (Django/FastAPI/Flask) 发现规则
- `references/discovery/go.md`：Go (Gin/Echo/gRPC/GORM) 发现规则
- `references/discovery/typescript.md`：TypeScript/JavaScript (NestJS/Express) 发现规则
- `references/quality-gates.md`：完整性、可用性和稳定性校验
- `references/update-playbook.md`：未来需求开发后如何维护 BCL

## 模板

- `assets/templates/domain_skill.md`：域 skill 文件模板
- `assets/templates/domain_workflows.md`：域 workflow 文件模板
- `assets/templates/enriched_domain.md`：AI 富化后的域文档示例
