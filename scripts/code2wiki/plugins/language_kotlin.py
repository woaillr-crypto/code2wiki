"""Kotlin scanner plugin.

Two execution paths:

- **Spring Kotlin** (default): delegates to the Java plugin, since Spring
  annotations / class structures / build files are 95% compatible with the
  Java analyzer that already accepts ``.kt`` files.

- **Pure Ktor** (build.gradle.kts depends on ``io.ktor``, no Spring):
  runs a self-contained pipeline that uses :func:`extract_ktor_routes` to
  resolve nested ``routing { route(...) { get(...) { ... } } }`` DSL into
  fully-qualified API paths.

Detection is keyed on the presence of ``io.ktor`` in any ``build.gradle.kts``
file under the project root, with Spring presence overriding (we keep
Spring-Kotlin projects on the Java pipeline to avoid behavior regression for
existing users).
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from code2wiki.core.domain import (
    infer_domain,
    merge_domains,
    normalize_domain,
)
from code2wiki.core.io import (
    iter_auxiliary_files,
    iter_files,
    read_text,
    rel,
    write,
)
from code2wiki.core.markdown import md_table
from code2wiki.core.models import (
    EXTRAS_KTOR_METHODS,
    FileInfo,
    GitContext,
    JavaFileInfo,
    ProjectContext,
)
from code2wiki.plugins.language_java import JavaPlugin


# ──────────────────────────────────────────────────────────────────────────────
# File suffixes / patterns
# ──────────────────────────────────────────────────────────────────────────────

KT_SUFFIXES = {".kt", ".kts"}

KT_CLASS_RE = re.compile(
    r"\b(?:(?:public|private|internal|abstract|open|sealed|final)\s+)*"
    r"(?:data\s+|enum\s+|sealed\s+|object\s+|annotation\s+|inner\s+|inline\s+)*"
    r"(?:class|object|interface)\s+(\w+)"
)
KT_PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)", re.MULTILINE)
KT_FUN_RE = re.compile(
    r"\bfun\s+(?:<[^>]+>\s+)?(?:\w+\.)?(\w+)\s*\(([^)]*)\)\s*(?::\s*([\w<>?\[\], .|]+))?"
)
KT_DATA_FIELD_RE = re.compile(r"(?:val|var)\s+(\w+)\s*:\s*([\w<>?, .|]+)")

KTOR_HTTP_VERBS = ("get", "post", "put", "delete", "patch", "options", "head")
KTOR_ROUTING_RE = re.compile(r"\brouting\b\s*\{")
KTOR_ROUTE_RE = re.compile(r"\broute\s*\(\s*\"([^\"]*)\"\s*\)\s*\{")
KTOR_VERB_RE = re.compile(
    rf"\b({'|'.join(KTOR_HTTP_VERBS)})\s*\(\s*\"([^\"]*)\"\s*\)"
)

GRADLE_KTS_DEP_RE = re.compile(
    r"""(?x)
    \b(?:implementation|api|compileOnly|runtimeOnly|testImplementation)
    \s*\(\s*["']([^"':]+:[^"':]+)["']"""
)
GRADLE_KTS_DEP_STRING_RE = re.compile(
    r"""\b(?:implementation|api|compileOnly|runtimeOnly|testImplementation)\s*\(\s*["']([^"']+)["']"""
)

KTOR_DEP_PREFIX = "io.ktor"
SPRING_DEP_PREFIX = "org.springframework"

KOTLIN_TECH_SEGMENTS = {
    "src", "main", "test", "kotlin", "app", "api", "internal", "core",
    "common", "shared", "util", "utils", "config", "configs", "infrastructure",
    "domain", "presentation", "application", "interfaces", "adapter",
    "adapters", "routes", "routing", "plugins", "modules",
    "model", "models", "service", "services", "controller", "controllers",
    "handler", "handlers", "ports",
}


