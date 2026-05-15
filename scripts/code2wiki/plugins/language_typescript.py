"""TypeScript / JavaScript scanner plugin (NestJS / Express / TypeORM / Prisma).

Regex-based, zero runtime deps. Produces ``JavaFileInfo`` records.
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
    EXTRAS_MQ_ROLE,
    EXTRAS_PRISMA_MODELS,
    FileInfo,
    GitContext,
    JavaFileInfo,
    MQ_ROLE_CUSTOM_CONSUMER,
    ProjectContext,
)


TS_SUFFIXES = {".ts", ".tsx", ".js", ".mjs"}
PRISMA_SUFFIXES = {".prisma"}


# ──────────────────────────────────────────────────────────────────────────────
# Prisma schema parser
# ──────────────────────────────────────────────────────────────────────────────

# A Prisma model block: `model Name { ... }` (single line opens, multi-line body).
# Tolerates leading whitespace (indented schemas) but anchors to line-start so we
# do not accidentally pick up a `model` token inside a doc comment.
PRISMA_MODEL_RE = re.compile(
    r"^[ \t]*model[ \t]+(\w+)[ \t]*\{([^{}]*)\}",
    re.MULTILINE | re.DOTALL,
)

# Inside a model block: `@@map("table_name")` overrides the default table name
PRISMA_MAP_RE = re.compile(r"@@map\s*\(\s*[\"']([^\"']+)[\"']\s*\)")

# Field detection: `<name> <Type>[?] [...attrs]`
PRISMA_FIELD_RE = re.compile(
    r"^\s*([a-zA-Z_]\w*)\s+([A-Za-z_]\w*)(\?|\[\])?",
    re.MULTILINE,
)


def parse_prisma_schema(text: str) -> list[dict]:
    """Parse a ``schema.prisma`` file into a list of model dicts.

    Returns a list of ``{name, table, fields: [{name, type}], path}``.
    The ``table`` key honours ``@@map("...")`` if present, otherwise falls
    back to the model name (which is Prisma's default behavior in the
    absence of an explicit ``@@map``).

    Triple-slash doc-comments and inline ``//`` comments are stripped before
    field extraction so they don't pollute the field list.
    """
    if "model " not in text:
        return []

    # Strip comments so they don't match the field/model regex. Order matters:
    # block comments are stripped FIRST so that a commented-out
    # `/* model Foo { ... } */` block does not falsely register as a model.
    cleaned = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"//[^\n]*", "", cleaned)

    models: list[dict] = []
    for m in PRISMA_MODEL_RE.finditer(cleaned):
        name = m.group(1)
        body = m.group(2)

        # Default table is the model name itself.
        table = name
        map_m = PRISMA_MAP_RE.search(body)
        if map_m:
            table = map_m.group(1)

        fields: list[dict] = []
        for fm in PRISMA_FIELD_RE.finditer(body):
            fname, ftype = fm.group(1), fm.group(2)
            # Skip Prisma block-level directives that look like fields.
            if fname.startswith("@@") or fname in {"model", "enum", "type"}:
                continue
            fields.append({"name": fname, "type": ftype + (fm.group(3) or "")})

        models.append({"name": name, "table": table, "fields": fields})

    return models


# ── Regex ─────────────────────────────────────────────────────────────────────

NEST_CTRL_RE = re.compile(r"@Controller\s*\(\s*(?:['\"]([^'\"]*)['\"])?\s*\)")
NEST_METHOD_RE = re.compile(r"@(Get|Post|Put|Delete|Patch|Options|Head)\s*\(\s*(?:['\"]([^'\"]*)['\"])?\s*\)")
NEST_INJECTABLE_RE = re.compile(r"@Injectable\s*\(")
NEST_MODULE_RE = re.compile(r"@Module\s*\(")
EXPRESS_ROUTE_RE = re.compile(r"\b(?:app|router|\w+Router)\.(get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]")

TYPEORM_ENTITY_RE = re.compile(r"@Entity\s*\(\s*(?:\{[^}]*name\s*:\s*['\"]([^'\"]+)['\"]|['\"]([^'\"]+)['\"])?")
TYPEORM_COLUMN_RE = re.compile(r"@Column\s*\(")
TS_CLASS_RE = re.compile(r"\b(?:export\s+)?(?:abstract\s+)?class\s+(\w+)")
TS_DECORATOR_RE = re.compile(r"@(\w+)")
TS_METHOD_RE = re.compile(r"^\s+(?:public|private|protected|async|static|\s)*\s+(\w+)\s*\(([^)]*)\)\s*(?::\s*([\w<>\[\], \|]+))?")
BULL_PROCESS_RE = re.compile(r"@Process\s*\(\s*(?:['\"]([^'\"]+)['\"])?\s*\)")
CRON_RE = re.compile(r"@Cron\s*\(\s*['\"]([^'\"]+)['\"]")

PKG_DEP_RE = re.compile(r'"((?:@[\w\-]+/)?[\w\-]+)"\s*:\s*"[^"]+"')

TRANSACTION_RE = re.compile(r"\b(?:@Transaction|transaction\(|manager\.transaction|getManager\(\)\.transaction)")
LOCK_RE = re.compile(r"\b(?:Mutex|Semaphore|asyncMutex|setImmediate|setLock)")
CACHE_RE = re.compile(r"\b(?:CacheModule|@Cache|cacheManager\.|redis\.)")

TS_TECH_DIRS = {"src", "app", "lib", "tests", "test", "spec", "common", "shared",
                "utils", "helpers", "config", "core", "infrastructure", "domain",
                "interfaces", "modules", "models", "schemas", "dto", "dtos",
                "entities", "services", "controllers", "guards", "interceptors",
                "filters", "pipes", "decorators", "middleware", "middlewares"}


def _extract_class(text: str) -> str | None:
    m = TS_CLASS_RE.search(text)
    return m.group(1) if m else None


def _extract_decorators(text: str) -> list[str]:
    return list({m.group(1) for m in TS_DECORATOR_RE.finditer(text)})


def _extract_mappings(text: str) -> list[str]:
    paths: list[str] = []
    # NestJS: @Controller("foo") + @Get("bar") → /foo/bar
    ctrl_path = ""
    ctrl_match = NEST_CTRL_RE.search(text)
    if ctrl_match:
        ctrl_path = ctrl_match.group(1) or ""
    for m in NEST_METHOD_RE.finditer(text):
        sub = m.group(2) or ""
        full = "/" + ctrl_path.strip("/")
        if sub:
            full = (full + "/" + sub.lstrip("/")).rstrip("/") or "/"
        paths.append(full)
    for m in EXPRESS_ROUTE_RE.finditer(text):
        paths.append(m.group(2))
    return list(dict.fromkeys(paths))


def _extract_tables(text: str) -> list[str]:
    tables: list[str] = []
    for m in TYPEORM_ENTITY_RE.finditer(text):
        name = m.group(1) or m.group(2)
        if name:
            tables.append(name)
    return tables


def _extract_bullmq_tasks(text: str) -> list[str]:
    return [m.group(1) or "default" for m in BULL_PROCESS_RE.finditer(text)]


def _extract_cron(text: str) -> list[str]:
    return list(CRON_RE.findall(text))


def _extract_public_methods(text: str) -> list[dict]:
    methods: list[dict] = []
    for m in TS_METHOD_RE.finditer(text):
        name, params, ret = m.group(1), m.group(2), m.group(3)
        if not name or name in {"constructor", "if", "for", "switch", "return"}:
            continue
        if name.startswith("_") or name[0].isupper():
            continue
        methods.append({
            "name": name,
            "params": params.strip(),
            "return_type": (ret or "-").strip(),
            "signature": f"{name}({params.strip()}){': ' + ret if ret else ''}",
        })
        if len(methods) >= 20:
            break
    return methods


def _risk_signals(text: str) -> list[str]:
    s: list[str] = []
    if TRANSACTION_RE.search(text):
        s.append("事务边界")
    if LOCK_RE.search(text):
        s.append("并发原语")
    if CACHE_RE.search(text):
        s.append("缓存读写")
    if "async " in text or "await " in text:
        s.append("async/await 路径")
    return s


def _infer_role(path: Path, text: str, class_name: str | None, decorators: list[str],
                mappings: list[str], tables: list[str], bull_tasks: list[str], cron_jobs: list[str]) -> str:
    fname = path.name.lower()
    parts_lower = "/".join(p.lower() for p in path.parts)

    if mappings:
        return "controller"
    if bull_tasks:
        return "mq-consumer"
    if cron_jobs:
        return "scheduler"
    if tables:
        return "entity"
    if "Injectable" in decorators and class_name:
        return "service"
    if "Module" in decorators:
        return "config"
    if fname.endswith(".controller.ts") or "/controllers/" in parts_lower:
        return "controller"
    if fname.endswith(".service.ts") or "/services/" in parts_lower:
        return "service"
    if fname.endswith(".repository.ts") or "/repositories/" in parts_lower:
        return "repository"
    if fname.endswith(".entity.ts") or "/entities/" in parts_lower:
        return "entity"
    if fname.endswith(".dto.ts") or fname.endswith(".schema.ts") or "/dto/" in parts_lower:
        return "dto"
    if fname.endswith(".module.ts"):
        return "config"
    if fname.endswith(".guard.ts") or "/guards/" in parts_lower:
        return "config"
    if "client" in fname or "/clients/" in parts_lower:
        return "external-client"
    if class_name:
        return "service"
    return "support"


def analyze_typescript_file(path: Path, root: Path) -> JavaFileInfo:
    text = read_text(path)
    class_name = _extract_class(text)
    decorators = _extract_decorators(text)
    mappings = _extract_mappings(text)
    tables = _extract_tables(text)
    bull_tasks = _extract_bullmq_tasks(text)
    cron_jobs = _extract_cron(text)
    module = _ts_module_path(path, root)

    role = _infer_role(path, text, class_name, decorators, mappings, tables, bull_tasks, cron_jobs)
    domain = infer_domain(path, root, module, class_name, mappings, tables)
    if domain == "unknown":
        domain = _ts_path_to_domain(path, root) or "unknown"

    extras: dict = {}
    if bull_tasks:
        extras[EXTRAS_MQ_ROLE] = MQ_ROLE_CUSTOM_CONSUMER

    return JavaFileInfo(
        path=rel(path, root),
        language="typescript",
        package=module,
        class_name=class_name,
        annotations=decorators,
        role=role,
        domain=domain,
        mappings=mappings,
        tables=tables,
        mq_listeners=bull_tasks,
        scheduled=cron_jobs,
        risk_signals=_risk_signals(text),
        public_methods=_extract_public_methods(text),
        extras=extras,
    )


def _ts_module_path(path: Path, root: Path) -> str | None:
    try:
        rel_path = path.relative_to(root)
    except ValueError:
        return None
    parts = [p for p in rel_path.parts]
    if parts:
        parts[-1] = re.sub(r"\.(tsx?|jsx?|mjs)$", "", parts[-1])
    return "/".join(parts)


def _ts_path_to_domain(path: Path, root: Path) -> str | None:
    try:
        parts = list(path.relative_to(root).parts)
    except ValueError:
        return None
    for part in parts:
        cleaned = re.sub(r"\.(tsx?|jsx?|mjs)$", "", part)
        if cleaned in TS_TECH_DIRS:
            continue
        if cleaned.endswith((".controller", ".service", ".module", ".dto",
                              ".entity", ".guard", ".repository", ".schema")):
            cleaned = cleaned.rsplit(".", 1)[0]
        token = normalize_domain(cleaned)
        if token != "unknown":
            return token
    return None


def _analyze_prisma_file(path: Path, root: Path) -> JavaFileInfo | None:
    """Build a synthetic FileInfo that exposes Prisma models as entity tables.

    Returns None if the file contains no model blocks (e.g. provider-only
    schemas, generator-only schemas).
    """
    text = read_text(path)
    models = parse_prisma_schema(text)
    if not models:
        return None

    tables = [m["table"] for m in models]
    first_model = models[0]["name"]

    # Build a class_doc that lists every model + its table for db_map.md.
    summary_lines = [f"Prisma models ({len(models)}): "
                       + ", ".join(f"{m['name']}→{m['table']}" for m in models)]
    class_doc = "\n".join(summary_lines)[:200]

    domain = path_to_prisma_domain(path, root, models)

    return JavaFileInfo(
        path=rel(path, root),
        language="typescript",
        package="prisma",
        class_name=first_model,
        annotations=["@@map"] if any(m["table"] != m["name"] for m in models) else [],
        role="entity",
        domain=domain,
        tables=tables,
        class_doc=class_doc,
        extras={EXTRAS_PRISMA_MODELS: models},
    )


def path_to_prisma_domain(path: Path, root: Path, models: list[dict]) -> str:
    """Domain for a Prisma schema file.

    Strategy:
      1. Try business-meaningful path segments (skip ``prisma`` / ``schema`` /
         standard TS tech dirs).
      2. Fall back to the first **model name** (e.g. ``User``), not the table
         name — model names are PascalCase business concepts whereas tables
         frequently carry prefixes like ``t_`` / ``tbl_`` that don't normalize
         to readable domain names.
    """
    try:
        parts = list(path.relative_to(root).parts)
    except ValueError:
        parts = []
    for part in parts:
        cleaned = re.sub(r"\.(prisma)$", "", part)
        if cleaned in TS_TECH_DIRS or cleaned == "prisma" or cleaned == "schema":
            continue
        token = normalize_domain(cleaned)
        if token != "unknown":
            return token
    # Fall back to first model name (business-friendly).
    if models:
        token = normalize_domain(models[0]["name"])
        if token != "unknown":
            return token
    return "unknown"


def _parse_package_json(paths: list[Path]) -> list[dict]:
    deps: list[dict] = []
    for path in paths:
        text = read_text(path)
        m = re.search(r'"(?:dependencies|devDependencies)"\s*:\s*\{([^}]*)\}', text)
        if not m:
            continue
        for dm in PKG_DEP_RE.finditer(m.group(1)):
            deps.append({"name": dm.group(1), "source": path.name})
    return deps


def _build_context(deps: list[dict]) -> ProjectContext:
    names = {d["name"].lower() for d in deps}
    ctx = ProjectContext(dependencies=deps)
    if any(n.startswith("@nestjs/") for n in names) or "@nestjs/core" in names:
        ctx.rpc_framework_name = "NestJS"
    if "express" in names:
        ctx.rpc_framework_name = ctx.rpc_framework_name or "Express"
    if "typeorm" in names:
        ctx.has_jpa = True
    if "@prisma/client" in names or "prisma" in names:
        ctx.has_mybatis = True
    if "bullmq" in names or "bull" in names:
        ctx.mq_framework_name = "BullMQ"
    if "ioredis" in names or "redis" in names:
        ctx.has_redis = True
    if any("cron" in n or "schedule" in n for n in names):
        ctx.has_xxljob = True
    return ctx


class TypescriptPlugin:
    name = "typescript"
    display_name = "TypeScript / JavaScript (NestJS/Express)"

    def file_extensions(self) -> frozenset[str]:
        return frozenset(TS_SUFFIXES)

    def build_manifests(self) -> frozenset[str]:
        return frozenset({"package.json", "tsconfig.json"})

    def fingerprint(self, root: Path) -> int:
        score = 0
        if (root / "package.json").exists():
            score += 10
        if (root / "tsconfig.json").exists():
            score += 5
        return score

    def run_pipeline(self, args: argparse.Namespace) -> int:
        from code2wiki.core.io import set_force_overwrite
        set_force_overwrite(args.force)

        project = args.project.resolve()
        output = (args.output.resolve() if args.output
                  else project / ".code2wiki" / "business-context-layer")
        output.mkdir(parents=True, exist_ok=True)

        all_files = list(iter_files(project, args.max_files))
        ts_files = [p for p in all_files if p.suffix in TS_SUFFIXES]
        pkg_files = [p for p in all_files if p.name == "package.json"]
        prisma_files = [p for p in all_files if p.suffix in PRISMA_SUFFIXES]
        from code2wiki.core.writers import extract_auxiliary_summary
        auxiliary_items = [extract_auxiliary_summary(path, project) for path in iter_auxiliary_files(project)]

        deps = _parse_package_json(pkg_files)
        ctx = _build_context(deps)

        print(f"[SCAN] Files: {len(all_files)}, TS/JS: {len(ts_files)}, deps: {len(deps)}")
        print(f"[SCAN] Framework: {ctx.rpc_framework_name or 'unknown'}, "
              f"MQ: {ctx.mq_framework_name or 'none'}, Redis: {ctx.has_redis}, "
              f"ORM: {'TypeORM' if ctx.has_jpa else ('Prisma' if ctx.has_mybatis else 'none')}")

        infos = [analyze_typescript_file(p, project) for p in ts_files]
        # Synthesize a FileInfo per Prisma schema so models surface in db_map.
        for prisma_path in prisma_files:
            prisma_info = _analyze_prisma_file(prisma_path, project)
            if prisma_info is not None:
                infos.append(prisma_info)
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

        _write_overview(output, project, ctx, ts_files, pkg_files,
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
            "language": "typescript",
            "summary": {
                "total_files_scanned": len(all_files),
                "ts_files": len(ts_files),
                "build_files": len(pkg_files),
                "auxiliary_knowledge_files": len(auxiliary_items),
                "domain_count": len(domain_counter),
                "dependencies": len(deps),
            },
            "project_context": {
                "rpc_framework": ctx.rpc_framework_name,
                "mq_framework": ctx.mq_framework_name,
                "has_redis": ctx.has_redis,
                "has_typeorm": ctx.has_jpa,
                "has_prisma": ctx.has_mybatis,
            },
            "domains": domain_counter.most_common(),
            "roles": role_counter.most_common(),
            "build_files": [rel(p, project) for p in pkg_files],
        }
        write(output / "inventory.json", json.dumps(inventory, ensure_ascii=False, indent=2))

        write(output / "generation_report.md", f"""# Generation Report

