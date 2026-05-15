# 6 个 Phase 实施细节

整个改造按 6 个 Phase 推进，每个 Phase 都过 5 个闸门（G1-G5）。Phase 之间严格串行，确保前一个 Phase 的产出稳定后才进入下一个。

## 闸门定义

每个 Phase 收尾必须过：

| 闸门 | 说明 |
| --- | --- |
| **G1** | 新代码单测覆盖率达标 |
| **G2** | 5 fixture × snapshot 全 byte-identical（mixed 除外，按预期更新） |
| **G3** | code-reviewer agent 复查所有 PRIORITY 1/2 finding 全清 |
| **G4** | 文档同步（discovery / context-model / docstring） |
| **G5** | 用户最终确认 |

---

## Phase 0 — 测试基础设施（前置）

**目标**：建立 byte-identical 保护网，让后续每个 Phase 都能用客观证据验收。

**产出**：

- `tests/snapshot.py`（357 行）：Golden snapshot 对比工具
  - `compare(golden, actual)` — 对比两个目录
  - `freeze_actual_as_golden(actual, golden)` — 把当前输出冻结为 golden（自动 path normalization）
  - `update_golden()` / CLI 子命令 `freeze` / `compare` / `update`
- `tests/test_snapshot_util.py`（33 个单测，98% 覆盖）
- `tests/test_snapshot.py`（fixture-driven 集成测试）
- 5 个 fixture：java / python / go / typescript / **mixed**（Java+TS Monorepo）
- 5 套 golden（全部 normalized：`<PROJECT_DIR>` / `<OUTPUT_DIR>` 占位符）
- `tests/README.md` — 使用文档

**关键设计**：

- Golden 文件**已 normalized**（含 `<OUTPUT_DIR>` 占位符），跨机器/CI 可移植
- Symlink 在 compare 和 freeze 中都被跳过（防御无限递归 + 数据泄漏）
- Binary 文件用 `rel_path` 作为 sentinel（防止假报 modified）

**闸门成绩**：

- G1: snapshot.py 单测覆盖 98% ✅
- G2: 5 fixture 全绿，0 个 `/Users/` 残留 ✅
- G3: code-reviewer 找到 P1-A/P1-B/P1-C 3 个 HIGH 问题，全部修复 ✅
- G4: tests/README.md ✅
- G5: 用户 "Phase 0 过" ✅

---

## Phase 1 — Regex 覆盖盲区填补（4 个子项）

**目标**：填补 4 项 regex 检测能力，每项配 fixture + 单测 + golden + discovery 文档。

### 1.1 Ktor routing DSL（最难的一项）

**问题**：Ktor 用嵌套 lambda DSL：
```kotlin
routing {
    route("/api/order") {
        get("/{id}") { ... }
        post("/create") { ... }
    }
}
```
单条 regex 抓不到嵌套结构。

**方案**：状态机 `extract_ktor_routes`：
- 跳过字符串/三引号 raw string/`//` 行注释/`/* */` 块注释
- 用 `{` `}` 平衡跟踪 scope 栈（routing 进栈 / route 进栈 / 普通 brace 也进栈但不贡献前缀）
- verb 调用时拼接当前所有 scope prefix → 完整 URL
- 深度限制 `max_depth=16` 防御恶意嵌套

**单测**：23 条覆盖嵌套 / 字符串带 `{` / 不平衡 brace / 多 routing 块独立等

### 1.2 Prisma schema

**问题**：`prisma/schema.prisma` 不是 `.ts`，原扫描器跳过；导致 Prisma 项目 db_map.md 为空。

**方案**：`parse_prisma_schema(text)` 单独解析 `model X { ... @@map("table_x") }`，每个 .prisma 文件合成一个 FileInfo（role=entity，extras=`prisma_models`）。

**单测**：15 条覆盖 `@@map` / 字段类型 / 可选 / 数组 / 注释 / enum 排除等

### 1.3 Django Class-Based View

**问题**：`class OrderListView(ListAPIView):` 原扫描器看不懂父类，错分类为 service。

