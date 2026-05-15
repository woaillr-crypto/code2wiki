"""Go scanner plugin (Gin / Echo / gRPC / GORM).

Regex-based, zero runtime deps. Produces ``JavaFileInfo`` records so the
language-agnostic writers stay untouched.
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
    IGNORE_DIRS,
    iter_auxiliary_files,
    iter_files,
    read_text,
    rel,
    write,
)
from code2wiki.core.markdown import md_table, role_label
from code2wiki.core.models import (
    EXTRAS_GRPC_SERVICES,
    FileInfo,
    GitContext,
    JavaFileInfo,
    ProjectContext,
)


GO_SUFFIXES = {".go"}

# ── Regex ─────────────────────────────────────────────────────────────────────

GIN_ROUTE_RE = re.compile(
    r"\b\w+\.(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s*\(\s*\"([^\"]+)\"",
)
ECHO_ROUTE_RE = re.compile(  # echo / chi / gorilla all use ServeMux-like APIs
    r"\b[\w]+\.(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s*\(\s*\"([^\"]+)\"",
)
HTTP_HANDLEFUNC_RE = re.compile(r"http\.HandleFunc\s*\(\s*\"([^\"]+)\"")

GO_PACKAGE_RE = re.compile(r"^package\s+(\w+)", re.MULTILINE)
GO_STRUCT_RE = re.compile(r"^type\s+(\w+)\s+struct\s*\{", re.MULTILINE)
GO_INTERFACE_RE = re.compile(r"^type\s+(\w+)\s+interface\s*\{", re.MULTILINE)
GO_FUNC_RE = re.compile(
    r"^func\s+(?:\(\s*\w+\s+\*?(\w+)\s*\)\s+)?(\w+)\s*\(([^)]*)\)\s*(\w*)",
    re.MULTILINE,
)
GORM_TABLE_RE = re.compile(
    # Receiver may be "func (var Type)" or "func (Type)" (no var name).
    r"func\s+\(\s*(?:\w+\s+)?\*?(\w+)\s*\)\s+TableName\s*\(\)\s*string\s*\{\s*return\s+\"(\w+)\"",
)
GRPC_REGISTER_RE = re.compile(r"\b\w+\.Register(\w+)Server\s*\(")
CRON_RE = re.compile(r"\bcron\.(?:New|AddFunc)\s*\(\s*\"([^\"]+)\"")
GO_DOC_RE = re.compile(r"(?:^//[^\n]*\n)+(?=type\s+\w+)", re.MULTILINE)

# go.mod direct deps
GOMOD_REQUIRE_RE = re.compile(r"^\s+([\w\./\-]+)\s+v[\d\.]", re.MULTILINE)

TRANSACTION_RE = re.compile(r"\b(?:db\.Transaction\(|Begin\(|tx\.Commit\(|tx\.Rollback\()")
LOCK_RE = re.compile(r"\b(?:sync\.Mutex|sync\.RWMutex|sync\.WaitGroup|atomic\.\w+)")
CACHE_RE = re.compile(r"\b(?:redis\.|cache\.Get|cache\.Set)")

GO_TECH_PKGS = {"main", "internal", "pkg", "cmd", "api", "server", "service",
                "services", "controller", "controllers", "handler", "handlers",
                "model", "models", "repo", "repository", "common", "util", "utils",
                "config", "configs", "infra", "infrastructure", "core"}


def _extract_package(text: str) -> str | None:
    m = GO_PACKAGE_RE.search(text)
    return m.group(1) if m else None


def _extract_classes(text: str) -> tuple[str | None, list[str]]:
    structs = list(GO_STRUCT_RE.findall(text))
    if structs:
        return structs[0], structs
    interfaces = list(GO_INTERFACE_RE.findall(text))
    if interfaces:
        return interfaces[0], interfaces
    return None, []


def _extract_mappings(text: str) -> list[str]:
    paths: list[str] = []
    for m in GIN_ROUTE_RE.finditer(text):
        paths.append(m.group(2))
    for m in HTTP_HANDLEFUNC_RE.finditer(text):
        paths.append(m.group(1))
    return list(dict.fromkeys(paths))


def _extract_tables(text: str) -> list[str]:
    return [m[1] for m in GORM_TABLE_RE.findall(text)]


def _extract_grpc(text: str) -> list[str]:
    return list(GRPC_REGISTER_RE.findall(text))


def _extract_cron(text: str) -> list[str]:
    return list(CRON_RE.findall(text))


def _extract_public_funcs(text: str) -> list[dict]:
    methods: list[dict] = []
    for m in GO_FUNC_RE.finditer(text):
        receiver, name, params, ret = m.group(1), m.group(2), m.group(3), m.group(4)
        if not name or name[0].islower():
            continue  # unexported
        sig = f"func{(' ('+receiver+')') if receiver else ''} {name}({params.strip()}) {ret}".strip()
        methods.append({
            "name": name,
            "params": params.strip(),
            "return_type": ret or "-",
            "signature": sig,
        })
        if len(methods) >= 20:
            break
    return methods


def _risk_signals(text: str) -> list[str]:
    s: list[str] = []
    if TRANSACTION_RE.search(text):
        s.append("事务边界（db.Transaction / tx）")
    if LOCK_RE.search(text):
        s.append("锁/并发原语")
    if CACHE_RE.search(text):
        s.append("缓存读写")
    if "go func" in text or "goroutine" in text:
        s.append("goroutine 异步路径")
    return s


def _infer_role(path: Path, text: str, struct: str | None, mappings: list[str],
                tables: list[str], grpc_services: list[str], cron_jobs: list[str]) -> str:
    parts_lower = "/".join(p.lower() for p in path.parts)
    fname = path.name.lower()

    if grpc_services or mappings:
        return "controller"
    if cron_jobs:
        return "scheduler"
    if tables:
        return "entity"
    if struct and struct.endswith(("Service", "Svc")):
        return "service"
    if struct and struct.endswith(("Repository", "Repo")):
        return "repository"
    if struct and struct.endswith(("Handler", "Controller")):
        return "controller"
    if struct and struct.endswith(("DTO", "Request", "Response", "Req", "Resp")):
        return "dto"
    if "/handler/" in parts_lower or "/handlers/" in parts_lower or "handler.go" in fname:
        return "controller"
    if "/service/" in parts_lower or "/services/" in parts_lower or "service.go" in fname:
        return "service"
    if "/repo" in parts_lower or "/repository/" in parts_lower:
        return "repository"
    if "/model/" in parts_lower or "/models/" in parts_lower or "model.go" in fname:
        return "entity"
    if "config" in fname or "/config/" in parts_lower:
        return "config"
    if "client" in fname or "/clients/" in parts_lower:
        return "external-client"
    if struct:
        return "service"
    return "support"


def analyze_go_file(path: Path, root: Path) -> JavaFileInfo:
    text = read_text(path)
    package = _extract_package(text)
    struct, _all_types = _extract_classes(text)
    mappings = _extract_mappings(text)
    tables = _extract_tables(text)
    grpc_services = _extract_grpc(text)
    cron_jobs = _extract_cron(text)

    role = _infer_role(path, text, struct, mappings, tables, grpc_services, cron_jobs)
    domain = infer_domain(path, root, package, struct, mappings, tables)
    if domain == "unknown":
        domain = _go_path_to_domain(path, root) or "unknown"

    extras: dict = {}
    if grpc_services:
        extras[EXTRAS_GRPC_SERVICES] = list(grpc_services)

    return JavaFileInfo(
        path=rel(path, root),
        language="go",
        package=package,
        class_name=struct,
        role=role,
        domain=domain,
        mappings=mappings,
        tables=tables,
        scheduled=cron_jobs,
        risk_signals=_risk_signals(text),
        public_methods=_extract_public_funcs(text),
        extras=extras,
    )


def _go_path_to_domain(path: Path, root: Path) -> str | None:
    try:
        parts = list(path.relative_to(root).parts)
    except ValueError:
        return None
    for part in parts:
        cleaned = re.sub(r"\.go$", "", part)
        if cleaned in GO_TECH_PKGS:
            continue
        token = normalize_domain(cleaned)
        if token != "unknown":
            return token
    return None


def _parse_gomod(gomod_paths: list[Path]) -> list[dict]:
    deps: list[dict] = []
    for path in gomod_paths:
        for m in GOMOD_REQUIRE_RE.finditer(read_text(path)):
            deps.append({"name": m.group(1), "source": path.name})
    return deps


def _build_context(deps: list[dict]) -> ProjectContext:
    names = {d["name"].lower() for d in deps}
    ctx = ProjectContext(dependencies=deps)
    if any("gin" in n for n in names):
        ctx.rpc_framework_name = "Gin"
    if any("echo" in n for n in names):
        ctx.rpc_framework_name = ctx.rpc_framework_name or "Echo"
    if any("grpc" in n for n in names):
        ctx.rpc_framework_name = (ctx.rpc_framework_name + ", gRPC") if ctx.rpc_framework_name else "gRPC"
    if any("gorm" in n for n in names):
        ctx.has_jpa = True
    if any("kafka" in n or "sarama" in n for n in names):
        ctx.has_kafka = True
        ctx.mq_framework_name = "Kafka"
    if any("nats" in n for n in names):
        ctx.mq_framework_name = ctx.mq_framework_name or "NATS"
    if any("redis" in n for n in names):
        ctx.has_redis = True
    if any("cron" in n for n in names):
        ctx.has_xxljob = True
    return ctx


class GoPlugin:
    name = "go"
    display_name = "Go (Gin/Echo/gRPC)"

    def file_extensions(self) -> frozenset[str]:
        return frozenset(GO_SUFFIXES)

    def build_manifests(self) -> frozenset[str]:
        return frozenset({"go.mod"})

    def fingerprint(self, root: Path) -> int:
        return 10 if (root / "go.mod").exists() else 0

    def run_pipeline(self, args: argparse.Namespace) -> int:
        from code2wiki.core.io import set_force_overwrite
        set_force_overwrite(args.force)

        project = args.project.resolve()
        output = (args.output.resolve() if args.output
                  else project / ".code2wiki" / "business-context-layer")
        output.mkdir(parents=True, exist_ok=True)

        all_files = list(iter_files(project, args.max_files))
        go_files = [p for p in all_files if p.suffix in GO_SUFFIXES]
        gomod_files = [p for p in all_files if p.name == "go.mod"]
        from code2wiki.core.writers import extract_auxiliary_summary
        auxiliary_items = [extract_auxiliary_summary(path, project) for path in iter_auxiliary_files(project)]

        deps = _parse_gomod(gomod_files)
        ctx = _build_context(deps)

        print(f"[SCAN] Files: {len(all_files)}, Go: {len(go_files)}, deps: {len(deps)}")
        print(f"[SCAN] Framework: {ctx.rpc_framework_name or 'unknown'}, "
              f"MQ: {ctx.mq_framework_name or 'none'}, Redis: {ctx.has_redis}, "
              f"GORM: {ctx.has_jpa}")

        infos = [analyze_go_file(p, project) for p in go_files]
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

        _write_overview(output, project, ctx, go_files, gomod_files,
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

        # Indexes (reuse Python-style helper)
        from code2wiki.plugins.language_python import _write_indexes
        _write_indexes(output, infos, top_domains, grouped, merge_map)

        # Inventory + report
        inventory = {
            "project": str(project),
            "output": str(output),
            "language": "go",
            "summary": {
                "total_files_scanned": len(all_files),
                "go_files": len(go_files),
                "build_files": len(gomod_files),
                "auxiliary_knowledge_files": len(auxiliary_items),
                "domain_count": len(domain_counter),
                "dependencies": len(deps),
            },
            "project_context": {
                "rpc_framework": ctx.rpc_framework_name,
                "mq_framework": ctx.mq_framework_name,
                "has_redis": ctx.has_redis,
                "has_gorm": ctx.has_jpa,
            },
            "domains": domain_counter.most_common(),
            "roles": role_counter.most_common(),
            "build_files": [rel(p, project) for p in gomod_files],
        }
        write(output / "inventory.json", json.dumps(inventory, ensure_ascii=False, indent=2))

        write(output / "generation_report.md", f"""# Generation Report