## 生成结果

- 输出目录：`{output}`
- 语言：TypeScript/JavaScript ({ctx.rpc_framework_name or '未识别框架'})
- 源文件数：{len(ts_files)}
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
        print(f"[OK] TS: {len(ts_files)}, Domains: {len(grouped)}, Output files: {output_count}")
        return 0


def _write_overview(output, project, ctx, ts_files, build_files, domain_counter,
                     role_counter, top_domains, top_n):
    tech = []
    if ctx.rpc_framework_name:
        tech.append(ctx.rpc_framework_name)
    if ctx.mq_framework_name:
        tech.append(ctx.mq_framework_name)
    if ctx.has_jpa:
        tech.append("TypeORM")
    if ctx.has_mybatis:
        tech.append("Prisma")
    if ctx.has_redis:
        tech.append("Redis")
    if ctx.has_xxljob:
        tech.append("Scheduler")

    write(output / "00_project_overview.md", f"""# Project Overview

## 基本信息

- 项目路径：`{project}`
- 语言：TypeScript / JavaScript
- 源文件数：{len(ts_files)}
- 构建文件：{", ".join(rel(p, project) for p in build_files) or "未发现"}

## 技术栈

{", ".join(tech) if tech else "未识别"}

## 关键数字

| 维度 | 数量 |
| --- | --- |
| Controller / Route (API 入口) | {role_counter.get("controller", 0)} |
| Service / Injectable | {role_counter.get("service", 0)} |
| Repository | {role_counter.get("repository", 0)} |
| Entity / Schema | {role_counter.get("entity", 0)} |
| BullMQ Consumer | {role_counter.get("mq-consumer", 0)} |
| Cron Scheduler | {role_counter.get("scheduler", 0)} |
| DTO | {role_counter.get("dto", 0)} |

## 候选业务域

{md_table(["业务域候选", "代码文件数"], [[d, str(domain_counter[d])] for d in top_domains], top_n)}
""")


