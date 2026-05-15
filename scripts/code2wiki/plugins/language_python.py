"""Python scanner plugin (Django / FastAPI / Flask / SQLAlchemy / Celery).

Regex-based, zero runtime deps. Produces ``JavaFileInfo`` records (the schema
is currently Java-named but field-agnostic — see core.models for the alias).
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from code2wiki.core.io import (
    AUXILIARY_SUFFIXES,
    IGNORE_DIRS,
    iter_auxiliary_files,
    iter_files,
    read_text,
    rel,
    write,
)
from code2wiki.core.markdown import md_table, role_label, skill_name_from_project
from code2wiki.core.models import (
    EXTRAS_CELERY_QUEUES,
    EXTRAS_MQ_ROLE,
    FileInfo,
    GitContext,
    JavaFileInfo,
    MQ_ROLE_CUSTOM_CONSUMER,
    ProjectContext,
)
from code2wiki.core.domain import (
    class_name_to_domain,
    infer_domain,
    merge_domains,
    normalize_domain,
    package_to_domain,
    path_to_domain,
    table_to_domain,
)


# ──────────────────────────────────────────────────────────────────────────────
# File suffixes
# ──────────────────────────────────────────────────────────────────────────────

PY_SUFFIXES = {".py"}
PY_CONFIG_SUFFIXES = {".yml", ".yaml", ".toml", ".ini", ".cfg", ".env"}


# ──────────────────────────────────────────────────────────────────────────────
# Regex patterns
# ──────────────────────────────────────────────────────────────────────────────

FASTAPI_ROUTE_RE = re.compile(
    r"@(?:app|router|\w*_?router)\.(get|post|put|delete|patch|options|head)\s*\(\s*['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)
FLASK_ROUTE_RE = re.compile(
    r"@\w+\.route\s*\(\s*['\"]([^'\"]+)['\"](?:[^)]*methods\s*=\s*\[([^\]]+)\])?",
    re.MULTILINE,
)
DJANGO_PATH_RE = re.compile(
    r"\b(?:path|re_path)\s*\(\s*['\"]([^'\"]*)['\"]\s*,\s*([\w\.]+)",
    re.MULTILINE,
)
CELERY_TASK_RE = re.compile(
    r"@(?:shared_task|\w+\.task)\s*(?:\([^)]*\))?\s*\ndef\s+(\w+)",
    re.MULTILINE,
)
APSCHEDULER_RE = re.compile(
    r"@\w+\.scheduled_job\s*\([^)]*\)\s*\ndef\s+(\w+)",
    re.MULTILINE,
)
SQLA_TABLE_RE = re.compile(r"__tablename__\s*=\s*['\"](\w+)['\"]", re.MULTILINE)
DJANGO_META_DB_TABLE_RE = re.compile(
    r"class\s+Meta\s*:[\s\S]{0,400}?db_table\s*=\s*['\"](\w+)['\"]",
)
PY_CLASS_RE = re.compile(r"^class\s+(\w+)\s*(?:\(([^)]*)\))?\s*:", re.MULTILINE)

# Class-Based View base classes from Django and Django REST Framework.
# A Python class is treated as a controller if ANY of its bases (direct or
# bracketed name without the module qualifier) appears in this set.
DJANGO_CBV_BASE_CLASSES = frozenset({
    # Django generic views
    "View", "TemplateView", "RedirectView",
    "ListView", "DetailView", "FormView",
    "CreateView", "UpdateView", "DeleteView",
    "ArchiveIndexView", "YearArchiveView", "MonthArchiveView", "WeekArchiveView",
    "DayArchiveView", "TodayArchiveView", "DateDetailView",
    "LoginView", "LogoutView", "PasswordChangeView", "PasswordResetView",
    # Django REST Framework views
    "APIView",
    "GenericAPIView",
    "ListAPIView", "CreateAPIView", "RetrieveAPIView",
    "DestroyAPIView", "UpdateAPIView",
    "ListCreateAPIView", "RetrieveUpdateAPIView", "RetrieveDestroyAPIView",
    "RetrieveUpdateDestroyAPIView",
    "ViewSet", "GenericViewSet", "ReadOnlyModelViewSet", "ModelViewSet",
})
PY_DEF_RE = re.compile(r"^def\s+(\w+)\s*\(([^)]*)\)\s*(?:->\s*[\w\[\], .|]+)?\s*:", re.MULTILINE)
PY_DECORATOR_RE = re.compile(r"^\s*@([\w\.]+)", re.MULTILINE)
PY_DOCSTRING_RE = re.compile(r'^\s*(?:"""|\'\'\')([\s\S]*?)(?:"""|\'\'\')', re.MULTILINE)
PY_MODULE_DOCSTRING_RE = re.compile(r'\A\s*(?:"""|\'\'\')([\s\S]*?)(?:"""|\'\'\')')