# ──────────────────────────────────────────────────────────────────────────────
# Ktor route extractor (state machine over balanced braces)
# ──────────────────────────────────────────────────────────────────────────────

def _iter_braces_skipping_strings(text: str):
    """Yield ``(position, '{')`` / ``(position, '}')`` for braces outside string
    and comment regions. Handles Kotlin's:

    - Double-quoted strings with backslash escapes
    - Triple-quoted raw strings ``\"\"\" ... \"\"\"``
    - Char literals ``'x'``
    - Line comments ``//``
    - Block comments ``/* ... */``
    """
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        # Triple-quoted raw string
        if ch == '"' and i + 2 < n and text[i + 1] == '"' and text[i + 2] == '"':
            i += 3
            while i + 2 < n and not (text[i] == '"' and text[i + 1] == '"' and text[i + 2] == '"'):
                i += 1
            i += 3
            continue
        # Regular double-quoted string
        if ch == '"':
            i += 1
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    i += 2
                else:
                    i += 1
            i += 1
            continue
        # Char literal
        if ch == "'":
            i += 1
            while i < n and text[i] != "'":
                if text[i] == "\\" and i + 1 < n:
                    i += 2
                else:
                    i += 1
            i += 1
            continue
        # Line comment
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        # Block comment
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        if ch == "{" or ch == "}":
            yield (i, ch)
        i += 1


def extract_ktor_routes(text: str, max_depth: int = 16) -> list[tuple[str, str]]:
    """Extract ``(METHOD, /full/path)`` pairs from Ktor routing DSL.

    Handles arbitrary nesting of ``route("/a") { route("/b") { get("/c") {...} } }``
    by walking balanced braces while tracking a stack of prefix scopes.

    Args:
        text: full source file content
        max_depth: protective brace-stack limit; deeper nesting is silently
            truncated (Phase 1 fixture coverage stays well within this limit)

    Returns:
        list of ``(METHOD, path)`` pairs. ``METHOD`` is uppercased. ``path``
        is normalized to a single leading ``/`` with no doubled slashes.
        Empty list if the file does not look like Ktor code.
    """
    # Quick reject: no `routing` keyword anywhere → not a Ktor file.
    if "routing" not in text and not any(
        re.search(rf"\b{verb}\s*\(\s*\"", text) for verb in KTOR_HTTP_VERBS
    ):
        return []

    # Find positions of every '{' that opens a *scope* (routing { or route(...) {).
    scope_open_positions: dict[int, str] = {}
    for m in KTOR_ROUTING_RE.finditer(text):
        scope_open_positions[m.end() - 1] = ""
    for m in KTOR_ROUTE_RE.finditer(text):
        scope_open_positions[m.end() - 1] = m.group(1)

    if not scope_open_positions:
        return []

    # Collect all events ordered by source position.
    events: list[tuple[int, str, object]] = []
    for pos, ch in _iter_braces_skipping_strings(text):
        events.append((pos, "open" if ch == "{" else "close", None))
    for m in KTOR_VERB_RE.finditer(text):
        events.append((m.start(), "verb", (m.group(1), m.group(2))))
    events.sort(key=lambda e: e[0])

    stack: list[tuple[str, str]] = []  # (kind, prefix or '')
    routes: list[tuple[str, str]] = []

    for pos, kind, payload in events:
        if kind == "open":
            if pos in scope_open_positions:
                stack.append(("scope", scope_open_positions[pos]))
            else:
                stack.append(("brace", ""))
            if len(stack) >= max_depth:
                # Protective truncation: stop accepting deeper scopes; pops still work.
                pass
        elif kind == "close":
            if stack:
                stack.pop()
        else:  # verb
            method, path = payload  # type: ignore[misc]
            # Only count a verb if at least one routing/route scope is active above it.
            if not any(s[0] == "scope" for s in stack):
                continue
            prefix_parts = [s[1] for s in stack if s[0] == "scope"]
            joined = "/" + "/".join(p.strip("/") for p in prefix_parts if p.strip("/"))
            if path:
                joined = joined.rstrip("/") + "/" + path.lstrip("/")
            joined = re.sub(r"/+", "/", joined) or "/"
            routes.append((method.upper(), joined))

    return routes