## 生成结果

- 输出目录：`{output}`
- 语言：Go ({ctx.rpc_framework_name or '未识别框架'})
- Go 源文件数：{len(go_files)}
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
        print(f"[OK] Go: {len(go_files)}, Domains: {len(grouped)}, Output files: {output_count}")
        return 0


def _write_overview(output, project, ctx, go_files, build_files, domain_counter,
                     role_counter, top_domains, top_n):
    tech = []
    if ctx.rpc_framework_name:
        tech.append(ctx.rpc_framework_name)
    if ctx.mq_framework_name:
        tech.append(ctx.mq_framework_name)
    if ctx.has_redis:
        tech.append("Redis")
    if ctx.has_jpa:
        tech.append("GORM")
    if ctx.has_xxljob:
        tech.append("cron")

    write(output / "00_project_overview.md", f"""# Project Overview

## 基本信息

- 项目路径：`{project}`
- 语言：Go
- Go 源文件数：{len(go_files)}
- 构建文件：{", ".join(rel(p, project) for p in build_files) or "未发现"}

## 技术栈

{", ".join(tech) if tech else "未识别"}

## 关键数字

| 维度 | 数量 |
| --- | --- |
| Handler (API 入口) | {role_counter.get("controller", 0)} |
| Service | {role_counter.get("service", 0)} |
| Repository | {role_counter.get("repository", 0)} |
| Entity / Model | {role_counter.get("entity", 0)} |
| Cron Scheduler | {role_counter.get("scheduler", 0)} |
| External Client | {role_counter.get("external-client", 0)} |
| DTO | {role_counter.get("dto", 0)} |

## 候选业务域

{md_table(["业务域候选", "代码文件数"], [[d, str(domain_counter[d])] for d in top_domains], top_n)}
""")


