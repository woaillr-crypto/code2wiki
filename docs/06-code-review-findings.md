# Code Review Findings 汇总

整个改造周期共进行 **6 次 code-review**（Phase 0/1/2/3/4/5），累计 **~30 个 finding**，**全部修复**。本文档按 severity 归档，便于后续相似改造避坑。

## Critical 级别（4 个）

任何一个会**直接破坏功能**，必须修。

### Critical-1: `from_legacy_kwargs` 两 flag 同 True 会 TypeError

**Phase 2** | `core/models.py:from_legacy_kwargs`

**症状**：当 `is_mq_producer=True AND is_mq_consumer_custom=True` 时（一个类既发消息又有自定义 consumer，RocketMQ Boot 集成常见），`if/elif` 第一个分支 pop 一个 flag，另一个泄漏到 `cls(**kwargs)` → `TypeError: FileInfo.__init__() got an unexpected keyword argument 'is_mq_consumer_custom'`。

**根因**：分支结构错误：
```python
# 错误
if kwargs.pop("is_mq_producer", False):
    extras[EXTRAS_MQ_ROLE] = MQ_ROLE_PRODUCER
elif kwargs.pop("is_mq_consumer_custom", False):  # 只在第一支为 False 时才 pop
    extras[EXTRAS_MQ_ROLE] = MQ_ROLE_CUSTOM_CONSUMER
```

**修复**：先无条件 pop 两个 flag，再分支判断：
```python
mq_producer = bool(kwargs.pop("is_mq_producer", False))
mq_consumer_custom = bool(kwargs.pop("is_mq_consumer_custom", False))
if mq_producer:
    extras[EXTRAS_MQ_ROLE] = MQ_ROLE_PRODUCER
elif mq_consumer_custom:
    extras[EXTRAS_MQ_ROLE] = MQ_ROLE_CUSTOM_CONSUMER
```

**回归测试**：`test_from_legacy_both_flags_true_producer_wins_and_no_typeerror`

---

### Critical-2: 老脚本完全没产出 cross_cutting 目录

**Phase 4** | `scripts/analyze_java_project.py`

**症状**：`python3 analyze_java_project.py /path --output /tmp/out` 产出 31 文件，但走新 CLI 产出 41 文件。差额 10 个文件全是 `02_cross_cutting/*.md`。用户的 BCL 完全不完整。

**根因**：Phase 4 把 Java 的 `generate_cross_cutting` 改为只 `add_cross_cutting()` 注册而不 `write()`。老脚本入口 `_run_legacy_pipeline` 只走 register 不走 emit（emit 只在新 CLI 的 `cli.main()` 里调）。

**修复**：在老脚本入口包装：
```python
def _legacy_main_with_cross_cutting() -> int:
    from code2wiki.core.cross_cutting import (
        emit_cross_cutting_files, reset_cross_cutting,
    )
    # 自己解析 sys.argv 找 --output
    out_dir = ...
    reset_cross_cutting()
    try:
        rc = main()
        if out_dir is not None:
            emit_cross_cutting_files(out_dir)
        return rc
    finally:
        reset_cross_cutting()
```

**回归测试**：`test_legacy_main_emits_cross_cutting_files` —— 用 subprocess 跑 `python3 analyze_java_project.py ...`，断言 `02_cross_cutting/` 含 mq.md / scheduler.md 等。

---

### Critical-3: Registry 异常时残留

**Phase 4** | `code2wiki/cli.py`

**症状**：plugin 异常时 `emit_cross_cutting_files` 不被调，`_REGISTERED` 残留。下次 `cli.main()` 看到污染数据。

**根因**：CLI 没有 try/finally 守卫。

**修复**：
```python
reset_cross_cutting()
try:
    for lang in languages:
        plugin.run_pipeline(args)
    emit_cross_cutting_files(output)
finally:
    reset_cross_cutting()
```

---

### Critical-4: `_force_overwrite` 跨调用泄漏（symmetric bug）

**Phase 5** | `code2wiki/cli.py` + `code2wiki/core/io.py`