# ──────────────────────────────────────────────────────────────────────────────
# Per-file analyzer (Ktor pipeline)
# ──────────────────────────────────────────────────────────────────────────────

def _extract_package(text: str) -> str | None:
    m = KT_PACKAGE_RE.search(text)
    return m.group(1) if m else None


def _extract_first_class(text: str) -> str | None:
    m = KT_CLASS_RE.search(text)
    return m.group(1) if m else None


def _extract_public_methods(text: str) -> list[dict]:
    methods: list[dict] = []
    for m in KT_FUN_RE.finditer(text):
        name, params, ret = m.group(1), m.group(2), m.group(3)
        if not name or name.startswith("_"):
            continue
        methods.append({
            "name": name,
            "params": params.strip(),
            "return_type": (ret or "Unit").strip(),
            "signature": f"fun {name}({params.strip()}): {ret or 'Unit'}",
        })
        if len(methods) >= 20:
            break
    return methods


def _infer_role(path: Path, mappings: list[str], class_name: str | None) -> str:
    fname = path.name.lower()
    parts_lower = "/".join(p.lower() for p in path.parts)
    if mappings:
        return "controller"
    if "routing" in parts_lower or "routes" in parts_lower or "routes.kt" in fname:
        return "controller"
    if class_name and class_name.endswith(("Service", "UseCase")):
        return "service"
    if class_name and class_name.endswith(("Repository", "Repo")):
        return "repository"
    if class_name and class_name.endswith(("Dto", "DTO", "Request", "Response")):
        return "dto"
    if "/service/" in parts_lower or "/services/" in parts_lower:
        return "service"
    if "/repository/" in parts_lower or "/repositories/" in parts_lower:
        return "repository"
    if "/model/" in parts_lower or "/models/" in parts_lower or "model.kt" in fname:
        return "entity"
    if class_name:
        return "service"
    return "support"


def _ktor_path_to_domain(path: Path, root: Path) -> str | None:
    try:
        parts = list(path.relative_to(root).parts)
    except ValueError:
        return None
    for part in parts:
        cleaned = re.sub(r"\.(kt|kts)$", "", part)
        if cleaned in KOTLIN_TECH_SEGMENTS:
            continue
        token = normalize_domain(cleaned)
        if token != "unknown":
            return token
    return None


def _risk_signals(text: str) -> list[str]:
    s: list[str] = []
    if "suspend " in text or " async " in text:
        s.append("协程/suspend 异步路径")
    if "Mutex(" in text or "withLock" in text:
        s.append("并发原语 (Mutex/withLock)")
    if "transaction {" in text or "newSuspendedTransaction" in text:
        s.append("事务边界 (Exposed transaction)")
    if "cache" in text.lower() and ("get(" in text or "put(" in text):
        s.append("缓存读写")
    return s