def _generate_cross_cutting(output: Path, infos: list[FileInfo], ctx: ProjectContext) -> None:
    """Register Go's cross-cutting contributions via the orchestrator (Phase 4)."""
    from code2wiki.core.cross_cutting import add_cross_cutting
    parts = ["Go"]
    sub = []
    if ctx.rpc_framework_name:
        sub.append(ctx.rpc_framework_name)
    if ctx.mq_framework_name:
        sub.append(ctx.mq_framework_name)
    label = "Go (" + " / ".join(sub) + ")" if sub else "Go"

    grpc_rows = []
    for info in infos:
        services = info.extras.get(EXTRAS_GRPC_SERVICES, [])
        for svc in services:
            grpc_rows.append([svc, info.class_name or info.package or "-", info.domain, info.path])
    add_cross_cutting(
        name="rpc_grpc", title="gRPC Services",
        body=md_table(["Service", "类型/Struct", "业务域", "文件"], grpc_rows) + "\n",
        language="go", language_label=label,
    )

    cron_rows = []
    for info in infos:
        if info.role == "scheduler":
            cron_rows.append([info.class_name or info.package or "-",
                              ", ".join(info.scheduled), info.domain, info.path])
    add_cross_cutting(
        name="scheduler", title="Cron 定时任务",
        body=md_table(["类型", "Cron 表达式", "业务域", "文件"], cron_rows) + "\n",
        language="go", language_label=label,
    )

    tx_rows = [[i.class_name or i.package or "-", i.role, i.domain, i.path]
               for i in infos if any("事务" in s for s in i.risk_signals)]
    add_cross_cutting(
        name="transaction", title="事务边界",
        body=md_table(["类型", "角色", "业务域", "文件"], tx_rows) + "\n",
        language="go", language_label=label,
    )

    lock_rows = [[i.class_name or i.package or "-", i.role, i.domain, i.path]
                 for i in infos if any("锁" in s or "goroutine" in s for s in i.risk_signals)]
    add_cross_cutting(
        name="concurrency", title="并发 / Goroutine",
        body=md_table(["类型", "角色", "业务域", "文件"], lock_rows) + "\n",
        language="go", language_label=label,
    )

    cache_rows = [[i.class_name or i.package or "-", i.role, i.domain, i.path]
                  for i in infos if any("缓存" in s for s in i.risk_signals)]
    add_cross_cutting(
        name="cache", title="缓存",
        body=md_table(["类型", "角色", "业务域", "文件"], cache_rows) + "\n",
        language="go", language_label=label,
    )

    add_cross_cutting(
        name="auth", title="认证 / 权限",
        body="请补充：中间件 + 鉴权策略。\n",
        language="go", language_label=label,
    )
    add_cross_cutting(
        name="observability", title="可观测性",
        body="请补充：log / metric / tracing 落点。\n",
        language="go", language_label=label,
    )


PLUGIN = GoPlugin()
