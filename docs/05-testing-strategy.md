# 测试策略

整个改造的「零回归」保护完全建立在测试基础设施上。本文档解释 6 fixture × Golden snapshot × 单测三层防线如何配合。

## 三层防线

```
┌─────────────────────────────────────────────────────┐
│  Layer 3: Snapshot 集成测试 (8 个测试)              │
│  保护：6 fixture × 跨多个 phase 的产出 byte-identical│
└────────────────────────┬────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────┐
│  Layer 2: In-process 集成测试 (12 个测试)            │
│  保护：覆盖率计入；CLI 参数路径全部走过              │
└────────────────────────┬────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────┐
│  Layer 1: 单元测试 (~190 个测试)                    │
│  保护：snapshot.py / extractors / regex / models    │
└─────────────────────────────────────────────────────┘
```

## Layer 1: 单元测试（190+）

### 按模块分布

| 测试文件 | 测试数 | 覆盖内容 |
| --- | --- | --- |
| `test_snapshot_util.py` | 33 | snapshot.py 自身（compare / freeze / normalize） |
| `test_models.py` | 38 | FileInfo / JavaFileInfo / from_legacy_kwargs / @property bridges |
| `test_kotlin_patterns.py` | 23 | Ktor routing 状态机：嵌套 / 字符串带 `{` / 注释跳过 / 深度限制 |
| `test_python_patterns.py` | 37 | Django CBV 识别 / `_extract_all_bases` / 父类提取 / DRF/Django 视图基类 |
| `test_typescript_patterns.py` | 15 | Prisma schema 解析（model / @@map / fields / enum 排除） |
| `test_java_patterns.py` | 21 | Spring 数组形 path / SystemExit 处理 / legacy script 集成 |
| `test_cross_cutting.py` | 22 | Registry 操作 / 合并算法 / heading 降级 / title 冲突 |

### 单测设计原则

**1. 正反样本配对**：每条 regex 配「应该匹配」+「应该不匹配」两组 case
```python
def test_listapiview_is_cbv(): ...      # 正样本
def test_plain_service_class_is_not_cbv(): ...  # 反样本
def test_class_inheriting_from_user_mixin_only_is_not_cbv(): ...  # 边界
```

**2. 边界 case 显式覆盖**：
- 空输入：`test_empty_string_returns_empty`
- 不平衡：`test_unbalanced_braces_do_not_crash`
- 深度限制：`test_deeply_nested_routes_do_not_crash`
- 字符串/注释里的语法：`test_braces_inside_string_literal_do_not_confuse_stack`

**3. 文档化已知限制**：
```python
def test_compare_binary_files_with_different_content_currently_collide(tmp_path):
    """Documents the deliberate limitation: binary files are compared via the
    sentinel only. Differing binary content is NOT detected."""
    ...
```
显式断言「这个 case 不会被检测到」——避免有人误以为是 bug。

## Layer 2: In-process 集成测试

### 为什么需要

Layer 3 的 snapshot 测试用 `subprocess.run` 跑 scanner，coverage.py 看不到子进程的代码执行。结果就是 plugin 代码（~2300 行）的覆盖率为 0。

**修复**：`test_pipeline_coverage.py` 新增 12 个测试，全部走 `from code2wiki.cli import main` → in-process 调用。

### 覆盖的代码路径

| 测试 | 覆盖路径 |
| --- | --- |
| `test_pipeline_runs_in_process[X]` | 每个 fixture 走 plugin 完整 pipeline（参数化 6 个） |
| `test_pipeline_force_flag_overwrites_ai_enriched` | `--force` 旗标 → AI-ENRICHED 覆盖逻辑 |
| `test_pipeline_force_flag_does_NOT_leak_across_cli_calls` | **Critical 回归保护**：CLI try/finally 重置 `_force_overwrite` |
| `test_pipeline_no_merge_flag_disables_domain_merging` | `--no-merge` 分支 |
| `test_pipeline_verbose_flag` | `--verbose` banner 输出 |
| `test_pipeline_explicit_language_flag` | `--language java` 显式指定 |
| `test_pipeline_plugin_only_flag` | `--plugin-only typescript` debug 路径 |
| `test_pipeline_top_domains_truncates` | `--top-domains 1` 截断 |
| `test_pipeline_with_real_git_repo` | 真实 git init/commit/log → core/git.py |
| `test_git_cmd_returns_none_on_non_git_dir` | git rev-parse 失败分支 |
| `test_analyze_git_history_returns_empty_for_non_git_dir` | 非 git 仓库 fallback |
| `test_generate_git_activity_renders_placeholder_when_not_git_repo` | 占位符渲染 |

