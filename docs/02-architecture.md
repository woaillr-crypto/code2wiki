# 架构设计

## 目录布局

```
scripts/
├── analyze_project.py            # 新统一 CLI 入口 (89 行)
├── analyze_java_project.py       # 老脚本，缩为 deprecation shim (106 行)
└── code2wiki/
    ├── __init__.py
    ├── cli.py                    # CLI 编排（参数解析 + plugin dispatch）
    ├── core/
    │   ├── io.py                 # 文件 I/O、AI-ENRICHED 增量保护
    │   ├── markdown.py           # md_table / role_label / 命名工具
    │   ├── domain.py             # 域推断 + 合并算法
    │   ├── git.py                # Git 历史分析（热点 / 贡献者 / 关键词）
    │   ├── writers.py            # generate_domain_docs / indexes / playbooks
    │   ├── models.py             # FileInfo / JavaFileInfo / EXTRAS_*
    │   ├── cross_cutting.py      # 跨语言合并 Registry + Emitter
    │   ├── detect.py             # 语言自动检测
    │   └── registry.py           # 插件注册表
    ├── plugins/
    │   ├── base.py               # LanguageScanner 协议 + extras keys 文档
    │   ├── language_java.py      # Java/Spring 分析器（含 Java cross-cutting）
    │   ├── language_python.py    # Python (Django/FastAPI/Flask/SQLAlchemy/Celery)
    │   ├── language_go.py        # Go (Gin/Echo/gRPC/GORM/cron)
    │   ├── language_kotlin.py    # Kotlin (Spring/Ktor + Exposed)
    │   └── language_typescript.py # TS/JS (NestJS/Express/TypeORM/Prisma/BullMQ)
    ├── tests/
    │   ├── fixtures/             # 6 个迷你项目
    │   ├── golden/               # 每个 fixture 的期望产出（machine-portable）
    │   ├── snapshot.py           # Golden 对比工具
    │   └── test_*.py             # 212 个测试
    └── CHANGELOG.md
```

## 三层架构

```
┌─────────────────────────────────────────────┐
│  scripts/analyze_project.py  (CLI 入口)      │
└──────────────────┬──────────────────────────┘
                   │ parse args, dispatch
                   ▼
┌─────────────────────────────────────────────┐
│  code2wiki/cli.py  (Orchestrator)      │
│    1. reset_cross_cutting()                 │
│    2. set_force_overwrite(False)            │
│    3. for lang in detect.pick_languages():  │
│         plugin.run_pipeline(args)           │
│    4. emit_cross_cutting_files(output)      │
│    5. finally: reset both globals           │
└──────────────────┬──────────────────────────┘
                   │
        ┌──────────┴──────────┐
        ▼                     ▼
┌──────────────┐       ┌──────────────┐
│ plugins/     │       │ core/        │
│ language_X   │ uses  │ (语言无关层) │
│ (per lang)   ├──────►│ io/markdown/ │
└──────┬───────┘       │ domain/git/  │
       │ contributes   │ writers/     │
       ▼               │ models/      │
┌──────────────┐       │ cross_cutting│
│ core/        │       └──────────────┘
│ cross_cutting│
│ Registry     │
└──────────────┘
```

### 1. `scripts/analyze_project.py`（CLI 入口）

89 行薄壳：parse args → 调 `cli.main()`。
所有真正的逻辑都在 `code2wiki/cli.py` 里，方便 library-mode 调用（`from code2wiki.cli import main`）。

### 2. `code2wiki/cli.py`（编排）

核心 8 行：

```python
reset_cross_cutting()                 # Phase 4 引入
set_force_overwrite(False)            # Phase 5 修复跨调用泄漏
try:
    for lang in languages:
        rc |= plugin.run_pipeline(args)
    emit_cross_cutting_files(output)  # 单一发射点
finally:
    reset_cross_cutting()             # 防御性双重清理
    set_force_overwrite(False)
```

### 3. plugins（语言专属）

每个 plugin 实现 `LanguageScanner` 协议（plugins/base.py）：

```python
class LanguageScanner(Protocol):
    name: str                  # "java", "python", ...
    display_name: str          # "Java/Spring"
    def file_extensions(self) -> frozenset[str]: ...
    def build_manifests(self) -> frozenset[str]: ...
    def scan_project(self, root: Path, max_files: int) -> ScanResult: ...
```

每个 plugin 的 `run_pipeline` 做三件事：

1. 扫描源文件 → 产生 `list[FileInfo]`
2. 调用 `core.writers.generate_*` 生成 `01_business_domains/` / `05_indexes/` 等
3. 调用 `core.cross_cutting.add_cross_cutting(...)` 注册 cross-cutting 贡献（不直接写盘）

### 4. core（语言无关）

| 模块 | 职责 | 行数 |
| --- | --- | --- |
| `io.py` | 文件读写、AI-ENRICHED 守卫、IGNORE_DIRS | 194 |
| `markdown.py` | 表格、role 标签、命名归一化 | 100 |
| `domain.py` | 域推断（class/package/table/path）+ 合并 | 279 |
| `git.py` | git log → hot files / 贡献者 / 关键词 | 175 |
| `writers.py` | generate_root_skill / generate_domain_docs / ... | 763 |
| `models.py` | FileInfo + JavaFileInfo + EXTRAS_* 常量 | 264 |
| `cross_cutting.py` | Registry + emit_cross_cutting_files | 117 |
| `detect.py` | 语言自动检测 | 99 |
| `registry.py` | 插件注册表 | 69 |