# Async client / RPC indicators
GRPC_SERVICER_RE = re.compile(r"class\s+(\w+)\(\w*Servicer\)")
HTTPX_CALL_RE = re.compile(r"(?:httpx|requests)\.(?:get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]")

# Risk signals
TRANSACTION_RE = re.compile(r"\b(?:atomic\(|transaction\.atomic|@?transactional|with\s+(?:db\.)?transaction\.atomic|begin_nested|begin_transaction)")
LOCK_RE = re.compile(r"\b(?:Lock\(|RLock\(|Semaphore\(|asyncio\.Lock|threading\.Lock|redis\.lock)")
CACHE_RE = re.compile(r"\b(?:cache\.get|cache\.set|cache\.delete|@cache\b|@lru_cache|@cached_property)")
IDEMPOTENT_RE = re.compile(r"\bidempoten[tc]y?_key\b", re.IGNORECASE)

# Build / dependency files
REQ_LINE_RE = re.compile(r"^\s*([A-Za-z0-9_\-\.]+)\s*[><=~!]")
PYPROJECT_DEP_RE = re.compile(r'"([A-Za-z0-9_\-\.]+)\s*(?:[><=~^]|$)')

# Tech tokens that look like module path noise (mirrors Java's TECH_SEGMENTS).
PY_TECH_SEGMENTS = {
    "src", "app", "apps", "lib", "core", "common", "tests", "test", "main",
    "api", "v1", "v2", "v3", "internal", "external", "services", "service",
    "controllers", "controller", "views", "view", "routes", "routers",
    "models", "model", "schemas", "schema", "dto", "entities", "entity",
    "tasks", "jobs", "scheduler", "celery", "config", "settings",
    "utils", "helpers", "factories", "factory", "dependencies",
    "deps", "middleware", "middlewares", "exceptions", "errors", "enums",
    "constants", "consts", "types", "domain", "infrastructure", "adapter",
    "adapters", "use_cases", "usecases", "use_case", "application",
    "presentation", "interfaces", "ports",
}


# ──────────────────────────────────────────────────────────────────────────────
# Extractors
# ──────────────────────────────────────────────────────────────────────────────

def _extract_module(path: Path, root: Path) -> str | None:
    """Convert a file path under root to a dotted module path."""
    try:
        rel_path = path.relative_to(root)
    except ValueError:
        return None
    parts = list(rel_path.parts)
    if parts and parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
        if parts[-1] == "__init__":
            parts.pop()
    return ".".join(parts) if parts else None


def _extract_decorators(text: str) -> list[str]:
    return list({m.group(1) for m in PY_DECORATOR_RE.finditer(text)})


def _extract_first_class(text: str) -> tuple[str | None, str]:
    """Return (first_top_level_class_name, bases_text)."""
    m = PY_CLASS_RE.search(text)
    if not m:
        return None, ""
    return m.group(1), (m.group(2) or "").strip()


def _extract_all_bases(text: str) -> set[str]:
    """Return the set of base class names referenced by any ``class X(Bases):``
    definition in the file.

    Each base entry is stripped of module qualifier (e.g. ``generics.ListAPIView``
    → ``ListAPIView``) and of generic parameters (``Mixin[T]`` → ``Mixin``) so
    callers can do plain set membership checks against
    :data:`DJANGO_CBV_BASE_CLASSES`.
    """
    bases: set[str] = set()
    for m in PY_CLASS_RE.finditer(text):
        bases_text = (m.group(2) or "").strip()
        if not bases_text:
            continue
        # Split on commas; tolerate decorators/keyword args in parens like
        # `class X(MyMixin, ListAPIView, metaclass=...)`.
        for raw in bases_text.split(","):
            base = raw.strip()
            if not base or "=" in base:  # keyword args like metaclass=...
                continue
            # Strip module qualifier: rest.generics.ListAPIView → ListAPIView
            if "." in base:
                base = base.rsplit(".", 1)[-1]
            # Strip generic parameter: Mixin[T] → Mixin
            base = re.split(r"[\[\(]", base, maxsplit=1)[0].strip()
            if base:
                bases.add(base)
    return bases