### 真实 git repo 测试

```python
def test_pipeline_with_real_git_repo(tmp_path):
    project = tmp_path / "java-with-git"
    shutil.copytree(FIXTURES_DIR / "java", project)
    
    # 用隔离的 env 避免开发者的 ~/.gitconfig 影响
    env = {
        "GIT_AUTHOR_NAME": "tester",
        "GIT_AUTHOR_EMAIL": "tester@example.com",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "HOME": str(tmp_path),
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    subprocess.run(["git", "init", "-q", "-b", "main", str(project)], env=env)
    subprocess.run(["git", "-C", str(project), "add", "-A"], env=env)
    subprocess.run(
        ["git", "-C", str(project), "commit", "-q",
         "--no-gpg-sign", "-m", "添加 订单 模块基线"],
        env=env,
    )
    
    rc = cli_main([str(project), "--output", str(tmp_path / "out")])
    # ...
```

**关键**：用 `GIT_CONFIG_GLOBAL=/dev/null` 隔离开发者本地 git 签名/hook 配置。这让 `core/git.py` 从 14% 跳到 91% 覆盖。

## Layer 3: Snapshot 集成测试

### 设计

```
tests/
├── fixtures/<name>/        ← 输入：迷你项目源码（6 个）
└── golden/<name>/          ← 期望：完整 BCL 输出树（machine-portable）
```

测试逻辑：
```python
def test_fixture_matches_golden(fixture_name, tmp_path):
    project = FIXTURES_DIR / fixture_name
    golden = GOLDEN_DIR / fixture_name
    actual = tmp_path / fixture_name
    
    # 走 subprocess，保证 process isolation
    subprocess.run([sys.executable, str(SCRIPT_PATH), str(project),
                    "--output", str(actual), "--no-git"])
    
    diff = compare(golden, actual, project_dir=project, output_dir=actual)
    if diff.has_changes():
        pytest.fail(render_diff(diff, max_lines_per_file=30))
```

### 关键设计：machine-portable golden

**问题**：scanner 在 `generation_report.md` / `inventory.json` 里嵌入了绝对路径（`/Users/code_2026/...`）。如果直接 `cp` 当 golden，CI 跑会失败。

**方案**：`freeze_actual_as_golden()` 在拷贝时替换：
- `<PROJECT_DIR>` 占位符替换项目绝对路径
- `<OUTPUT_DIR>` 占位符替换输出目录绝对路径

compare 时：
- golden 是 normalized 形式（已含占位符）
- actual 在比较时用 normalize() 即时替换

结果：6 个 golden 跨任何机器都能跑通。`grep -r /Users/ tests/golden/` 返回 0 行。

### 6 个 fixture

| Fixture | 栈 | 主要测试目标 |
| --- | --- | --- |
| `java/` | Spring Boot + RocketMQ + MyBatis + Feign | Java pipeline baseline（含 Phase 1.4 数组形 path 测例） |
| `python/` | FastAPI + SQLAlchemy + Celery + DRF + APScheduler | Python plugin + Django CBV |
| `go/` | Gin + GORM + cron | Go plugin + `func (T) TableName()` |
| `typescript/` | NestJS + TypeORM + BullMQ + Prisma | TS plugin + Prisma schema |
| `kotlin-ktor/` | Ktor + Exposed | Ktor routing DSL 状态机 |
| `mixed/` | Java + TS Monorepo | Phase 4 cross-cutting 合并 ✨ |

