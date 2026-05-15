# 如何扩展

本文档面向后续要做扩展开发的工程师，含 3 个常见场景的完整步骤。

## 场景 1：新增语言插件

以加 Rust 支持为例（实际开发可对照 Go 插件最简洁）。

### 步骤 1：创建 fixture

```
scripts/code2wiki/tests/fixtures/rust/
├── Cargo.toml
├── src/
│   ├── main.rs
│   └── order/
│       ├── handler.rs
│       ├── service.rs
│       └── repository.rs
```

最小 fixture 6-8 个文件即可。覆盖：
- 一个 Controller-like 文件（含 HTTP 路由）
- 一个 Service 文件
- 一个 Repository / ORM 文件
- 配置文件（如 `config.toml`）

### 步骤 2：写 plugin

参考 `plugins/language_go.py` 模板：

```python
"""Rust scanner plugin (actix-web / axum / rocket)."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from code2wiki.core.domain import infer_domain, merge_domains, normalize_domain
from code2wiki.core.io import iter_auxiliary_files, iter_files, read_text, rel, write
from code2wiki.core.markdown import md_table, role_label
from code2wiki.core.models import FileInfo, GitContext, JavaFileInfo, ProjectContext


RUST_SUFFIXES = {".rs"}

# ── Regex ──
ACTIX_ROUTE_RE = re.compile(r'#\[\s*(get|post|put|delete|patch)\(\s*"([^"]+)"\s*\)\s*\]')
AXUM_ROUTE_RE  = re.compile(r'\.route\(\s*"([^"]+)"\s*,\s*(get|post|put|delete|patch)\(')
RUST_STRUCT_RE = re.compile(r"^pub\s+struct\s+(\w+)", re.MULTILINE)
RUST_FN_RE     = re.compile(r"^pub\s+(?:async\s+)?fn\s+(\w+)\s*\(", re.MULTILINE)


def _extract_mappings(text: str) -> list[str]:
    paths = []
    for m in ACTIX_ROUTE_RE.finditer(text):
        paths.append(m.group(2))
    for m in AXUM_ROUTE_RE.finditer(text):
        paths.append(m.group(1))
    return list(dict.fromkeys(paths))


def _infer_role(path: Path, mappings, class_name):
    fname = path.name.lower()
    if mappings:
        return "controller"
    if fname.endswith(("handler.rs",)):
        return "controller"
    if "service" in fname:
        return "service"
    if "repository" in fname or "repo.rs" in fname:
        return "repository"
    if "model" in fname:
        return "entity"
    return "support"


def analyze_rust_file(path: Path, root: Path) -> JavaFileInfo:
    text = read_text(path)
    mappings = _extract_mappings(text)
    m = RUST_STRUCT_RE.search(text)
    class_name = m.group(1) if m else None
    role = _infer_role(path, mappings, class_name)
    domain = infer_domain(path, root, None, class_name, mappings, [])
    return JavaFileInfo(
        path=rel(path, root),
        language="rust",
        class_name=class_name,
        role=role,
        domain=domain,
        mappings=mappings,
    )


def _parse_cargo_toml(paths: list[Path]) -> list[dict]:
    deps = []
    for path in paths:
        text = read_text(path)
        for line in text.splitlines():
            if "=" in line and "version" in line.lower():
                name = line.split("=", 1)[0].strip()
                deps.append({"name": name, "source": path.name})
    return deps


def _build_context(deps: list[dict]) -> ProjectContext:
    names = [d["name"].lower() for d in deps]
    ctx = ProjectContext(dependencies=deps)
    if any("actix-web" in n for n in names):
        ctx.rpc_framework_name = "actix-web"
    elif any("axum" in n for n in names):
        ctx.rpc_framework_name = "axum"
    if any("redis" in n for n in names):
        ctx.has_redis = True
    return ctx


class RustPlugin:
    name = "rust"
    display_name = "Rust (actix-web / axum)"

    def file_extensions(self) -> frozenset[str]:
        return frozenset(RUST_SUFFIXES)

    def build_manifests(self) -> frozenset[str]:
        return frozenset({"Cargo.toml"})

    def fingerprint(self, root: Path) -> int:
        return 10 if (root / "Cargo.toml").exists() else 0

    def run_pipeline(self, args: argparse.Namespace) -> int:
        # 参考 plugins/language_go.py 的 run_pipeline 完整实现
        # 1. 扫文件 → analyze_rust_file → list[FileInfo]
        # 2. domain_counter + merge_domains
        # 3. generate_root_skill / generate_domain_docs / generate_business_domain_map
        # 4. _generate_cross_cutting (调 add_cross_cutting)
        # 5. _write_indexes / inventory.json / generation_report.md
        ...


def _generate_cross_cutting(output: Path, infos: list[FileInfo], ctx: ProjectContext) -> None:
    """Register Rust cross-cutting contributions via the orchestrator."""
    from code2wiki.core.cross_cutting import add_cross_cutting
    label = f"Rust ({ctx.rpc_framework_name})" if ctx.rpc_framework_name else "Rust"

    # 例：tracing 中间件
    add_cross_cutting(
        name="observability", title="可观测性",
        body="请补充：tracing 配置、metrics 落点、日志格式。\n",
        language="rust", language_label=label,
    )

    # 例：tokio 异步路径
    async_files = [i for i in infos if "tokio::spawn" in i.path or "async fn" in (i.class_doc or "")]
    add_cross_cutting(
        name="concurrency", title="并发 / 异步",
        body=md_table(["类型", "角色", "业务域", "文件"],
                      [[i.class_name or "-", i.role, i.domain, i.path] for i in async_files]) + "\n",
        language="rust", language_label=label,
    )


PLUGIN = RustPlugin()
```