_DJANGO_DRF_IMPORT_RE = re.compile(
    r"\b(?:from\s+(?:django|rest_framework)|import\s+(?:django|rest_framework))\b"
)


def _is_django_cbv(text: str) -> bool:
    """True if the file declares a class extending a Django/DRF view base.

    Guard against the false positive where ``"View"`` (or any equally short
    name like ``"ListView"``) happens to be a local user-defined base class
    in a non-Django file: we only accept the CBV classification if the file
    actually imports ``django`` or ``rest_framework``. Files without those
    imports cannot legitimately subclass the real CBV bases.
    """
    bases = _extract_all_bases(text)
    if not (bases & DJANGO_CBV_BASE_CLASSES):
        return False
    return bool(_DJANGO_DRF_IMPORT_RE.search(text))


def _extract_module_doc(text: str) -> str:
    m = PY_MODULE_DOCSTRING_RE.search(text)
    return (m.group(1).strip().split("\n", 1)[0] if m else "")[:200]


def _extract_mappings(text: str) -> list[str]:
    """HTTP routes from FastAPI/Flask/Django.

    Returns just path strings so downstream domain inference (shared with
    Java) treats them as paths. HTTP method enrichment can be layered on
    later through ``extras['http_methods']`` if needed.
    """
    mappings: list[str] = []
    for m in FASTAPI_ROUTE_RE.finditer(text):
        mappings.append(m.group(2))
    for m in FLASK_ROUTE_RE.finditer(text):
        mappings.append(m.group(1))
    for m in DJANGO_PATH_RE.finditer(text):
        mappings.append(m.group(1) or "/")
    return mappings


def _extract_router_prefix(text: str) -> str:
    """Pull the prefix= argument from an APIRouter(...) declaration if any."""
    m = re.search(r"APIRouter\s*\(\s*[^)]*prefix\s*=\s*['\"]([^'\"]+)['\"]", text)
    return m.group(1) if m else ""


def _extract_tables(text: str) -> list[str]:
    tables = list(SQLA_TABLE_RE.findall(text))
    tables.extend(DJANGO_META_DB_TABLE_RE.findall(text))
    return tables


def _extract_tasks(text: str) -> list[str]:
    return list(CELERY_TASK_RE.findall(text))


def _extract_scheduled(text: str) -> list[str]:
    return list(APSCHEDULER_RE.findall(text))


def _extract_public_defs(text: str) -> list[dict]:
    """Return dicts shaped like Java public_methods so core writers stay generic.

    Keys: name, return_type, params, signature.
    """
    methods: list[dict] = []
    for m in PY_DEF_RE.finditer(text):
        name, params = m.group(1), m.group(2)
        if name.startswith("_"):
            continue
        params_clean = params.strip()
        # Python lacks a Java-style return type slot; surface the type hint if present.
        full = m.group(0)
        ret = ""
        if "->" in full:
            ret = full.split("->", 1)[1].strip().rstrip(":").strip()
        methods.append({
            "name": name,
            "params": params_clean,
            "return_type": ret or "-",
            "signature": f"def {name}({params_clean})",
        })
        if len(methods) >= 20:
            break
    return methods


def _risk_signals(text: str) -> list[str]:
    signals: list[str] = []
    if TRANSACTION_RE.search(text):
        signals.append("事务边界（@atomic / transaction）")
    if LOCK_RE.search(text):
        signals.append("锁/并发原语")
    if CACHE_RE.search(text):
        signals.append("缓存读写")
    if IDEMPOTENT_RE.search(text):
        signals.append("幂等键")
    if "async def" in text:
        signals.append("async/await 异步路径")
    return signals


