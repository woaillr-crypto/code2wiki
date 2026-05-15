"""Markdown rendering helpers (tables, role labels, naming).

These are formatting primitives that every writer reuses. Pure functions —
no I/O, no global state.
"""

from __future__ import annotations

import re
from pathlib import Path


# ──────────────────────────────────────────────────────────────────────────────
# Table rendering
# ──────────────────────────────────────────────────────────────────────────────

def md_table(headers: list[str], rows: list[list[str]], max_rows: int | None = None) -> str:
    """Render a GitHub-flavored Markdown table.

    - Returns ``"（无数据）"`` when ``rows`` is empty so empty-state sections
      remain visible to readers and CI diffing.
    - Each cell is normalised: newlines collapsed to spaces, pipes escaped,
      and truncated to 300 chars to keep BCL files scannable.
    - If ``max_rows`` is set and the input exceeds it, a footer line records
      the truncation so users know they need to read the underlying index.
    """
    if not rows:
        return "（无数据）"
    selected = rows if max_rows is None else rows[:max_rows]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in selected:
        escaped = [str(cell).replace("\n", " ").replace("|", "\\|")[:300] for cell in row]
        lines.append("| " + " | ".join(escaped) + " |")
    if max_rows is not None and len(rows) > max_rows:
        lines.append(f"\n> 仅展示前 {max_rows} 条，共 {len(rows)} 条")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Role labels — Chinese display names for the canonical role enum
# ──────────────────────────────────────────────────────────────────────────────

_ROLE_LABELS = {
    "controller": "入口 API",
    "service": "业务服务",
    "repository": "数据访问",
    "entity": "数据模型",
    "mq-consumer": "消息消费",
    "scheduler": "定时任务",
    "external-client": "外部依赖",
    "dto": "传输对象",
    "enum": "枚举/状态",
    "config": "配置",
    "cache": "缓存",
}


def role_label(role: str) -> str:
    """Map a canonical role identifier to its Chinese display label."""
    return _ROLE_LABELS.get(role, "其他")


# ──────────────────────────────────────────────────────────────────────────────
# Naming helpers
# ──────────────────────────────────────────────────────────────────────────────

def skill_name_from_project(project: Path) -> str:
    """Derive a stable slug for the project's BCL skill name.

    Used for ``business-context-layer/SKILL.md`` headers. Strips non-alphanum
    characters and collapses runs of dashes. Falls back to
    ``"java-project-business-context"`` when the slug is empty.
    """
    slug = re.sub(r"[^a-z0-9-]+", "-", project.name.lower())
    slug = re.sub(r"-+", "-", slug).strip("-") or "java-project"
    return f"{slug}-business-context"


# Tech words filtered out when extracting business vocabulary from identifiers.
_BIZ_WORD_SKIP = {
    "get", "set", "is", "do", "on", "to", "by", "the", "a", "an", "of", "in",
    "impl", "service", "controller", "handler", "consumer", "processor",
    "mapper", "dto", "vo", "bo", "request", "response", "config", "test",
    "manager", "facade", "factory", "helper", "util", "utils", "support",
    "logic", "biz", "base", "abstract", "default", "common", "internal",
}


def _extract_business_words(name: str) -> list[str]:
    """Pull business-meaningful tokens out of a CamelCase identifier.

    Splits on camel-case boundaries, lowercases via the filter, removes
    technical scaffolding words, and keeps tokens longer than 2 characters
    so 2-letter abbreviations (``IO``, ``UI``) do not flood the keyword map.
    """
    parts = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name).split()
    return [p for p in parts if p.lower() not in _BIZ_WORD_SKIP and len(p) > 2]