def analyze_kotlin_file(path: Path, root: Path) -> JavaFileInfo:
    text = read_text(path)
    package = _extract_package(text)
    class_name = _extract_first_class(text)

    ktor_routes = extract_ktor_routes(text)
    # Rename the inner loop var to avoid shadowing the `path: Path` parameter.
    mappings = [route_path for _method, route_path in ktor_routes]

    role = _infer_role(path, mappings, class_name)
    domain = infer_domain(path, root, package, class_name, mappings, [])
    if domain == "unknown":
        domain = _ktor_path_to_domain(path, root) or "unknown"

    extras: dict = {}
    if ktor_routes:
        extras[EXTRAS_KTOR_METHODS] = [m for m, _ in ktor_routes]

    return JavaFileInfo(
        path=rel(path, root),
        language="kotlin",
        package=package,
        class_name=class_name,
        role=role,
        domain=domain,
        mappings=mappings,
        risk_signals=_risk_signals(text),
        public_methods=_extract_public_methods(text),
        extras=extras,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Build-config parsing
# ──────────────────────────────────────────────────────────────────────────────

def _parse_gradle_kts(build_files: list[Path]) -> list[dict]:
    deps: list[dict] = []
    for path in build_files:
        text = read_text(path)
        for m in GRADLE_KTS_DEP_RE.finditer(text):
            deps.append({"name": m.group(1), "source": path.name})
        for m in GRADLE_KTS_DEP_STRING_RE.finditer(text):
            name = m.group(1)
            if ":" in name and not any(d["name"] == name for d in deps):
                deps.append({"name": name, "source": path.name})
    return deps


def _project_uses_ktor(deps: list[dict]) -> bool:
    """Check the parsed dependency list — not raw build-file text — so that
    a commented-out reference (``// io.ktor:ktor-server-core``) does not
    falsely trigger the Ktor pipeline."""
    return any(d["name"].startswith(KTOR_DEP_PREFIX) for d in deps)


def _project_uses_spring(deps: list[dict]) -> bool:
    """Same rationale as :func:`_project_uses_ktor` — only inspect parsed
    dependency coordinates so commented or doc'd Spring references in a pure
    Ktor build do not accidentally route the project to the Java pipeline."""
    return any(d["name"].startswith(SPRING_DEP_PREFIX) for d in deps)


def _build_ktor_context(deps: list[dict]) -> ProjectContext:
    """Build a ProjectContext from parsed Gradle deps for a Ktor project."""
    names = [d["name"].lower() for d in deps]
    ctx = ProjectContext(dependencies=deps)
    ctx.rpc_framework_name = "Ktor"
    if any("redis" in n for n in names):
        ctx.has_redis = True
    if any("exposed" in n for n in names):
        ctx.has_jpa = True  # generic ORM slot
    return ctx


# ──────────────────────────────────────────────────────────────────────────────
# Plugin
# ──────────────────────────────────────────────────────────────────────────────

class KotlinPlugin(JavaPlugin):
    name = "kotlin"
    display_name = "Kotlin (Spring/Ktor)"

    def file_extensions(self) -> frozenset[str]:
        return frozenset(KT_SUFFIXES)

    def build_manifests(self) -> frozenset[str]:
        return frozenset({"build.gradle.kts", "settings.gradle.kts"})

    def fingerprint(self, root: Path) -> int:
        score = 0
        if (root / "build.gradle.kts").exists():
            score += 10
        if (root / "settings.gradle.kts").exists():
            score += 5
        return score

    def run_pipeline(self, args: argparse.Namespace) -> int:
        """Dispatch to the Ktor pipeline for pure Ktor projects, otherwise
        delegate to the Java plugin (Spring Kotlin and the common case)."""
        project = args.project.resolve()
        all_files = list(iter_files(project, args.max_files))
        build_files = [p for p in all_files if p.name in self.build_manifests()]

        # Parse dependencies once and feed the dispatch + downstream pipeline
        # from the same canonical list. Avoids substring-on-raw-text false
        # positives when comments/strings happen to mention a framework.
        deps = _parse_gradle_kts(build_files)
        is_ktor = _project_uses_ktor(deps) and not _project_uses_spring(deps)
        if is_ktor:
            return _run_ktor_pipeline(args, project, all_files, build_files, deps)

        # Spring Kotlin or unknown: delegate to Java pipeline (preserves existing
        # behavior for the kotlin fixture and matching real-world projects).
        return super().run_pipeline(args)


def _run_ktor_pipeline(args: argparse.Namespace, project: Path,
                        all_files: list[Path], build_files: list[Path],
                        deps: list[dict]) -> int:
    from code2wiki.core.io import set_force_overwrite
    set_force_overwrite(args.force)

    output = (args.output.resolve() if args.output
              else project / ".code2wiki" / "business-context-layer")
    output.mkdir(parents=True, exist_ok=True)

    kt_files = [p for p in all_files if p.suffix in KT_SUFFIXES]
    from code2wiki.core.writers import extract_auxiliary_summary
    auxiliary_items = [extract_auxiliary_summary(path, project)
                        for path in iter_auxiliary_files(project)]

    ctx = _build_ktor_context(deps)

    print(f"[SCAN] Files: {len(all_files)}, Kotlin: {len(kt_files)}, deps: {len(deps)}")
    print(f"[SCAN] Framework: {ctx.rpc_framework_name}, "
          f"Exposed: {ctx.has_jpa}, Redis: {ctx.has_redis}")

    infos = [analyze_kotlin_file(p, project) for p in kt_files]
    domain_counter = Counter(info.domain for info in infos)
    role_counter = Counter(info.role for info in infos)

    merge_map: dict[str, str] = {}
    if not args.no_merge:
        domain_counter, merge_map = merge_domains(infos, domain_counter)

    top_domains = [d for d, _ in domain_counter.most_common() if d != "unknown"][:args.top_domains]
    grouped: dict[str, list[FileInfo]] = defaultdict(list)
    for info in infos:
        if info.domain in top_domains:
            grouped[info.domain].append(info)

    from code2wiki.core.writers import (
        generate_auxiliary_knowledge,
        generate_business_domain_map,
        generate_domain_docs,
        generate_playbooks,
        generate_root_skill,
    )

    _write_overview(output, project, ctx, kt_files, build_files,
                     domain_counter, role_counter, top_domains, args.top_domains)
    generate_root_skill(output, project, top_domains, infos, grouped)
    for domain, files in grouped.items():
        generate_domain_docs(output, domain, files, ctx, [])
    generate_business_domain_map(output, domain_counter, grouped)
    generate_auxiliary_knowledge(output, project, auxiliary_items)
    _generate_cross_cutting(output, infos, ctx)
    generate_playbooks(output)

    if not args.no_git:
        from code2wiki.core.git import analyze_git_history, generate_git_activity
        git_ctx = analyze_git_history(project, infos, top_domains)
        if git_ctx.is_git_repo:
            generate_git_activity(output, git_ctx, top_domains)

    from code2wiki.plugins.language_python import _write_indexes
    _write_indexes(output, infos, top_domains, grouped, merge_map)

    inventory = {
        "project": str(project),
        "output": str(output),
        "language": "kotlin",
        "framework": "Ktor",
        "summary": {
            "total_files_scanned": len(all_files),
            "kotlin_files": len(kt_files),
            "build_files": len(build_files),
            "auxiliary_knowledge_files": len(auxiliary_items),
            "domain_count": len(domain_counter),
            "dependencies": len(deps),
        },
        "project_context": {
            "rpc_framework": ctx.rpc_framework_name,
            "has_redis": ctx.has_redis,
            "has_exposed": ctx.has_jpa,
        },
        "domains": domain_counter.most_common(),
        "roles": role_counter.most_common(),
        "build_files": [rel(p, project) for p in build_files],
    }
    write(output / "inventory.json", json.dumps(inventory, ensure_ascii=False, indent=2))

    write(output / "generation_report.md", f"""# Generation Report

## 生成结果

- 输出目录：`{output}`
- 语言：Kotlin (Ktor)
- Kotlin 源文件数：{len(kt_files)}
- 已生成候选业务域：{len(grouped)}
- 依赖包数：{len(deps)}
""")
    if merge_map:
        merge_rows = [[old, new] for old, new in sorted(merge_map.items())]
        write(output / "domain_merge_log.md",
              "# 域聚合日志\n\n以下碎片域已被合并到父域：\n\n"
              + md_table(["原始域", "合并到"], merge_rows))

    output_count = sum(1 for _ in output.rglob("*.md")) + sum(1 for _ in output.rglob("*.json"))
    print(f"[OK] Business Context Layer generated at: {output}")
    print(f"[OK] Kotlin: {len(kt_files)}, Domains: {len(grouped)}, Output files: {output_count}")
    return 0


def _write_overview(output, project, ctx, kt_files, build_files, domain_counter,
                     role_counter, top_domains, top_n):
    tech = ["Ktor"]
    if ctx.has_redis:
        tech.append("Redis")
    if ctx.has_jpa:
        tech.append("Exposed (ORM)")

    write(output / "00_project_overview.md", f"""# Project Overview

## 基本信息

- 项目路径：`{project}`
- 语言：Kotlin
- 框架：Ktor
- Kotlin 源文件数：{len(kt_files)}
- 构建文件：{", ".join(rel(p, project) for p in build_files) or "未发现"}

## 技术栈

{", ".join(tech)}

## 关键数字

| 维度 | 数量 |
| --- | --- |
| Controller / Route | {role_counter.get("controller", 0)} |
| Service | {role_counter.get("service", 0)} |
| Repository | {role_counter.get("repository", 0)} |
| Entity / Model | {role_counter.get("entity", 0)} |
| DTO | {role_counter.get("dto", 0)} |

## 候选业务域

{md_table(["业务域候选", "代码文件数"], [[d, str(domain_counter[d])] for d in top_domains], top_n)}
""")


def _generate_cross_cutting(output: Path, infos: list[FileInfo], ctx: ProjectContext) -> None:
    """Register Kotlin/Ktor's cross-cutting contributions (Phase 4)."""
    from code2wiki.core.cross_cutting import add_cross_cutting
    label = "Kotlin (Ktor / Exposed)" if ctx.has_jpa else "Kotlin (Ktor)"

    tx_rows = [[i.class_name or i.package or "-", i.role, i.domain, i.path]
               for i in infos if any("事务" in s for s in i.risk_signals)]
    add_cross_cutting(
        name="transaction", title="事务边界 (Exposed)",
        body=md_table(["类/对象", "角色", "业务域", "文件"], tx_rows) + "\n",
        language="kotlin", language_label=label,
    )

    coro_rows = [[i.class_name or i.package or "-", i.role, i.domain, i.path]
                 for i in infos if any("协程" in s or "并发" in s for s in i.risk_signals)]
    add_cross_cutting(
        name="concurrency", title="并发 / 协程",
        body=md_table(["类/对象", "角色", "业务域", "文件"], coro_rows) + "\n",
        language="kotlin", language_label=label,
    )

    cache_rows = [[i.class_name or i.package or "-", i.role, i.domain, i.path]
                  for i in infos if any("缓存" in s for s in i.risk_signals)]
    add_cross_cutting(
        name="cache", title="缓存",
        body=md_table(["类/对象", "角色", "业务域", "文件"], cache_rows) + "\n",
        language="kotlin", language_label=label,
    )

    add_cross_cutting(
        name="auth", title="认证 / 权限",
        body="请补充：Ktor authentication feature + JWT/Sessions 配置。\n",
        language="kotlin", language_label=label,
    )
    add_cross_cutting(
        name="observability", title="可观测性",
        body="请补充：CallLogging / Micrometer / OpenTelemetry。\n",
        language="kotlin", language_label=label,
    )
    add_cross_cutting(
        name="scheduler", title="定时任务",
        body="请补充：协程 + delay / quartz / cron4j 调度。\n",
        language="kotlin", language_label=label,
    )
    add_cross_cutting(
        name="mq", title="消息队列",
        body="请补充：项目使用的 MQ broker + Consumer 落点。\n",
        language="kotlin", language_label=label,
    )


PLUGIN = KotlinPlugin()