### 步骤 3：注册插件

```python
# core/registry.py
def _load_rust():
    from code2wiki.plugins.language_rust import PLUGIN
    return PLUGIN

PLUGIN_LOADERS = {
    "java": _load_java,
    ...
    "rust": _load_rust,      # 新增
}
```

### 步骤 4：加自动检测

```python
# core/detect.py
MANIFEST_MAP: dict[str, str] = {
    ...
    "Cargo.toml": "rust",    # 新增
}

EXT_MAP: dict[str, str] = {
    ...
    ".rs": "rust",           # 新增
}
```

### 步骤 5：单元测试

```python
# tests/test_rust_patterns.py
"""Unit tests for Rust plugin pattern detection."""

import pytest
from code2wiki.plugins.language_rust import (
    _extract_mappings,
    _infer_role,
    analyze_rust_file,
)


def test_actix_route_extraction():
    src = '#[get("/users")]\nasync fn list() {}'
    assert _extract_mappings(src) == ["/users"]


def test_axum_route_extraction():
    src = '.route("/orders", get(list_orders))'
    assert _extract_mappings(src) == ["/orders"]


# ... 等
```

### 步骤 6：冻结 golden

```bash
cd scripts
rm -rf /tmp/rust-first
python3 analyze_project.py code2wiki/tests/fixtures/rust \
    --output /tmp/rust-first --no-git

python3 -m code2wiki.tests.snapshot freeze \
    code2wiki/tests/golden/rust \
    /tmp/rust-first \
    --project code2wiki/tests/fixtures/rust \
    --output /tmp/rust-first
```

### 步骤 7：验证

```bash
# Fixture-driven snapshot 测试会自动 pick up tests/fixtures/rust
python3 -m pytest code2wiki/tests/test_snapshot.py -v
# In-process 集成测试也会自动覆盖
python3 -m pytest code2wiki/tests/test_pipeline_coverage.py -v
```

---

## 场景 2：新 Cross-cutting 类型

例：加「服务降级 / 熔断」横切关注（NestJS 用 `@CircuitBreaker`、Spring 用 `@HystrixCommand` / `@SentinelResource`）。

### 步骤 1：在 plugin 注册

在每个相关 plugin 的 `_generate_cross_cutting` / `generate_cross_cutting` 加：

```python
# language_java.py
circuit_files = [f for f in java_infos
                 if "HystrixCommand" in f.annotations or "SentinelResource" in f.annotations]
circuit_body = ""
if circuit_files:
    circuit_body += "## 概况\n\n"
    circuit_body += f"检测到 {len(circuit_files)} 个文件使用熔断装饰器。\n\n"
    circuit_body += md_table(
        ["业务域", "类", "装饰器", "文件"],
        [[f.domain, f.class_name or "-",
          ",".join(set(f.annotations) & {"HystrixCommand", "SentinelResource"}),
          f.path]
         for f in circuit_files],
        50,
    ) + "\n"
else:
    circuit_body += "未检测到显式的熔断/限流装饰器。\n"
add_cross_cutting(
    name="circuit_breaker",
    title="熔断 / 限流",
    body=circuit_body,
    language="java",
    language_label=label,
)
```

```python
# language_typescript.py
ts_circuit_files = [i for i in infos if "@CircuitBreaker" in (read_text(...) or "")]
add_cross_cutting(
    name="circuit_breaker",
    title="熔断 / 限流",     # 与 Java 保持同 title
    body=...,
    language="typescript",
    language_label=label,
)
```

### 步骤 2：编排器自动处理

无需改 `core/cross_cutting.py`。`emit_cross_cutting_files` 自动按 `name` 分桶：
- 单 plugin 命中 → 单文件输出
- 多 plugin 命中（Java + TS Monorepo）→ 自动合并为 `## Java` + `## TypeScript` 两段

### 步骤 3：更新 golden + 测试