**症状**：library-mode 调用：
```python
cli.main(["proj_a", "--force"])    # 设置 _force_overwrite = True
cli.main(["proj_b"])               # 没 --force，但 _force_overwrite 还是 True
                                   # → 默默覆盖 proj_b 的 AI-ENRICHED 文件
```

**根因**：和 Critical-3 同样的全局状态泄漏，但当时只修了 registry，没修 `_force_overwrite`。

**修复**：
```python
reset_cross_cutting()
set_force_overwrite(False)          # 新增
try:
    ...
finally:
    reset_cross_cutting()
    set_force_overwrite(False)      # 新增
```

**回归测试**：`test_pipeline_force_flag_does_NOT_leak_across_cli_calls`

---

## High 级别（5 个）

会破坏正确性但有 fallback 路径。

### High-1: argparse SystemExit 未捕获

**Phase 3** | `plugins/language_java.py:JavaPlugin.run_pipeline`

**症状**：JavaPlugin 通过 `sys.argv` 桥接调 `_run_legacy_pipeline()`，argparse 遇到坏参数会 `sys.exit(2)`，抛 SystemExit 给外层。外层 orchestrator 期待 int 返回码。

**修复**：
```python
try:
    return _run_legacy_pipeline(new_argv)
except SystemExit as exc:
    return exc.code if isinstance(exc.code, int) else 1
```

### High-2: Spring 检测被注释误触

**Phase 1** | `plugins/language_kotlin.py:_project_uses_spring`

**症状**：Kotlin 插件用 `if "org.springframework" in raw_text:` 判断是否 Spring 项目。如果 build.gradle.kts 里有注释 `// 之前用过 Spring`，Ktor 项目会被错路由到 Java pipeline。

**修复**：改用 `_parse_gradle_kts(build_files)` 解析出的 deps list 判断。

### High-3: 裸 `View` 类被误识别为 CBV

**Phase 1** | `plugins/language_python.py:_is_django_cbv`

**症状**：`DJANGO_CBV_BASE_CLASSES` 含裸字符串 `"View"`。任何文件里有 `class MyHelper(View):`（本地工具类）都被错识为 controller。

**修复**：加 `_DJANGO_DRF_IMPORT_RE` 守卫，要求文件实际有 `from django|rest_framework` import 才认 CBV。

### High-4: `sys.argv` 全局污染

**Phase 5** | `plugins/language_java.py:JavaPlugin.run_pipeline`

**症状**：JavaPlugin 改写 `sys.argv` 后调 `_run_legacy_pipeline`，期间 sys.argv 是全局变量。多线程 library 调用会数据竞争。

**修复**：让 `_run_legacy_pipeline(argv=None)` 接受参数，不再读 `sys.argv`：
```python
def _run_legacy_pipeline(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(...)
    args = parser.parse_args(argv)  # argv=None 时 fallback 到 sys.argv
```

### High-5: Stale "Phase 3 will remove" docstrings

**Phase 5** | `core/models.py`

**症状**：`@property feign_clients` 等的注释说 "Phase 3 will remove these once all consumer call sites are migrated"。Phase 5 已完成，但这些 properties 仍在用，不会移除。误导未来贡献者。

**修复**：把承诺改成「将持续保留，直到所有 writer 调用点迁移」的真实状态描述。

---

## Medium 级别（8 个）

不破坏功能，但会让人困惑或带来潜在隐患。

| # | Phase | 文件 | 问题 | 修复 |
| --- | --- | --- | --- | --- |
| M-1 | 1 | `language_typescript.py` | Prisma `PRISMA_MODEL_RE` 不剥块注释 | 先 `re.sub` 剥 `/* ... */` 再匹配 model |
| M-2 | 2 | `core/models.py` | `JavaFileInfo("X.java")` 不支持位置 path（dataclass override 破坏 contract） | 加 `path: str | None = None, /, **kwargs` |
| M-3 | 4 | `core/cross_cutting.py` | title 冲突静默丢失 | 加 `[WARN]` 日志 + 测试 |
| M-4 | 4 | `core/cross_cutting.py` | `emit_cross_cutting_files` 依赖 `write()` 内部 mkdir | 显式 `mkdir(parents=True, exist_ok=True)` |
| M-5 | 5 | `analyze_ts_file` | 命名不一致（其他都是 `analyze_<lang>_file`） | 改名 `analyze_typescript_file` + 别名 |
| M-6 | 5 | `plugins/base.py` | docstring 列的 extras key 名不对（写 `grpc_methods` 实际是 `grpc_services`） | docstring 改用真实 `EXTRAS_*` 常量名 |
| M-7 | 5 | `test_pipeline_coverage.py` | 没测 `_force_overwrite` 跨调用泄漏 | 加 `test_pipeline_force_flag_does_NOT_leak_across_cli_calls` |
| M-8 | 0 | `tests/snapshot.py` | Symlink 没跳过（compare 和 freeze 都可能无限递归） | 两处都 `if path.is_symlink(): continue` |