def _infer_role(path: Path, text: str, class_name: str | None, decorators: list[str], mappings: list[str], tables: list[str], celery_tasks: list[str]) -> str:
    fname = path.name.lower()
    parts_lower = "/".join(p.lower() for p in path.parts)

    if mappings:
        return "controller"
    # Django / DRF Class-Based Views — the class itself is the HTTP entry point.
    # Check this BEFORE table detection so that a CBV that also references a
    # model.Meta.db_table isn't mis-classified as `entity`.
    if _is_django_cbv(text):
        return "controller"
    if celery_tasks:
        return "mq-consumer"
    if "scheduled_job" in decorators or any("scheduled_job" in d for d in decorators):
        return "scheduler"
    if tables:
        return "entity"
    if fname in {"urls.py", "routes.py", "router.py"}:
        return "controller"
    if fname in {"models.py"} or "/models/" in parts_lower:
        return "entity"
    if fname in {"schemas.py", "dtos.py"} or "/schemas/" in parts_lower or "/dtos/" in parts_lower:
        return "dto"
    if fname in {"tasks.py"} or "/tasks/" in parts_lower or "/celery/" in parts_lower:
        return "mq-consumer"
    if fname in {"views.py"} or "/views/" in parts_lower:
        return "controller"
    if "service" in fname or "/services/" in parts_lower:
        return "service"
    if "repository" in fname or "/repositories/" in parts_lower or "/repository/" in parts_lower:
        return "repository"
    if "client" in fname or "/clients/" in parts_lower:
        return "external-client"
    if "config" in fname or "settings" in fname:
        return "config"
    if "enum" in fname or "status" in fname:
        return "enum"
    if class_name and class_name.endswith("Service"):
        return "service"
    if class_name and class_name.endswith(("Repository", "DAO", "Dao")):
        return "repository"
    if class_name and class_name.endswith(("DTO", "Schema")):
        return "dto"
    if class_name and class_name.endswith("Enum"):
        return "enum"
    return "service" if "def " in text else "support"


# ──────────────────────────────────────────────────────────────────────────────
# File analysis
# ──────────────────────────────────────────────────────────────────────────────

def analyze_python_file(path: Path, root: Path) -> JavaFileInfo:
    text = read_text(path)
    decorators = _extract_decorators(text)
    class_name, _bases = _extract_first_class(text)
    module = _extract_module(path, root)

    raw_mappings = _extract_mappings(text)
    prefix = _extract_router_prefix(text)
    if prefix:
        mappings = [
            (prefix.rstrip("/") + "/" + m.lstrip("/")) if not m.startswith(prefix) else m
            for m in raw_mappings
        ]
        # normalise double slashes
        mappings = [re.sub(r"//+", "/", p) for p in mappings]
    else:
        mappings = raw_mappings
    tables = _extract_tables(text)
    celery_tasks = _extract_tasks(text)
    scheduled = _extract_scheduled(text)

    role = _infer_role(path, text, class_name, decorators, mappings, tables, celery_tasks)

    # For Django CBVs, the class name (e.g. RefundListView) is a technical
    # wrapper around a business noun (Refund). Strip the full CBV suffix —
    # both the action verb (List / Detail / Create / Update / Delete /
    # Retrieve / Destroy) and the view kind (View / ViewSet / APIView) —
    # before letting class_name_to_domain seed the domain. Otherwise the
    # domain ends up as "refund-list-view" or "refund-list" rather than
    # the business-meaningful "refund".
    domain_class_name = class_name
    if class_name and role == "controller" and _is_django_cbv(text):
        stripped = re.sub(
            r"(?:List|Detail|Create|Update|Delete|Retrieve|Destroy|"
            r"ReadOnly|Generic|Model|Form|Template|Archive|Index|Year|Month|"
            r"Week|Day|Today|Date|Login|Logout|Password)*"
            r"(?:ViewSet|APIView|View)$",
            "",
            class_name,
        )
        if stripped:
            domain_class_name = stripped

    domain = infer_domain(path, root, module, domain_class_name, mappings, tables)
    if domain == "unknown":
        # Try one more pass with the python-aware path normaliser.
        domain = _python_path_to_domain(path, root) or "unknown"

    extras: dict = {}
    if celery_tasks:
        extras[EXTRAS_MQ_ROLE] = MQ_ROLE_CUSTOM_CONSUMER
        extras[EXTRAS_CELERY_QUEUES] = list(celery_tasks)

    info = JavaFileInfo(
        path=rel(path, root),
        language="python",
        package=module,
        class_name=class_name,
        annotations=decorators,
        role=role,
        domain=domain,
        mappings=mappings,
        tables=tables,
        mq_listeners=celery_tasks,
        scheduled=scheduled,
        risk_signals=_risk_signals(text),
        public_methods=_extract_public_defs(text),
        class_doc=_extract_module_doc(text),
        extras=extras,
    )
    return info