`mixed/` fixture 的两个子目录：
- `backend-java/`：Spring + RocketMQ + Feign
- `frontend-ts/`：NestJS + TypeORM + BullMQ

根目录无 build manifest → 强制走自动检测 → 两个 plugin 都被识别和执行。

## 覆盖率最终成绩

```
code2wiki/cli.py                     54     9    84%
code2wiki/core/cross_cutting.py      47     0   100%   ← Phase 4 新增
code2wiki/core/detect.py             47     5    89%
code2wiki/core/domain.py            119    15    87%
code2wiki/core/git.py                85     8    91%
code2wiki/core/io.py                 81    18    78%
code2wiki/core/markdown.py           25     1    96%
code2wiki/core/models.py            116     0   100%
code2wiki/core/registry.py           32     9    72%
code2wiki/core/writers.py           388    77    80%
code2wiki/plugins/base.py            24    24     0%   ← Protocol class
code2wiki/plugins/language_go.py    264    61    77%
code2wiki/plugins/language_java.py  696   165    76%
code2wiki/plugins/language_kotlin.py  295  47    84%
code2wiki/plugins/language_python.py  411  78    81%
code2wiki/plugins/language_typescript.py 356 77   78%
─────────────────────────────────────────────────────────
TOTAL                                   3043   594    80%
```

**满足 G1 闸门要求**（≥ 80%）。

### 未覆盖部分的来源

- `plugins/base.py` 0%：Protocol class 没有可执行代码
- 各 plugin 76-84%：错误路径、Spring vs Ktor dispatch 罕见分支
- `core/registry.py` 72%：lazy loader 失败分支（缺失模块的 fallback）
- `core/io.py` 78%：encoding fallback、auxiliary path 边界

这些都是非关键路径。继续提升需要：
- mock 缺失的 plugin 模块测 registry 错误
- 注入坏 encoding 测 io fallback
- 投入产出比降低，不强求

## 添加新测试的指南

### 新语言插件

```python
# 1. 加 fixture: tests/fixtures/rust/
#    含 Cargo.toml + src/main.rs + 几个 module

# 2. 加 plugin: plugins/language_rust.py

# 3. 加单测: tests/test_rust_patterns.py
#    - 关键 regex 的正反样本
#    - 框架识别（actix-web / rocket / axum）

# 4. 加 in-process 集成测试参数化项
#    tests/fixtures/rust 会被自动 pick up（fixture_name fixture）

# 5. 生成 golden:
python3 -m code2wiki.tests.snapshot freeze \
    code2wiki/tests/golden/rust \
    /tmp/initial-rust-output \
    --project code2wiki/tests/fixtures/rust

# 6. 跑测试确认绿
python3 -m pytest code2wiki/tests/test_snapshot.py -v
```

### 新 cross-cutting 类型

```python
# 1. 在 plugin 的 _generate_cross_cutting 里 add_cross_cutting:
add_cross_cutting(
    name="observability",   # 新文件名
    title="可观测性",
    body=...,
    language="rust",
    language_label="Rust (actix-web)",
)

# 2. 单语言 fixture: 重新 freeze golden
python3 -m code2wiki.tests.snapshot freeze ...

# 3. 多语言 fixture: 验证合并行为
#    test_emit_two_contributors_creates_merged_file 已经覆盖通用合并逻辑
```

### 新 extras key

```python
# 1. core/models.py 加常量:
EXTRAS_NEW_THING = "new_thing"

# 2. plugins/base.py docstring 加说明

# 3. plugin 写入:
info.extras[EXTRAS_NEW_THING] = ...

# 4. writer 读取:
things = info.extras.get(EXTRAS_NEW_THING, [])

# 5. 单测 test_models.py 加常量稳定性测试:
@pytest.mark.parametrize("constant,expected", [
    (EXTRAS_NEW_THING, "new_thing"),
    ...
])
```

## 一键运行所有测试

```bash
cd scripts
python3 -m pytest code2wiki/tests/ \
  --cov=code2wiki.core \
  --cov=code2wiki.plugins \
  --cov=code2wiki.cli \
  --cov-report=term -v

# 期望：212 passed, 80% 总覆盖率
```