**方案**：
- 维护 `DJANGO_CBV_BASE_CLASSES` 集合（30+ 个 Django/DRF view 基类）
- `_is_django_cbv(text)` 提取所有 `class X(Bases):` 的父类，集合求交集
- **守卫**：还要求文件实际 `from django/rest_framework` import（避免裸 `View` 类误识别）
- 命中后剥离 `(List|Detail|Create|...)*View` 后缀，让 domain 推断得到业务名

**单测**：37 条，含父类继承多 mixin、qualified module path、本地 View 类误报防护等

### 1.4 Spring 数组形 path

**问题**：`@RequestMapping(path = ["/foo", "/bar"])`（Kotlin）/ `@GetMapping({"/x", "/y"})`（Java）。

**调查发现**：`extract_string_values` 已经隐式支持（grep 所有 `"..."`），但**没有 regression 保护**。Phase 4 拆 writer 时容易破。

**方案**：写 19 条单测固化契约，加 fixture case 验证端到端。

**闸门成绩**：

- G1: 94 新单测全绿 ✅
- G2: 5 旧 fixture **完全不变**；4 个新 fixture/子样例就位 ✅
- G3: code-reviewer 8 finding（含 3 HIGH）全清：
  - HIGH-3 (Kotlin Spring 检测被注释误触): 改用 parsed deps
  - HIGH-5 (裸 View 误报): 加 django/drf import 守卫
  - MEDIUM-4 (Prisma 块注释): 剥块注释
- G4: python.md / kotlin.md / typescript.md 三份「已知限制」更新 ✅
- G5: 用户 "确认" ✅

**测试增量**：40 → 135

---

## Phase 2 — FileInfo 通用化

**目标**：把 23 字段的 `JavaFileInfo` 重塑为语言无关 `FileInfo`，Java 专属字段降到 `extras` dict。

**关键挑战**：`analyze_java_project.py` 中 ~30 处消费 `info.feign_clients` / `info.dubbo_refs` / `info.is_mq_producer` 等。一次性改完风险大。

**方案**：

1. **新 `FileInfo` dataclass**：通用字段（path / language / package / class_name / role / domain / mappings / tables / mq_listeners / scheduled / **rpc_clients** / risk_signals / ... / **extras** dict）

2. **`JavaFileInfo` 作为子类**：添加 6 个 `@property` 桥接：
   ```python
   @property
   def feign_clients(self): return self.rpc_clients
   @property
   def dubbo_refs(self): return self.extras.get(EXTRAS_DUBBO_REFS, [])
   # ... 等
   ```

3. **`from_legacy_kwargs()`**：迁移函数，把旧字段名转新 schema
   - `feign_clients=` → `rpc_clients=`
   - `dubbo_refs=` → `extras[EXTRAS_DUBBO_REFS]=`
   - `is_mq_producer=True` → `extras[EXTRAS_MQ_ROLE]="producer"`
   - 等

4. **`JavaFileInfo.__init__` 智能调度**：
   - 调用方传 `feign_clients=` 等旧名 → 走 `from_legacy_kwargs`
   - 调用方传 `rpc_clients=` 等新名 → 走 dataclass 默认 `__init__`

5. **核心 dataclasses 都搬到 core/models.py**：`ProjectContext` / `GitContext` / `MyBatisXmlInfo`（解循环 import）

6. **inventory.json schema 清理**：`"feign_clients"` → `"rpc_clients"`；加 `"language"` 字段

**Critical bug 发现**：写测试时发现 `from_legacy_kwargs` 在 `is_mq_producer=True AND is_mq_consumer_custom=True` 时会 `TypeError`（第一个分支 pop 一个，另一个泄漏到 cls 构造器）。修复：先无条件 pop 两个，再分支。

**闸门成绩**：

- G1: `core/models.py` **100% 覆盖**（116 行 / 0 miss）✅
- G2: 5 fixture byte-identical ✅
- G3: code-reviewer 9 finding（含 1 Critical + 1 HIGH）全清：
  - **Critical Finding 1**（两 flag 同 True TypeError）已修 + 回归测试
  - **HIGH Finding 2**（positional path 不支持）已修 + 测试
- G4: extras keys 文档 ✅
- G5: 用户 "确认" ✅