---

## Low 级别（4 个）

风格 / 类型注解 / 死代码。

| # | Phase | 文件 | 问题 | 修复 |
| --- | --- | --- | --- | --- |
| L-1 | 5 | `core/writers.py` | `list[JavaFileInfo]` annotation lies（实际接受 FileInfo） | 改 `list[FileInfo]` |
| L-2 | 5 | `language_python.py` | `PY_TECH_SEGMENTS` 含两次 `"factories"` | 删重复 |
| L-3 | 5 | `language_java.py` | Phase 3.7 banner 引入 4 个未用 import（dataclass / asdict / Iterable / dataclass_field） | 全删 |
| L-4 | 4 | `language_java.py` | `# Main` stale 注释 | 改为 "# Legacy pipeline entry point" |

---

## 经验教训

整个改造过程中浮现的几条经验：

### 1. byte-identical 闸门是「金标准」

每个 phase 都要保证 5 个单语言 fixture 输出**完全不变**（只有 mixed fixture 在 Phase 4 后预期变化）。这给重构兜底——任何意外的逻辑改动都会立刻被 snapshot 测试报错。

**反例**：如果只跑「不报错」级别的 smoke test，Phase 3 把 2363 行代码搬到 7 个文件这种大手术会有无数隐性 bug 漏掉。

### 2. 全局状态是隐形 bug 工厂

`_force_overwrite` 和 `_REGISTERED` 都是 module-level mutable globals。每加一个全局状态：
- 立刻要想 library-mode 多次调用会不会泄漏
- 立刻要在 CLI 的 try/finally 加 reset
- 立刻要写「相邻两次调用」回归测试

**反例**：Phase 4 只修了 `_REGISTERED` 没修 `_force_overwrite`，Phase 5 reviewer 才发现 symmetric bug。

### 3. 写测试时发现真 bug

`from_legacy_kwargs` 的 Critical TypeError 是写测试时发现的——`test_from_legacy_both_flags_true_producer_wins_and_no_typeerror` 让我注意到边界 case。**写测试本身就是 review。**

### 4. Code review agent 不会发现所有问题

每次 code-review 都漏掉一些后续才发现的问题：
- Phase 4 review 发现 Critical-3（registry 异常残留）但漏了 Critical-4（_force_overwrite symmetric leak）
- Phase 5 final reviewer 才补上

**结论**：reviewer 不是终点，分阶段累积的多次 review 才是。

### 5. 老代码先理解，再动刀

Phase 3 把 ~2000 行代码从 monolith 搬到 7 个模块。如果一次性「读 + 搬 + 验证」会很容易丢东西。**实际做法**：
- 用 grep 列出所有函数 + 它们被谁调用
- 用 Python script 按行号范围剪切粘贴
- **每搬一个子模块**就跑 snapshot 测试（共 7 次）
- 任何一次 snapshot 失败立即定位是哪个迁移引起的

### 6. Deprecation 比删除更安全

老脚本 `analyze_java_project.py` 不是直接删，而是：
- 缩成 106 行 shim
- 所有 public 名字仍可 import（`main`, `analyze_java_file`, 等）
- `__main__` 入口打 `[DEPRECATED]` banner
- 第三方代码继续工作，用户能看到迁移提示

如果直接删除，任何依赖 `from analyze_java_project import main` 的下游代码立刻报错。**渐进废弃 > 一次性删除。**