def _python_path_to_domain(path: Path, root: Path) -> str | None:
    """Pull the first non-tech segment of the file path."""
    try:
        parts = list(path.relative_to(root).parts)
    except ValueError:
        return None
    for part in parts:
        cleaned = re.sub(r"\.py$", "", part)
        if cleaned.startswith("__"):
            continue
        if cleaned in PY_TECH_SEGMENTS:
            continue
        token = normalize_domain(cleaned)
        if token != "unknown":
            return token
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Project context
# ──────────────────────────────────────────────────────────────────────────────

def _parse_requirements(paths: list[Path]) -> list[dict]:
    deps: list[dict] = []
    for path in paths:
        text = read_text(path)
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = REQ_LINE_RE.match(line + "==")  # tolerate plain "pkg"
            if m:
                deps.append({"name": m.group(1), "source": rel(path, path.parent.parent)})
            else:
                token = re.split(r"[<>=!~\s]", line, maxsplit=1)[0]
                if token:
                    deps.append({"name": token, "source": rel(path, path.parent.parent)})
    return deps


def _parse_pyproject(paths: list[Path]) -> list[dict]:
    deps: list[dict] = []
    for path in paths:
        text = read_text(path)
        for m in PYPROJECT_DEP_RE.finditer(text):
            name = m.group(1)
            if name.lower() in {"python", "name", "version", "description", "authors"}:
                continue
            deps.append({"name": name, "source": path.name})
    return deps


def _build_context(deps: list[dict]) -> ProjectContext:
    names = {d["name"].lower() for d in deps}
    ctx = ProjectContext(dependencies=deps)

    if "celery" in names:
        ctx.has_rocketmq = False
        ctx.mq_framework_name = "Celery"
    if "kombu" in names or "aio-pika" in names or "pika" in names:
        ctx.mq_framework_name = ctx.mq_framework_name or "AMQP (Kombu/Pika)"
    if "kafka-python" in names or "aiokafka" in names or "confluent-kafka" in names:
        ctx.has_kafka = True
        ctx.mq_framework_name = ctx.mq_framework_name or "Kafka"
    if "redis" in names or "aioredis" in names:
        ctx.has_redis = True
    if "sqlalchemy" in names:
        ctx.has_jpa = True  # generic ORM flag — reusing the slot
    if "django" in names:
        ctx.has_mybatis = True  # ORM slot
    if "fastapi" in names:
        ctx.rpc_framework_name = ctx.rpc_framework_name or "FastAPI"
    if "flask" in names:
        ctx.rpc_framework_name = ctx.rpc_framework_name or "Flask"
    if "grpcio" in names:
        ctx.rpc_framework_name = ctx.rpc_framework_name or "gRPC"
    if "django" in names and not ctx.rpc_framework_name:
        ctx.rpc_framework_name = "Django"
    if "apscheduler" in names:
        ctx.has_xxljob = True  # scheduler slot

    return ctx


# ──────────────────────────────────────────────────────────────────────────────
# Pipeline
# ──────────────────────────────────────────────────────────────────────────────