**测试增量**：135 → 171（+36 个 models 单测）

---

## Phase 3 — core/* 真实代码迁移

**目标**：把 2363 行 `analyze_java_project.py` 按模块边界搬到 `core/*` 和 `plugins/language_java.py`，老脚本变 ≤50 行 shim。

### 子步骤（每步都跑 snapshot）

| 子步骤 | 搬运内容 | 目标文件 |
| --- | --- | --- |
| 3.1 | read_text / iter_files / write / AI-ENRICHED 守卫 + 常量 | core/io.py |
| 3.2 | md_table / role_label / skill_name_from_project | core/markdown.py |
| 3.3 | normalize_domain / *_to_domain / merge_domains | core/domain.py |
| 3.4 | _git_cmd / analyze_git_history / generate_git_activity | core/git.py |
| 3.5 | generate_root_skill / generate_domain_docs / ... (~970 行) | core/writers.py |
| 3.6 | generate_cross_cutting (~250 行) | plugins/language_java.py |
| 3.7 | 剩余 Java 全部（extractors + analyze_java_file + main） | plugins/language_java.py |

### 关键技术细节

**循环 import 处理**：core/models 需要从 analyze_java_project 拿 `GitContext` / `ProjectContext` / `MyBatisXmlInfo`，但 analyze_java_project 又 import 自 core/models（JavaFileInfo）。**解法**：把那 3 个 dataclass 也搬到 core/models.py。

**lazy import 解 Phase 3.6 的循环依赖**：cross_cutting 暂时需要从 language_java import generate_cross_cutting，但 language_java import 自 analyze_java_project（拿 _aj 引用）。**解法**：在 analyze_java_project 中给 generate_cross_cutting 做个 lazy 函数包装。

**Phase 3.7 一次性大搬运**：用 Python script 剪切粘贴 ~600 行剩余代码到 plugins/language_java.py，并把 `main()` 改名为 `_run_legacy_pipeline()`。

**老脚本 shim**：106 行（含 deprecation 提示 + `_legacy_main_with_cross_cutting` 包装器）：
```python
from code2wiki.plugins.language_java import (
    _run_legacy_pipeline as main,
    analyze_java_file, ...
)
# __main__: print [DEPRECATED] + DeprecationWarning + main()
```

**闸门成绩**：

