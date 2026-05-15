"""Cross-cutting concern writer orchestration.

Plugins contribute their cross-cutting writers (MQ, Scheduler, Cache, …) to
a process-level registry during a CLI run. After every language plugin
finishes scanning, the CLI calls :func:`emit_cross_cutting_files` which
groups writers by filename and writes the merged content to
``02_cross_cutting/*.md``.

Single-language projects emit byte-identical output (``# {title}`` followed
by the plugin's body verbatim). Mixed-language projects produce a single
file per concern with a ``## {language_label}`` section for each plugin
that contributed; the plugin's own ``##`` headings are demoted to ``###``
during the merge so the document hierarchy stays sensible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from code2wiki.core.io import write


# ──────────────────────────────────────────────────────────────────────────────
# Data model
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CrossCuttingFile:
    """One plugin's contribution to a cross-cutting concern file.

    Attributes:
      name: Output filename without extension (e.g. ``"mq"``).
      title: H1 title rendered at the top of the merged file
        (e.g. ``"MQ 消息队列"``). All contributors to the same ``name`` should
        use the SAME title; the first writer wins on conflict.
      body: Markdown body that goes below the H1 title. Should start at
        ``##`` heading level (writers must NOT emit ``# {title}`` themselves
        — the orchestrator adds it). Body may be the empty string for
        plugins that want to declare a concern but have nothing to report.
      language: Plugin id, e.g. ``"java"``, ``"python"``. Used only for
        sorting + dedup; the user-visible label is :attr:`language_label`.
      language_label: Human-readable language + stack identifier rendered as
        the ``## {label}`` section heading when multiple plugins contribute
        to the same file (e.g. ``"Java (Spring + RocketMQ)"``).
    """
    name: str
    title: str
    body: str
    language: str
    language_label: str


# ──────────────────────────────────────────────────────────────────────────────
# Process-level registry
# ──────────────────────────────────────────────────────────────────────────────

# Module-level list: simple, thread-unsafe (the CLI is single-threaded).
# Each CLI run resets this list before invoking plugins.
_REGISTERED: list[CrossCuttingFile] = []


def reset_cross_cutting() -> None:
    """Empty the registry. The CLI calls this before each scan run."""
    _REGISTERED.clear()


def add_cross_cutting(*, name: str, title: str, body: str,
                       language: str, language_label: str) -> None:
    """Register one plugin's cross-cutting contribution.

    All arguments are keyword-only to avoid positional confusion between the
    short language id and the human-readable label.
    """
    _REGISTERED.append(CrossCuttingFile(
        name=name, title=title, body=body,
        language=language, language_label=language_label,
    ))


def registered_files() -> list[CrossCuttingFile]:
    """Snapshot of the current registry (read-only view for tests)."""
    return list(_REGISTERED)


# ──────────────────────────────────────────────────────────────────────────────
# Emission
# ──────────────────────────────────────────────────────────────────────────────

# Demote every ##-or-deeper heading by one ``#`` level, used when merging
# multiple plugins into one file so each plugin's content nests under a
# top-level ``## {language_label}`` section.
_HEADING_RE = re.compile(r"^(#{2,})(?=\s)", re.MULTILINE)


def _demote_headings(body: str) -> str:
    """Add one ``#`` to every existing ``##``+ heading line."""
    return _HEADING_RE.sub(r"#\1", body)


def emit_cross_cutting_files(output: Path) -> None:
    """Write all registered cross-cutting contributions to ``output/02_cross_cutting/``.

    For each output filename:
      - **1 contributor**: write ``# {title}\\n\\n{body}`` verbatim, preserving
        byte-identical output for single-language projects.
      - **2+ contributors**: write ``# {title}`` followed by one
        ``## {language_label}\\n\\n{demoted_body}`` section per contributor,
        ordered by language alphabetically (so the same monorepo always
        produces the same file regardless of plugin discovery order).
    """
    by_name: dict[str, list[CrossCuttingFile]] = {}
    for f in _REGISTERED:
        by_name.setdefault(f.name, []).append(f)

    target_dir = output / "02_cross_cutting"
    # Defensive: do not rely on write() to create the parent dir. The
    # core.io.write() implementation does call mkdir, but making it explicit
    # here keeps the contract obvious even if write() is refactored later.
    target_dir.mkdir(parents=True, exist_ok=True)

    for name, contributions in by_name.items():
        if len(contributions) == 1:
            f = contributions[0]
            content = f"# {f.title}\n\n{f.body}".rstrip() + "\n"
        else:
            # Stable language ordering so monorepos diff cleanly.
            contributions = sorted(contributions, key=lambda x: x.language)
            # Warn (not fatal) when contributors disagree on the H1 title —
            # the first-language wins is intentional but easy to miss when
            # debugging a merged file.
            titles = {c.title for c in contributions}
            if len(titles) > 1:
                first = contributions[0]
                others = ", ".join(f"{c.language}={c.title!r}" for c in contributions[1:])
                print(f"[WARN] cross-cutting '{name}': contributors disagree on title; "
                      f"using {first.language}={first.title!r} (others: {others})")
            title = contributions[0].title
            sections = []
            for c in contributions:
                body = _demote_headings(c.body).rstrip()
                if body:
                    sections.append(f"## {c.language_label}\n\n{body}")
                else:
                    sections.append(f"## {c.language_label}\n\n（{c.language} 插件未检测到相关内容）")
            content = f"# {title}\n\n" + "\n\n".join(sections).rstrip() + "\n"
        write(target_dir / f"{name}.md", content)
