# 4 项技术债清理

这次改造的**真正核心**是清掉 4 项历史技术债。每一项都有明确的根因、影响范围和修复方案。

## 技术债 #1：`core/*` 是 re-export 转发壳

### 根因

上一期改造采用「适配器策略」快速落地多语言架构：
- `core/io.py` 等模块只是 `from analyze_java_project import ...` 的转发
- 老 2363 行单体脚本不动，保 byte-identical
- 新 plugin 通过 `from core.io import write` 间接调用老代码

### 问题

| 维度 | 影响 |
| --- | --- |
| 认知断层 | 想改 `core/io.py:write()` 的人发现代码实际在 `analyze_java_project.py:1036` |
| 耦合风险 | 想给共享函数加新参数 → 必须改老脚本 → 破坏 byte-identical |
| 删除老脚本不可能 | 所有 core/* 依赖它，永远不能真正废弃 |
| 测试覆盖 | core/* 单测只能间接覆盖，无法独立测试 |

### 修复（Phase 3）

把 ~2000 行代码从老脚本搬到 7 个 core 模块 + plugin。每搬一个子模块跑全套 snapshot 测试。

```
迁移路径：
  analyze_java_project.py (2363 行)
    │
    ├─► core/io.py            (194)  IO + AI-ENRICHED 守卫
    ├─► core/markdown.py      (100)  md_table / role_label / 命名
    ├─► core/domain.py        (279)  域推断 + 合并
    ├─► core/git.py           (175)  Git 历史分析
    ├─► core/writers.py       (763)  generate_root_skill / generate_domain_docs / ...
    └─► plugins/language_java.py (1276)  Java extractors + analyze_java_file
                                          + generate_cross_cutting + _run_legacy_pipeline

老脚本最终：106 行 deprecation shim
```

### 验证

```bash
# 老脚本可运行（带 deprecation 提示）
python3 analyze_java_project.py /path/to/java --output /tmp/legacy
# [DEPRECATED] analyze_java_project.py is the legacy entry point.

# 新脚本产出完全一致
python3 analyze_project.py /path/to/java --output /tmp/new --language java
diff -r /tmp/legacy /tmp/new  # 0 差异
```

---

## 技术债 #2：Cross-cutting 五套代码并存

### 根因

每个 plugin 自己写 `02_cross_cutting/*.md` 文件：
- Java plugin → 直接 `write(output / "02_cross_cutting" / "mq.md", ...)`
- Python plugin → 自己内联 `_generate_python_cross_cutting`
- 同样 Go / Kotlin / TypeScript

### 问题：Monorepo 数据丢失

Java + TS 混合项目的扫描流程：
```
1. CLI 跑 Java plugin → 写 mq.md（含 RocketMQ Consumer）
2. CLI 跑 TS plugin   → 写 mq.md（含 BullMQ Consumer，覆盖 Java 的）
3. 最终 mq.md 只剩 TS 内容，Java 信息完全丢失！
```

**验证 bug**：mixed fixture 加入 Phase 0 时就暴露了这个问题——`golden/mixed/02_cross_cutting/mq.md` 只显示 TypeScript section，Java 的 CartCheckoutConsumer 消失。

### 修复（Phase 4）

**进程级 registry**：
- 每个 plugin 不再 `write(...)`，改为 `add_cross_cutting(name="mq", title="MQ 消息队列", body=...)`
- CLI 在所有 plugin 完成后调用 `emit_cross_cutting_files()` 统一发射

**合并规则**：
- **单 plugin 命中**：`# {title}\n\n{body}` 直接输出（byte-identical 保护）
- **多 plugin 命中**：`# {title}\n\n## {label1}\n\n{body1}\n\n## {label2}\n\n{body2}`
  - body 中所有 `##` 自动降级为 `###`（避免标题层级冲突）
  - plugin 排序按 `language` 字母序（Java < TypeScript）

### 修复后的 mq.md

```markdown
# MQ 消息队列                                    ← 单一 H1

## Java (RocketMQ / Feign)                      ← Java section
### 本项目的 MQ 实现方式                          ← 原 ## 降为 ###
本项目使用 **RocketMQ** 作为消息中间件。
### Consumer 清单
| 业务域 | Consumer 类 | ... |
| cart | CartCheckoutConsumer | ... |

## TypeScript (NestJS / BullMQ / TypeORM)        ← TS section
| 类 | 队列/Job | ... |
| CartProcessor | cart.checkout | ... |
```

### 验证

- 5 个单语言 fixture：byte-identical（registry 单 plugin 路径）
- mixed fixture：两段都在
- 17 个新单测覆盖：单/多贡献者、title 冲突警告、heading 降级、registry 隔离、目录创建

---

## 技术债 #3：`JavaFileInfo` 字段语义错位

### 根因

原 `JavaFileInfo` dataclass 有 23 个字段，其中 6 个是 Java 专属：
- `feign_clients` — Feign 是 Spring Cloud 的东西
- `feign_detail` — 同上
- `dubbo_refs` — Apache Dubbo
- `is_mq_producer` / `is_mq_consumer_custom` — RocketMQ 自定义模式
- `xxl_jobs` — 国产分布式任务调度框架

Phase 1 多语言改造时为了快速跑通，让 Python / Go / TS 插件**硬填这些字段为空**：

```python
# language_python.py（改造前）
info = JavaFileInfo(
    path=...,
    feign_clients=[],            # 假填
    dubbo_refs=[],               # 假填
    is_mq_producer=False,        # 假填
    is_mq_consumer_custom=bool(celery_tasks),  # 借用！
    xxl_jobs=[],                 # 假填
    feign_detail={},             # 假填
    ...
)
```

### 问题

- **inventory.json 显示 `dubbo_refs: 0`**：Python 项目永远是 0，纯噪音
- **Go 把 gRPC 服务塞进 `feign_detail["grpc_services"]`**：语义篡改
- **Python 用 `is_mq_consumer_custom=True` 标记 Celery 任务**：借用 RocketMQ 字段
- **新字段无处安放**：想给 Python 加 `celery_queues` 字段？要改 dataclass 影响所有 plugin

### 修复（Phase 2）

**新 `FileInfo` 通用 schema**：

```python
@dataclass
class FileInfo:
    path: str
    language: str = "unknown"          # 新增
    package: str | None = None
    class_name: str | None = None
    role: str = "support"
    domain: str = "unknown"
    mappings: list[str] = ...
    tables: list[str] = ...
    mq_listeners: list[str] = ...
    scheduled: list[str] = ...
    rpc_clients: list[str] = ...       # 改名自 feign_clients
    risk_signals: list[str] = ...
    fields / enum_values / public_methods / class_doc / implements_list / call_targets
    extras: dict[str, Any] = ...       # 新增：语言专属数据
```

**`EXTRAS_*` 标准 key 常量**：

```python
EXTRAS_DUBBO_REFS    = "dubbo_refs"     # Java
EXTRAS_FEIGN_DETAIL  = "feign_detail"   # Java
EXTRAS_MQ_ROLE       = "mq_role"        # 跨语言（producer / custom-consumer）
EXTRAS_XXL_JOBS      = "xxl_jobs"       # Java
EXTRAS_GRPC_SERVICES = "grpc_services"  # Go
EXTRAS_KTOR_METHODS  = "ktor_methods"   # Kotlin
EXTRAS_CELERY_QUEUES = "celery_queues"  # Python
EXTRAS_PRISMA_MODELS = "prisma_models"  # TypeScript
```

**`JavaFileInfo` 作为子类 + `@property` 桥接**：

```python
@dataclass
class JavaFileInfo(FileInfo):
    def __init__(self, path=None, /, **kwargs):
        # 智能调度：传 feign_clients= 走 from_legacy_kwargs；传 rpc_clients= 走 dataclass
        ...

# FileInfo 上的桥接 properties（read-only）
@property
def feign_clients(self) -> list[str]: return self.rpc_clients
@property
def dubbo_refs(self) -> list[str]: return self.extras.get(EXTRAS_DUBBO_REFS, [])
@property
def is_mq_producer(self) -> bool: return self.extras.get(EXTRAS_MQ_ROLE) == "producer"
# ... 等 6 个 properties
```

### Plugin 改造前后对比

**改造前**（Python plugin）：
```python
info = JavaFileInfo(
    path=...,
    feign_clients=[],          # 噪音
    is_mq_consumer_custom=bool(celery_tasks),  # 借用
    dubbo_refs=[],             # 噪音
    xxl_jobs=[],               # 噪音
    feign_detail={},           # 噪音
    ...
)
```

**改造后**：
```python
extras: dict = {}
if celery_tasks:
    extras[EXTRAS_MQ_ROLE] = MQ_ROLE_CUSTOM_CONSUMER
    extras[EXTRAS_CELERY_QUEUES] = list(celery_tasks)

info = JavaFileInfo(
    path=...,
    language="python",
    ...
    extras=extras,             # 只放真正相关的数据
)
```

**老 writer 代码不动**：因为 `info.feign_clients` 走 @property → `self.rpc_clients`。

### Critical bug 修复

写测试时发现 `from_legacy_kwargs` 在两个 mq flag 同时 `True` 时会 TypeError——`if/elif` 第一个分支 pop 一个 flag，另一个泄漏到 `cls(**kwargs)`。修复：先无条件 pop 两个，再分支判断。

### 验证

- 36 个 `test_models.py` 单测覆盖每条迁移路径 + property 桥接 + 边界场景
- `core/models.py` **100% 行覆盖**
- 5 fixture 输出**完全不变**（@property 桥接证明 backward-compat）

---

## 技术债 #4：Regex 覆盖盲区（4 个子项）

### 根因

每种语言都有「主流路由 / ORM / MQ 框架的 N 种写法」，原扫描器只覆盖了一小部分。

### 4 个具体盲区

#### 4.1 Ktor routing DSL

**漏的写法**：
```kotlin
routing {
    route("/api/order") {
        route("/{orderId}") {
            get("/status") { ... }   ← 单条 regex 抓不到完整路径 /api/order/{orderId}/status
        }
    }
}
```

**修复**：写状态机 `extract_ktor_routes`（详见 `03-phase-by-phase.md` Phase 1.1）。

#### 4.2 Prisma schema

**漏的文件**：`prisma/schema.prisma`（不是 `.ts`）

```prisma
model User {
  id    Int    @id
  email String
  @@map("t_user")
}
```

**修复**：独立 `parse_prisma_schema()` 解析器，合成 FileInfo 注入 db_map。

#### 4.3 Django Class-Based View

**漏的写法**：
```python
class OrderListView(generics.ListAPIView):
    ...
```

原扫描器只看文件名 / 路径前缀，不读父类 → 误识别为 `service`。

**修复**：
- 提取所有 `class X(Bases):` 的父类，与 30+ 个 Django/DRF 视图基类集合求交集
- 加 `from django|rest_framework` import 守卫（避免裸 `View` 类误报）
- 命中后剥离 `(List|Detail|Create|...)*View` 后缀，让 domain 推断得到业务名（`refund` 而非 `refund-list`）

#### 4.4 Spring 数组形 path

**漏的写法**：
```kotlin
@RequestMapping(path = ["/api/v1", "/api/v2"])
```
```java
@GetMapping({"/list", "/all"})
```

**调查发现**：`extract_string_values` 已经隐式工作（grep 所有 `"..."`），但没有 regression 保护。Phase 4 拆 writer 时容易破。

**修复**：写 19 条单测固化契约，加 fixture case 端到端验证。

### 总成绩

- **94 条新单测**（23 Ktor + 15 Prisma + 37 Django + 19 Spring）
- 4 个新 fixture / fixture 增量 + golden 验证
- discovery 文档「已知限制」段全部更新

---

## 累计修复的隐藏 bug

除了 4 项已知技术债，改造过程中还发现并修复了 7 个**之前未知的真实 bug**：

| Bug | Phase | 影响 |
| --- | --- | --- |
| `from_legacy_kwargs` 两 flag 同 True TypeError | Phase 2 | 任何同时是 producer + custom consumer 的类会让 scan 崩溃 |
| Spring 检测被注释误触 (Kotlin 插件 dispatch) | Phase 1 | Ktor 项目里 `// 之前用过 Spring` 注释会让插件走错路径 |
| 裸 `View` 类被误识别为 CBV | Phase 1 | 任何自定义本地 `class V(View)` 都会被错分 |
| argparse SystemExit 未被 catch | Phase 3 | 错误参数会让外层 orchestrator 收到异常而非 int 返回码 |
| 老脚本 cross_cutting 完全消失 | Phase 4 | `python3 analyze_java_project.py` 用户产出 31 文件 vs 新 CLI 41 文件 |
| Registry 异常时残留 | Phase 4 | plugin 异常后 emit 不被调，下次调用看到污染状态 |
| `_force_overwrite` 跨 cli.main() 调用泄漏 | Phase 5 | library-mode `cli.main(force=True)` 后下次调用静默覆盖 AI-ENRICHED |

每个 bug 都配套：
- 复现测试（先让测试失败）
- 修复 commit
- 回归测试（验证不会再坏）