- G1: 每个子步骤跑 snapshot，全绿才进 next；core/* 覆盖率累计大幅提升 ✅
- G2: 6 fixture × 8 snapshot 测试每步都过 ✅
- G3: code-reviewer 8 finding（含 2 HIGH）：
  - HIGH-1 (argparse SystemExit 未捕获): try/except 包裹
  - HIGH-3 (Spring 检测被注释误触): 改用 parsed deps（Phase 1 已修，这里复验）
  - 6 个 imports 去重 / 死代码删除 / docstring 更新
- G4: shim docstring 加 programmatic main 警告 ✅
- G5: 用户 "确认" ✅

**核心 deliverable**：
- `analyze_java_project.py`: 2363 行 → **106 行**（96% 削减）
- core/* 总计 1142 行真实实现
- 全代码库 `from analyze_java_project import` 0 个残留

**测试增量**：171 → 195

---

## Phase 4 — Writer Registration

**目标**：修复混合语言项目 cross-cutting 文件被覆盖的核心 bug，让 Java+TS Monorepo 真正可用。

**Bug 描述**：mixed fixture 的 `02_cross_cutting/mq.md` 只有 TypeScript 的 BullMQ 内容，Java 的 RocketMQ Consumer 完全消失（被后跑的 TS plugin 覆盖）。

### 实施

1. **`core/cross_cutting.py`**：进程级 registry
   - `CrossCuttingFile` frozen dataclass: name / title / body / language / language_label
   - `add_cross_cutting()` / `reset_cross_cutting()` / `emit_cross_cutting_files()`
   - 单 plugin 命中 → byte-identical 输出（保护 5 套单语言 fixture）
   - 多 plugin 命中 → 合并为 `## <Language>` 双段 + 子标题 `##→###` 自动降级
   - 多 plugin 排序：按 `language` 字母序（保 Monorepo 输出可重现）

2. **5 个 plugin 重构**：每个 plugin 的 `_generate_cross_cutting` / Java `generate_cross_cutting` 改用 `add_cross_cutting(...)` 而非 `write(...)`

3. **CLI 集成**：plugin loop 前 reset，loop 后 emit

4. **mixed fixture golden 重冻**：新输出含 `## Java (RocketMQ / Feign)` + `## TypeScript (NestJS / BullMQ / TypeORM)` 双 section

### 关键 review 修复

- **Critical-1**：plugin 异常时 registry 残留 → CLI 加 `try/finally` 双重清理
- **Critical-2**：**老脚本 `python3 analyze_java_project.py` 完全没产出 cross_cutting 目录**！因为它只 register 不 emit。修复：加 `_legacy_main_with_cross_cutting()` 包装老 main 做 reset+emit。配套 subprocess 集成测试。
- **High-3**：title 冲突时静默丢弃 → 加 `[WARN]` 日志 + 2 个新测试

**闸门成绩**：

- G1: 17 cross_cutting 单测 + 5 新回归测试 ✅
- G2: 5 单语言 fixture **完全不变**；mixed 重 freeze，含双 section ✅
- G3: code-reviewer 6 finding 全清（含 2 Critical）
- G4: cross_cutting.py docstring 解释合并规则 ✅
- G5: 用户 "确认" ✅

**测试增量**：195 → 211

---

## Phase 5 — 全量回归 + 文档收尾

**目标**：80% 覆盖率达标，文档同步，最终双 reviewer 验收。

### 覆盖率提升

**问题**：snapshot 测试用 subprocess 跑，coverage.py 看不到 plugin 代码执行。

**方案**：新增 `test_pipeline_coverage.py`：
- 12 个 in-process 测试调 `cli.main()`（不用 subprocess）
- 覆盖 --force / --no-merge / --verbose / --language / --plugin-only / --top-domains
- 真实 git repo 测试覆盖 `core/git.py`

**结果**：从 50% → **80%**：
- `core/git.py` 14% → 91%
- `core/cross_cutting.py` 100%
- `core/models.py` 100%

### 文档同步

- `CHANGELOG.md`：0.4.0 发布说明
- `references/context-model.md`：跨语言合并规则段落
- `core/models.py` / `core/writers.py` / `code2wiki/__init__.py` docstrings 去 Phase 标签
- `plugins/base.py`：extras keys 文档用真实 EXTRAS_* 常量名

### 最终双 reviewer 验收

reviewer 找到 9 个 finding（3 HIGH + 4 MEDIUM + 2 LOW）：

- **HIGH-1**：`_force_overwrite` 跨 cli.main() 调用泄漏（symmetric 于 Phase 4 registry 泄漏）→ CLI 加 `set_force_overwrite(False)` 到 try/finally
- **HIGH-2**：stale "Phase 3 will remove" docstrings → 改正
- **HIGH-3**：JavaPlugin 改 sys.argv 全局污染（library-mode 多线程隐患） → `_run_legacy_pipeline(argv=None)` 接受参数
- **MEDIUM**：`analyze_ts_file` → `analyze_typescript_file` + 别名；base.py 错误 key 名；测 force 泄漏；duplicate `factories`
- **LOW**：`list[JavaFileInfo]` → `list[FileInfo]` annotation

**闸门成绩**：

- G1: 212 测试 + **80% 覆盖** ✅
- G2: 6 fixture × 8 snapshot 全绿 ✅
- G3: 双 reviewer 9 finding 全清 ✅
- G4: 5 处文档全部同步 ✅
- G5: 用户 "确认" ✅

**测试增量**：211 → 212

---

## 累计成绩

| 维度 | Phase 0 | Phase 5 |
| --- | --- | --- |
| 测试数量 | 0 | 212 |
| 覆盖率 | - | 80% |
| Fixture | 0 | 6 |
| Code review finding 修复 | - | ~20 |
| `analyze_java_project.py` 行数 | 2363 | 106 |
| 支持语言数 | 1 | 5 |
| 混合项目可用性 | ❌ | ✅ |