class PythonPlugin:
    name = "python"
    display_name = "Python (Django/FastAPI/Flask)"

    def file_extensions(self) -> frozenset[str]:
        return frozenset(PY_SUFFIXES)

    def build_manifests(self) -> frozenset[str]:
        return frozenset({"pyproject.toml", "requirements.txt", "setup.py", "manage.py"})

    def fingerprint(self, root: Path) -> int:
        score = 0
        for manifest in self.build_manifests():
            if (root / manifest).exists():
                score += 10
        return score

    def run_pipeline(self, args: argparse.Namespace) -> int:
        from code2wiki.core.io import set_force_overwrite

        set_force_overwrite(args.force)

        project = args.project.resolve()
        output = (args.output.resolve() if args.output
                  else project / ".code2wiki" / "business-context-layer")
        output.mkdir(parents=True, exist_ok=True)

        all_files = list(iter_files(project, args.max_files))
        py_files = [p for p in all_files if p.suffix in PY_SUFFIXES]
        config_files = [p for p in all_files if p.suffix in PY_CONFIG_SUFFIXES]
        req_files = [p for p in all_files if p.name == "requirements.txt"]
        pyproject_files = [p for p in all_files if p.name == "pyproject.toml"]
        build_files = [p for p in all_files if p.name in self.build_manifests()]
        auxiliary_items: list[dict[str, str]] = []
        from code2wiki.core.writers import extract_auxiliary_summary
        for aux_path in iter_auxiliary_files(project):
            auxiliary_items.append(extract_auxiliary_summary(aux_path, project))

        deps = _parse_requirements(req_files) + _parse_pyproject(pyproject_files)
        ctx = _build_context(deps)

        print(f"[SCAN] Files: {len(all_files)}, Python: {len(py_files)}, "
              f"Config: {len(config_files)}, deps: {len(deps)}")
        print(f"[SCAN] Framework: {ctx.rpc_framework_name or 'unknown'}, "
              f"MQ: {ctx.mq_framework_name or 'none'}, Redis: {ctx.has_redis}, "
              f"Scheduler: {'APScheduler' if ctx.has_xxljob else 'none'}")

        py_infos = [analyze_python_file(p, project) for p in py_files]
        domain_counter = Counter(info.domain for info in py_infos)
        role_counter = Counter(info.role for info in py_infos)

        merge_map: dict[str, str] = {}
        if not args.no_merge:
            pre = len([d for d in domain_counter if d != "unknown"])
            domain_counter, merge_map = merge_domains(py_infos, domain_counter)
            post = len([d for d in domain_counter if d != "unknown"])
            if merge_map:
                print(f"[MERGE] 域聚合：{pre} → {post} 个域（合并了 {len(merge_map)} 个碎片域）")

        top_domains = [d for d, _ in domain_counter.most_common() if d != "unknown"][:args.top_domains]

        grouped: dict[str, list[FileInfo]] = defaultdict(list)
        for info in py_infos:
            if info.domain in top_domains:
                grouped[info.domain].append(info)

        # Root skill / overview (Python-specific text — keeps writer override out of core for now).
        _write_overview(output, project, ctx, py_files, config_files, build_files,
                         domain_counter, role_counter, top_domains, args.top_domains)

        from code2wiki.core.writers import (
            build_keyword_domain_map,
            build_mermaid_domain_graph,
            generate_auxiliary_knowledge,
            generate_business_domain_map,
            generate_domain_docs,
            generate_playbooks,
            generate_root_skill,
        )

        generate_root_skill(output, project, top_domains, py_infos, grouped)

        for domain, files in grouped.items():
            generate_domain_docs(output, domain, files, ctx, [])

        generate_business_domain_map(output, domain_counter, grouped)
        generate_auxiliary_knowledge(output, project, auxiliary_items)
        _generate_python_cross_cutting(output, py_infos, ctx)
        generate_playbooks(output)

        # Git
        git_ctx = GitContext()
        if not args.no_git:
            from code2wiki.core.git import analyze_git_history, generate_git_activity
            git_ctx = analyze_git_history(project, py_infos, top_domains)
            if git_ctx.is_git_repo:
                generate_git_activity(output, git_ctx, top_domains)

        # Indexes
        _write_indexes(output, py_infos, top_domains, grouped, merge_map)

        # Inventory + report
        inventory = {
            "project": str(project),
            "output": str(output),
            "language": "python",
            "summary": {
                "total_files_scanned": len(all_files),
                "python_files": len(py_files),
                "config_files": len(config_files),
                "build_files": len(build_files),
                "auxiliary_knowledge_files": len(auxiliary_items),
                "domain_count": len(domain_counter),
                "dependencies": len(deps),
            },
            "project_context": {
                "rpc_framework": ctx.rpc_framework_name,
                "mq_framework": ctx.mq_framework_name,
                "has_redis": ctx.has_redis,
                "has_scheduler": ctx.has_xxljob,
            },
            "domains": domain_counter.most_common(),
            "roles": role_counter.most_common(),
            "build_files": [rel(p, project) for p in build_files],
        }
        write(output / "inventory.json", json.dumps(inventory, ensure_ascii=False, indent=2))

        write(output / "generation_report.md", f"""# Generation Report

## 生成结果

- 输出目录：`{output}`
- 语言：Python ({ctx.rpc_framework_name or '未识别框架'})
- Python 源文件数：{len(py_files)}
- 已生成候选业务域：{len(grouped)}
- 依赖包数：{len(deps)}
- Celery 任务数：{sum(1 for f in py_infos if f.is_mq_consumer_custom)}
- 定时任务数：{sum(1 for f in py_infos if f.role == 'scheduler')}
- 辅助知识文件：{len(auxiliary_items)} 个

## 后续 AI 富化建议

- 优先选择 `{', '.join(top_domains[:5]) or '（待识别）'}` 这些域进行 AI 富化。
- 富化时关注：路由 → service → ORM 模型 → Celery 异步任务 → 状态枚举。
""")

        if merge_map:
            merge_rows = [[old, new] for old, new in sorted(merge_map.items())]
            write(output / "domain_merge_log.md",
                  "# 域聚合日志\n\n以下碎片域已被合并到父域：\n\n"
                  + md_table(["原始域", "合并到"], merge_rows))

        output_count = sum(1 for _ in output.rglob("*.md")) + sum(1 for _ in output.rglob("*.json"))
        print(f"[OK] Business Context Layer generated at: {output}")
        print(f"[OK] Python: {len(py_files)}, Domains: {len(grouped)}, Output files: {output_count}")
        return 0