def _generate_cross_cutting(output: Path, infos: list[FileInfo], ctx: ProjectContext) -> None:
    """Register TypeScript/JS cross-cutting contributions (Phase 4)."""
    from code2wiki.core.cross_cutting import add_cross_cutting
    sub = []
    if ctx.rpc_framework_name:
        sub.append(ctx.rpc_framework_name)
    if ctx.mq_framework_name:
        sub.append(ctx.mq_framework_name)
    if ctx.has_jpa:
        sub.append("TypeORM")
    elif ctx.has_mybatis:  # Prisma flag
        sub.append("Prisma")
    label = "TypeScript (" + " / ".join(sub) + ")" if sub else "TypeScript"

    mq_rows = []
    for info in infos:
        if info.is_mq_consumer_custom:
            mq_rows.append([info.class_name or info.package or "-",
                            ", ".join(info.mq_listeners), info.domain, info.path])
    add_cross_cutting(
        name="mq", title=f"队列消费 ({ctx.mq_framework_name or '未检测'})",
        body=md_table(["类", "队列/Job", "业务域", "文件"], mq_rows) + "\n",
        language="typescript", language_label=label,
    )

    sched_rows = []
    for info in infos:
        if info.role == "scheduler":
            sched_rows.append([info.class_name or info.package or "-",
                               ", ".join(info.scheduled), info.domain, info.path])
    add_cross_cutting(
        name="scheduler", title="定时任务",
        body=md_table(["类", "Cron", "业务域", "文件"], sched_rows) + "\n",
        language="typescript", language_label=label,
    )

    tx_rows = [[i.class_name or i.package or "-", i.role, i.domain, i.path]
               for i in infos if any("事务" in s for s in i.risk_signals)]
    add_cross_cutting(
        name="transaction", title="事务边界",
        body=md_table(["类", "角色", "业务域", "文件"], tx_rows) + "\n",
        language="typescript", language_label=label,
    )

    cache_rows = [[i.class_name or i.package or "-", i.role, i.domain, i.path]
                  for i in infos if any("缓存" in s for s in i.risk_signals)]
    add_cross_cutting(
        name="cache", title="缓存",
        body=md_table(["类", "角色", "业务域", "文件"], cache_rows) + "\n",
        language="typescript", language_label=label,
    )

    lock_rows = [[i.class_name or i.package or "-", i.role, i.domain, i.path]
                 for i in infos if any("并发" in s or "async" in s for s in i.risk_signals)]
    add_cross_cutting(
        name="concurrency", title="并发 / 异步",
        body=md_table(["类", "角色", "业务域", "文件"], lock_rows) + "\n",
        language="typescript", language_label=label,
    )

    add_cross_cutting(
        name="auth", title="认证 / 权限",
        body="请补充：NestJS Guards / Express middleware。\n",
        language="typescript", language_label=label,
    )
    add_cross_cutting(
        name="observability", title="可观测性",
        body="请补充：logger / metrics / tracing。\n",
        language="typescript", language_label=label,
    )


# Backward-compat alias — the public function used to be named after the
# file extension. Kept so external callers do not break on this rename.
analyze_ts_file = analyze_typescript_file

PLUGIN = TypescriptPlugin()