## 关键设计决策

### 决策 1：JavaFileInfo 作为 FileInfo 的兼容子类

**问题**：把 `JavaFileInfo` 重命名为 `FileInfo` 会破坏 `core/writers.py` 里 ~30 处 `info.feign_clients` / `info.dubbo_refs` 等访问。

**方案**：
- `FileInfo` 是新的通用 dataclass，字段 `rpc_clients` / `extras`
- `JavaFileInfo` 是子类，添加 `@property` 桥接：
  ```python
  @property
  def feign_clients(self) -> list[str]:
      return self.rpc_clients
  @property
  def dubbo_refs(self) -> list[str]:
      return self.extras.get(EXTRAS_DUBBO_REFS, [])
  ```
- 老 writer 代码继续 `info.feign_clients` 工作（read-only），新 plugin 用 `info.extras[EXTRAS_*]`

**收益**：byte-identical 保护 + 渐进迁移空间。

### 决策 2：Cross-Cutting Registry 是进程级全局

**问题**：每个 plugin 单独执行 `run_pipeline`，先后顺序导致后者覆盖前者的 cross-cutting 文件。

**方案**：
- 引入 `_REGISTERED: list[CrossCuttingFile]` 进程级 list
- plugin 不直接 write，而是 `add_cross_cutting(name=..., title=..., body=...)` 注册
- CLI 在所有 plugin 完成后调 `emit_cross_cutting_files()`：
  - 同一 `name` 只有 1 个贡献 → byte-identical 单文件输出
  - 同一 `name` 多个贡献 → 合并为 `# 总标题 \n\n## Java\n...\n\n## TypeScript\n...`
  - 子标题 `##` → `###` 自动降级
- CLI 用 `try/finally` 双重 reset 保证不跨调用泄漏

### 决策 3：CrossCuttingFile dataclass frozen

`@dataclass(frozen=True)`，注册后不可改。防止 plugin 共享同一对象后互相干扰。

### 决策 4：标准 EXTRAS_* 常量

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

避免插件之间用 raw string key 漂移（写 `"dubbo_refs"` 和读 `"dubbo_ref"` 这种 typo）。

### 决策 5：legacy 老脚本仍可工作 + 显式 deprecation

`analyze_java_project.py` 不是直接删除，而是 106 行 shim：
- import 所有 public 名字（main / analyze_java_file / generate_cross_cutting / ...）从新位置
- `__main__` 入口打印 `[DEPRECATED]` banner 到 stderr
- 包了 `_legacy_main_with_cross_cutting()` 调 reset + main + emit（Phase 4 Critical-2 修复）

第三方代码 `from analyze_java_project import main` 还能用，但用户能看到提示。

## 数据流（一次完整扫描）

```
1. 用户运行: python3 analyze_project.py /path/to/project
       │
2. cli.main() parse args
       │
3. detect.pick_languages(project)
       │  返回 ["java", "typescript"]
       ▼
4. reset_cross_cutting() + set_force_overwrite(False)
       │
5. for lang in ["java", "typescript"]:
       │
       ├─► JavaPlugin.run_pipeline(args)
       │     │
       │     ├─► iter_files → analyze_java_file → list[FileInfo]
       │     ├─► generate_root_skill / generate_domain_docs / ...
       │     │     (写 01_business_domains/, 05_indexes/, ...)
       │     └─► generate_cross_cutting → 11 次 add_cross_cutting(...)
       │           (mq, scheduler, cache, transaction, concurrency,
       │            auth, permission, idempotency, observability,
       │            dubbo_rpc, feign_rpc)
       │
       └─► TypescriptPlugin.run_pipeline(args)
             ├─► iter_files → analyze_typescript_file → list[FileInfo]
             ├─► generate_*  (同上)
             └─► _generate_cross_cutting → 7 次 add_cross_cutting(...)
                   (mq, scheduler, cache, transaction,
                    concurrency, auth, observability)
       │
6. emit_cross_cutting_files(output)
       │  按 name 分桶：
       │    mq: [Java贡献, TS贡献] → 合并为 ## Java / ## TypeScript
       │    scheduler: [Java贡献, TS贡献] → 合并
       │    cache: [Java贡献, TS贡献] → 合并
       │    ... (etc)
       │    dubbo_rpc: [仅Java贡献] → 单语言写入
       │    feign_rpc: [仅Java贡献] → 单语言写入
       ▼
7. finally: reset_cross_cutting() + set_force_overwrite(False)
```

## 扩展点

**加新语言**：
1. 写 `plugins/language_rust.py`，仿照 Go plugin 模板
2. 在 `core/registry.py` 加 import
3. 在 `core/detect.py` 加 `Cargo.toml` / `.rs` 检测
4. 加 fixture + golden + 单测

**加新 extras key**：
1. 在 `core/models.py` 加 `EXTRAS_FOO = "foo"`
2. 在 `plugins/base.py` docstring 加说明
3. plugin 用 `info.extras[EXTRAS_FOO] = ...` 写入

**加新 cross-cutting 类型**：
1. plugin 的 `_generate_cross_cutting` 里调 `add_cross_cutting(name="新名字", title="...", body="...", language=..., language_label=...)`
2. 多语言同时贡献同名时，自动合并

具体步骤见 `07-how-to-extend.md`。