def _write_overview(output: Path, project: Path, ctx: ProjectContext, py_files, config_files, build_files,
                     domain_counter, role_counter, top_domains, top_n):
    tech_stack = []
    if ctx.rpc_framework_name:
        tech_stack.append(ctx.rpc_framework_name)
    if ctx.mq_framework_name:
        tech_stack.append(ctx.mq_framework_name)
    if ctx.has_redis:
        tech_stack.append("Redis")
    if ctx.has_xxljob:
        tech_stack.append("APScheduler")
    if ctx.has_jpa:
        tech_stack.append("SQLAlchemy")
    if ctx.has_mybatis:
        tech_stack.append("Django ORM")

    mq_count = sum(1 for f in role_counter.elements() if f == "mq-consumer")
    sched_count = role_counter.get("scheduler", 0)

    write(output / "00_project_overview.md", f"""# Project Overview

## 基本信息

- 项目路径：`{project}`
- 语言：Python
- Python 源文件数：{len(py_files)}
- 配置文件数：{len(config_files)}
- 构建文件：{", ".join(rel(p, project) for p in build_files) or "未发现"}

## 技术栈

{", ".join(tech_stack) if tech_stack else "需要从依赖与代码进一步确认"}

## 关键数字

| 维度 | 数量 |
| --- | --- |
| Controller / Route (API 入口) | {role_counter.get("controller", 0)} |
| Service (业务服务) | {role_counter.get("service", 0)} |
| Celery Task (异步消费) | {mq_count} |
| Scheduler (定时任务) | {sched_count} |
| Model / Entity (数据模型) | {role_counter.get("entity", 0)} |
| Enum (枚举/状态) | {role_counter.get("enum", 0)} |
| Repository (数据访问) | {role_counter.get("repository", 0)} |
| DTO / Schema | {role_counter.get("dto", 0)} |
| External Client | {role_counter.get("external-client", 0)} |

## 候选业务域

{md_table(["业务域候选", "代码文件数"], [[d, str(domain_counter[d])] for d in top_domains], top_n)}

## 后续人工补强

- 将候选业务域改名为真实业务术语
- 为核心业务域补齐真实流程、状态流转与风险
- 将 `需要确认` 的内容交给熟悉业务的人验证
""")


