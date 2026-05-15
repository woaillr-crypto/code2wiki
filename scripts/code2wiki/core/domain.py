"""Domain inference and merging.

All language-agnostic logic for mapping a source file to a business domain
candidate. The detection passes look at, in order:

  1. URL path prefixes from HTTP route mappings.
  2. Class / type name suffix stripping.
  3. Package / module path segments.
  4. Persistence table names.
  5. Filesystem path segments.

When the project produces many fragmented domains (``employee-active``,
``employee-medal``, …), :func:`merge_domains` consolidates them by shared
prefix and by a small synonym table.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


# ──────────────────────────────────────────────────────────────────────────────
# Vocabulary
# ──────────────────────────────────────────────────────────────────────────────

# Technical/scaffolding path segments that should NOT seed a business domain.
# Mirrors the legacy Java vocabulary — Phase 3 keeps these as defaults because
# every language has SOME flavour of these tokens. Plugins may extend the
# blacklist via their own ``*_TECH_SEGMENTS`` constant when calling
# :func:`infer_domain`.
TECH_SEGMENTS = {
    "api", "v1", "v2", "v3", "admin", "internal", "open", "inner", "web",
    "common", "core", "service", "services", "server", "controller", "controllers",
    "impl", "domain", "application", "infrastructure", "adapter", "client",
    "config", "configuration", "util", "utils", "framework", "dto", "vo", "bo",
    "ao", "po", "do", "request", "response", "param", "params", "model", "models",
    "entity", "entities", "mapper", "mappers", "repository", "repositories",
    "dao", "daos", "bizmapper", "bizmappers", "handler", "handlers", "processor",
    "processors", "converter", "converters", "facade", "facades", "factory",
    "factories", "context", "constant", "constants", "enums", "enum", "exception",
    "exceptions", "filter", "filters", "listener", "listeners", "event", "events",
    "message", "messages", "helper", "helpers", "support", "base", "basic",
    "basics", "rest", "test", "tests", "main", "java", "kotlin", "groovy", "src",
}

# Path prefixes that, while not strictly "technical", carry no business signal.
PATH_PREFIX_SEGMENTS = {
    "express", "management", "server", "backend", "front", "feign", "app",
}

# Class-name suffixes stripped during identifier-to-domain extraction.
# Used by :func:`class_name_to_domain` to remove ``OrderController`` →
# ``Order`` before the camel-case split.
CLASS_SUFFIXES = (
    "Controller", "ServiceImpl", "Service", "Manager", "Facade", "Handler",
    "Processor", "Repository", "Mapper", "Dao", "Client", "FeignClient", "Feign",
    "Consumer", "Listener", "JobHandler", "Job", "Task", "Scheduler", "Factory",
    "Converter", "Config", "Configuration", "Request", "Response", "DTO", "Dto",
    "VO", "BO", "AO", "PO", "DO", "Entity", "Enum", "Status", "Type",
)


# ──────────────────────────────────────────────────────────────────────────────
# Primitive normalization
# ──────────────────────────────────────────────────────────────────────────────

def normalize_domain(token: str | None) -> str:
    """Lower-case + kebab-case the input, filter technical tokens, keep up to 3 business words.

    Returns ``"unknown"`` for empty/None inputs or when every component is
    filtered out as technical noise.
    """
    if not token:
        return "unknown"
    token = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", token.strip("/"))
    token = re.sub(r"[^A-Za-z0-9_\-/]", "-", token)
    parts = [p.lower() for p in re.split(r"[/_.-]+", token) if p]
    if not parts:
        return "unknown"
    ignored = TECH_SEGMENTS | PATH_PREFIX_SEGMENTS
    meaningful = [p for p in parts if p not in ignored and not p.isdigit()]
    # Strip CRUD verb prefixes so "getOrders" / "listOrders" → "orders".
    if len(meaningful) >= 3 and meaningful[0] in {"get", "query", "select", "list", "create", "update", "delete", "batch"}:
        meaningful = meaningful[1:]
    if len(meaningful) >= 2:
        return "-".join(meaningful[:3])
    if meaningful:
        return meaningful[0]
    return "unknown"


# ──────────────────────────────────────────────────────────────────────────────
# Per-signal domain extractors
# ──────────────────────────────────────────────────────────────────────────────

def class_name_to_domain(class_name: str | None) -> str | None:
    """Strip canonical CLASS_SUFFIXES then normalise the base.

    Multi-pass so ``OrderServiceImpl`` → ``Order`` (drops ``Impl`` then
    ``Service``). Returns None when the class name is missing or normalises
    to nothing meaningful.
    """
    if not class_name:
        return None
    base = class_name
    changed = True
    while changed:
        changed = False
        for suffix in CLASS_SUFFIXES:
            if base.endswith(suffix) and len(base) > len(suffix):
                base = base[: -len(suffix)]
                changed = True
                break
    base = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", base)
    parts = [p.lower() for p in re.split(r"[-_]+", base) if p]
    ignored = TECH_SEGMENTS | {"express", "mgmt", "base", "abstract"}
    meaningful = [p for p in parts if p not in ignored and not p.isdigit()]
    if len(meaningful) >= 3:
        return "-".join(meaningful[:3])
    if len(meaningful) >= 2:
        return "-".join(meaningful)
    if meaningful:
        return meaningful[0]
    return None


# Generic-company / non-business prefixes we drop from package paths so that
# package walking surfaces the first segment that actually carries business
# meaning. Extend this set when scanning a project whose top-level package
# happens to be a brand or org name.
_GENERIC_COMPANY_PACKAGES = {
    "com", "org", "net", "cn", "io",
    "example", "demo", "company", "internal", "corp",
}


def package_to_domain(package: str | None) -> str | None:
    """Walk a dotted package and pick the last business-meaningful segment."""
    if not package:
        return None
    segments = [s.lower() for s in package.split(".")]
    business = [s for s in segments if s not in TECH_SEGMENTS and s not in PATH_PREFIX_SEGMENTS]
    business = [s for s in business if s not in _GENERIC_COMPANY_PACKAGES and not s.startswith("base")]
    if not business:
        return None
    return normalize_domain(business[-1])


def table_to_domain(tables: list[str]) -> str | None:
    """Strip common table prefixes (``t_``, ``tbl_``, ``tb_``) then normalise."""
    if not tables:
        return None
    table = tables[0]
    table = re.sub(r"^(t_|tbl_|tb_)", "", table, flags=re.IGNORECASE)
    return normalize_domain(table)


def path_to_domain(path: Path, root: Path) -> str | None:
    """First non-technical segment of the file's path relative to ``root``."""
    rel_path = path.relative_to(root).as_posix() if path.is_absolute() else path.as_posix()
    for part in rel_path.split("/"):
        low = part.lower()
        if low not in TECH_SEGMENTS and low not in PATH_PREFIX_SEGMENTS and not low.endswith(".java"):
            return normalize_domain(low)
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Composite inference
# ──────────────────────────────────────────────────────────────────────────────