```bash
# 跑一遍单语言 fixture
python3 analyze_project.py code2wiki/tests/fixtures/java \
    --output /tmp/java-cb-test --no-git

# 检查新文件是否产生
ls /tmp/java-cb-test/02_cross_cutting/circuit_breaker.md

# 冻结到 golden
python3 -m code2wiki.tests.snapshot freeze \
    code2wiki/tests/golden/java /tmp/java-cb-test \
    --project code2wiki/tests/fixtures/java --output /tmp/java-cb-test
```

如果 mixed fixture 也涉及该装饰器，同样重 freeze。

---

## 场景 3：新增 `extras` key

例：给 Kotlin plugin 增加 `extras["kotlin_coroutines"]` 记录 suspend function 信息。

### 步骤 1：声明常量

```python
# core/models.py
EXTRAS_KOTLIN_COROUTINES = "kotlin_coroutines"
```

### 步骤 2：更新 base.py 文档

```python
# plugins/base.py docstring
EXTRAS_KOTLIN_COROUTINES = "kotlin_coroutines"  list[dict]  Kotlin suspend fn metadata
```

### 步骤 3：plugin 写入

```python
# plugins/language_kotlin.py
suspend_fns = [{"name": m.group(1), "line": ...} for m in re.finditer(r"suspend fun (\w+)", text)]
extras = {}
if suspend_fns:
    extras[EXTRAS_KOTLIN_COROUTINES] = suspend_fns

return JavaFileInfo(..., extras=extras)
```

### 步骤 4：writer / cross-cutting 读取

```python
# 例：在 _generate_cross_cutting 中加 coroutine 表
coro_rows = []
for info in infos:
    for fn in info.extras.get(EXTRAS_KOTLIN_COROUTINES, []):
        coro_rows.append([info.class_name, fn["name"], info.domain, info.path])
add_cross_cutting(
    name="concurrency", title="并发 / 协程",
    body=md_table(["类", "suspend fn", "业务域", "文件"], coro_rows) + "\n",
    language="kotlin", language_label=label,
)
```

### 步骤 5：单元测试加常量稳定性

```python
# tests/test_models.py
@pytest.mark.parametrize("constant,expected", [
    ...
    (EXTRAS_KOTLIN_COROUTINES, "kotlin_coroutines"),     # 新增
])
def test_extras_keys_are_stable(constant, expected):
    assert constant == expected
```

---

## Tips

### 添加新 fixture 前先想清楚目标

每个 fixture 应该是「最小覆盖」的——只放需要测试的特征，不要膨胀。

参考各 fixture 的最小集：
- java/: Controller + Service + Entity + MQ Consumer + FeignClient + 数组形 path (6 文件)
- python/: FastAPI route + Service + SQLAlchemy model + Celery task + DRF CBV (8 文件)
- go/: Gin handler + Service + GORM model (3 文件)
- typescript/: NestJS controller + Service + Entity + BullMQ processor + Prisma schema (5 文件)
- kotlin-ktor/: Ktor routing + Service + Repository (4 文件)

### 写 golden 前先 review 输出

```bash
# 1. 生成到 tmp 目录
python3 analyze_project.py fixtures/new --output /tmp/new --no-git

# 2. 手动 review 输出是否合理
find /tmp/new -type f -name "*.md" | head
cat /tmp/new/05_indexes/api_index.md
cat /tmp/new/01_business_domains/order/skill.md

# 3. 确认合理后才 freeze
python3 -m code2wiki.tests.snapshot freeze ...
```

不要直接 `cp -r /tmp/new golden/new`——会嵌入机器绝对路径，CI 跑挂。必须用 `freeze` 子命令做 normalization。

### 双语言合并优先看 title

合并规则按 `name` 分桶。如果两个 plugin 都 `add_cross_cutting(name="foo", ...)`，会合并。如果其中一个写 `name="foo_v2"`，则各自独立成文件。

### 修改 core/* 时先跑全套 snapshot

```bash
python3 -m pytest code2wiki/tests/test_snapshot.py
```

8 个测试应全绿。任何一个失败说明输出漂移——要么是 bug，要么需要重 freeze golden（确认是预期变化后才能）。

---

## 一键开发环境

```bash
# 1. 安装依赖（只有测试用，运行时零依赖）
pip3 install pytest pytest-cov

# 2. 跑全套测试
cd scripts
python3 -m pytest code2wiki/tests/ \
    --cov=code2wiki.core \
    --cov=code2wiki.plugins \
    --cov=code2wiki.cli \
    -v

# 3. 跑某个 fixture 看实际输出
python3 analyze_project.py code2wiki/tests/fixtures/python \
    --output /tmp/dev-test --no-git --verbose

# 4. 对比 golden
python3 -m code2wiki.tests.snapshot compare \
    code2wiki/tests/golden/python /tmp/dev-test \
    --project code2wiki/tests/fixtures/python
```