def _generate_python_cross_cutting(output: Path, infos: list[FileInfo], ctx: ProjectContext) -> None:
    """Register Python's cross-cutting contributions with the orchestrator.

    Phase 4: this function pushes ``CrossCuttingFile`` records into the
    process-level registry; the CLI emits them after all plugins finish so
    mixed-language projects produce a single merged file per concern.

    The ``output`` arg is kept for backward compatibility (and as a hint to
    plugin authors that disk writes used to happen here); it is unused.
    """
    from code2wiki.core.cross_cutting import add_cross_cutting

    parts = ["Python"]
    sub = []
    if ctx.rpc_framework_name:
        sub.append(ctx.rpc_framework_name)
    if ctx.mq_framework_name:
        sub.append(ctx.mq_framework_name)
    if ctx.has_xxljob:
        sub.append("APScheduler")
    if sub:
        parts.append("(" + " / ".join(sub) + ")")
    label = " ".join(parts)

    # MQ / Celery
    mq_rows = []
    for info in infos:
        if info.is_mq_consumer_custom or info.role == "mq-consumer":
            mq_rows.append([info.class_name or info.package or "-", ", ".join(info.mq_listeners), info.domain, info.path])
    add_cross_cutting(
        name="mq", title="消息异步消费",
        body=f"> 框架：{ctx.mq_framework_name or '未检测到'}\n\n"
             + md_table(["类/模块", "任务/Topic", "业务域", "文件"], mq_rows) + "\n",
        language="python", language_label=label,
    )

    # Scheduler
    sched_rows = []
    for info in infos:
        if info.role == "scheduler":
            sched_rows.append([info.class_name or info.package or "-",
                               ", ".join(info.scheduled) or "-", info.domain, info.path])
    add_cross_cutting(
        name="scheduler", title="定时任务",
        body=f"> 框架：{'APScheduler' if ctx.has_xxljob else '未检测到'}\n\n"
             + md_table(["类/模块", "任务名", "业务域", "文件"], sched_rows) + "\n",
        language="python", language_label=label,
    )

    # Transaction
    tx_rows = []
    for info in infos:
        if any("事务" in s for s in info.risk_signals):
            tx_rows.append([info.class_name or info.package or "-", info.role, info.domain, info.path])
    add_cross_cutting(
        name="transaction", title="事务边界",
        body=md_table(["类/模块", "角色", "业务域", "文件"], tx_rows) + "\n",
        language="python", language_label=label,
    )

    # Cache
    cache_rows = []
    for info in infos:
        if any("缓存" in s for s in info.risk_signals):
            cache_rows.append([info.class_name or info.package or "-", info.role, info.domain, info.path])
    add_cross_cutting(
        name="cache", title="缓存使用",
        body=md_table(["类/模块", "角色", "业务域", "文件"], cache_rows) + "\n",
        language="python", language_label=label,
    )

    # Lock / Concurrency
    lock_rows = []
    for info in infos:
        if any("锁" in s or "async" in s for s in info.risk_signals):
            lock_rows.append([info.class_name or info.package or "-", info.role, info.domain, info.path])
    add_cross_cutting(
        name="concurrency", title="并发/锁",
        body=md_table(["类/模块", "角色", "业务域", "文件"], lock_rows) + "\n",
        language="python", language_label=label,
    )

    # Auth (placeholder — needs deeper detection)
    add_cross_cutting(
        name="auth", title="认证 / 权限",
        body="请补充：FastAPI Dependency / Django middleware / Flask before_request 检查。\n",
        language="python", language_label=label,
    )

    add_cross_cutting(
        name="observability", title="可观测性",
        body="请补充：logger / metrics / tracing 配置和落点。\n",
        language="python", language_label=label,
    )


def _write_indexes(output: Path, infos: list[FileInfo], top_domains, grouped, merge_map) -> None:
    api_rows, db_rows, code_rows, dep_rows = [], [], [], []
    for info in infos:
        for mapping in info.mappings:
            api_rows.append([mapping, info.class_name or info.package or "-", info.domain, info.path])
        for table in info.tables:
            db_rows.append([table, info.class_name or info.package or "-", info.domain, info.path])
        code_rows.append([info.class_name or info.package or "-", role_label(info.role), info.domain, info.path])

    write(output / "05_indexes" / "api_index.md",
          "# API Index\n\n" + md_table(["路径", "Controller", "业务域", "文件"], api_rows, 1000))
    write(output / "05_indexes" / "database_index.md",
          "# Database Index\n\n" + md_table(["表", "模型", "业务域", "文件"], db_rows, 1000))
    write(output / "05_indexes" / "code_entrypoint_index.md",
          "# Code Entrypoint Index\n\n" + md_table(["类/模块", "角色", "业务域", "文件"], code_rows, 2000))
    write(output / "05_indexes" / "dependency_index.md",
          "# Dependency Index\n\n（依赖关系由 AI 富化阶段补全）\n")

    write(output / "04_glossary" / "business_terms.md",
          "# 业务术语表\n\n请补充：业务术语 -> 所属业务域 -> 代码入口。\n")
    write(output / "04_glossary" / "status_codes.md",
          "# 状态码\n\n请补充：状态码/枚举 -> 含义 -> 流转约束 -> 来源文件。\n")
    write(output / "04_glossary" / "error_codes.md",
          "# 错误码\n\n请补充：错误码 -> 用户含义 -> 触发条件 -> 来源文件。\n")


PLUGIN = PythonPlugin()