def infer_domain(path: Path, root: Path, package: str | None,
                  class_name: str | None, mappings: list[str], tables: list[str]) -> str:
    """Try every signal in order; return the first that yields a non-unknown domain."""
    if mappings:
        domain = normalize_domain(mappings[0])
        if domain != "unknown":
            return domain
    for candidate in (
        class_name_to_domain(class_name),
        package_to_domain(package),
        table_to_domain(tables),
        path_to_domain(path, root),
    ):
        if candidate and candidate != "unknown":
            return candidate
    return "unknown"


# ──────────────────────────────────────────────────────────────────────────────
# Domain merging
# ──────────────────────────────────────────────────────────────────────────────

# Roots that look meaningful at first glance but are actually verbs or generic
# scaffolding — never merge fragments under these.
_MERGE_SKIP_ROOTS = {
    "get", "set", "add", "del", "put", "new", "old", "all", "has", "can",
    "save", "send", "sync", "init", "load", "stop", "open", "read",
    "change", "update", "delete", "create", "remove", "check", "clear",
    "transfer", "convert", "handle", "process", "consume", "produce",
    "common", "commons", "default", "custom", "internal", "external",
    "admin", "client", "server", "consumer", "producer", "rock", "rocketmq",
}

# Synonym groups consolidated after prefix merging. Each set merges into its
# most-frequent member.
_SYNONYM_GROUPS: list[set[str]] = [
    {"logistic", "logistics"},
    {"text", "textbook", "textbooks"},
    {"good", "goods"},
    {"gift", "gifts", "present", "presents"},
    {"complain", "complaint", "complaints"},
    {"task", "tasks"},
    {"stock", "stocks", "inventory"},
]


def merge_domains(infos: Iterable, domain_counter: Counter[str],
                   min_merge: int = 2) -> tuple[Counter[str], dict[str, str]]:
    """Consolidate fragmented domains by shared prefix and synonyms.

    Mutates ``info.domain`` on each FileInfo in place. Returns the rebuilt
    counter and a ``{old: new}`` merge map for the audit log.

    Strategy:
      1. Prefix merge: group domains whose first hyphen-segment matches and
         the group has at least ``min_merge`` members. Each member collapses
         to the root token.
      2. Synonym merge: after prefix merging, replace each member of a
         :data:`_SYNONYM_GROUPS` set with the most-frequent surviving member.
    """
    infos = list(infos)

    # Step 1: prefix merging.
    root_children: dict[str, list[str]] = defaultdict(list)
    for domain in domain_counter:
        if domain == "unknown":
            continue
        parts = domain.split("-")
        root = parts[0]
        if len(root) <= 3 or root in _MERGE_SKIP_ROOTS:
            continue
        root_children[root].append(domain)

    prefix_map: dict[str, str] = {}
    for root, children in root_children.items():
        if len(children) >= min_merge:
            for child in children:
                if child != root:
                    prefix_map[child] = root

    for info in infos:
        if info.domain in prefix_map:
            info.domain = prefix_map[info.domain]

    domain_counter = Counter(info.domain for info in infos)

    # Step 2: synonym merging — runs AFTER prefix merging so the canonical
    # root has already absorbed its fragments.
    synonym_map: dict[str, str] = {}
    for group in _SYNONYM_GROUPS:
        candidates = [(d, domain_counter.get(d, 0)) for d in group if d in domain_counter]
        if len(candidates) < 2:
            continue
        primary = max(candidates, key=lambda x: x[1])[0]
        for d, _ in candidates:
            if d != primary:
                synonym_map[d] = primary

    for info in infos:
        if info.domain in synonym_map:
            info.domain = synonym_map[info.domain]

    merge_map = {**prefix_map, **synonym_map}
    if not merge_map:
        return domain_counter, {}
    return Counter(info.domain for info in infos), merge_map
