"""Golden snapshot comparison utility.

Compares an actual BCL output directory against an expected (golden) directory
and produces a structured diff report. Path normalization filters out
unavoidable differences (the absolute path of the output dir is embedded in
multiple files but is never semantically significant).

Usage as a module
-----------------
    from code2wiki.tests.snapshot import compare, render_diff

    diff = compare(golden_dir, actual_dir, project_dir, output_dir)
    if diff.has_changes():
        print(render_diff(diff))

Usage as a CLI (for golden updates)
-----------------------------------
    python3 -m code2wiki.tests.snapshot compare GOLDEN ACTUAL --project PROJ --output OUT
    python3 -m code2wiki.tests.snapshot update GOLDEN ACTUAL
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ──────────────────────────────────────────────────────────────────────────────
# Diff data model
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class FileDiff:
    """Per-file comparison result."""
    path: str                    # relative to root
    kind: str                    # "added" | "removed" | "modified" | "unchanged"
    golden_lines: list[str] = field(default_factory=list)
    actual_lines: list[str] = field(default_factory=list)


@dataclass
class SnapshotDiff:
    """Aggregate comparison of two directory trees."""
    added: list[FileDiff] = field(default_factory=list)
    removed: list[FileDiff] = field(default_factory=list)
    modified: list[FileDiff] = field(default_factory=list)

    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.modified)

    def summary(self) -> str:
        return (f"added={len(self.added)} removed={len(self.removed)} "
                f"modified={len(self.modified)}")


# ──────────────────────────────────────────────────────────────────────────────
# Path / content normalization
# ──────────────────────────────────────────────────────────────────────────────

# Strings that contain the literal output directory path get substituted with a
# stable placeholder before comparison. Both POSIX and Darwin /private/tmp
# variants are handled.
_OUTPUT_TOKEN = "<OUTPUT_DIR>"
_PROJECT_TOKEN = "<PROJECT_DIR>"


def normalize(content: str, project_dir: Path | None, output_dir: Path | None) -> str:
    """Replace volatile absolute paths with stable placeholders.

    The scanner embeds two absolute paths in its output:
      - project root (in generation_report.md, inventory.json, overview)
      - output dir   (in generation_report.md, inventory.json)

    On macOS, ``/tmp`` is a symlink to ``/private/tmp`` and the scanner uses
    Path.resolve(), so both variants are stripped.
    """
    if output_dir is not None:
        for variant in _path_variants(output_dir):
            content = content.replace(variant, _OUTPUT_TOKEN)
    if project_dir is not None:
        for variant in _path_variants(project_dir):
            content = content.replace(variant, _PROJECT_TOKEN)
    return content


def _path_variants(path: Path) -> list[str]:
    """Return the path plus its resolved form (handles /tmp ↔ /private/tmp)."""
    variants = {str(path), str(path.resolve())}
    return sorted(variants, key=len, reverse=True)  # longest first to avoid prefix collisions


# ──────────────────────────────────────────────────────────────────────────────
# Comparison
# ──────────────────────────────────────────────────────────────────────────────

def _walk_files(root: Path) -> set[str]:
    """Return relative file paths under root (recursive, posix style).

    Symlinks are skipped to prevent infinite loops and surprise content from
    outside the snapshot directory.
    """
    if not root.exists():
        return set()
    files: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            continue
        if path.is_file():
            files.add(path.relative_to(root).as_posix())
    return files


def _read_lines(path: Path, rel_path: str,
                 project_dir: Path | None, output_dir: Path | None,
                 *, normalize_paths: bool) -> list[str]:
    """Read a file; optionally normalize absolute paths.

    Args:
      path: absolute filesystem path to read
      rel_path: relative path used in the binary-sentinel (machine-independent)
      project_dir, output_dir: substituted with placeholders if ``normalize_paths`` is True
      normalize_paths: pass True for the *actual* side of a comparison; pass
        False for the *golden* side, which is already stored in placeholder form.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # Use rel_path so the sentinel is identical between golden and actual.
        return [f"<binary or unreadable: {rel_path}>"]
    if normalize_paths:
        raw = normalize(raw, project_dir, output_dir)
    return raw.splitlines(keepends=False)


def compare(golden_root: Path, actual_root: Path,
            project_dir: Path | None = None,
            output_dir: Path | None = None) -> SnapshotDiff:
    """Compare a frozen golden tree against an actual scanner-output tree.

    The golden tree is **expected to already be in placeholder form** (use
    :func:`freeze_actual_as_golden` to produce one). Only the *actual* side is
    normalized at compare time.

    Args:
      golden_root: Path to the frozen golden tree (committed in tests/golden).
      actual_root: Path to the actual output tree produced by the scanner.
      project_dir: Absolute path of the scanned project (substituted to
                   ``<PROJECT_DIR>`` in the actual side before comparison).
      output_dir: Output dir used in the current run (substituted to
                  ``<OUTPUT_DIR>``). Defaults to ``actual_root``.
    """
    output_dir = output_dir or actual_root

    golden_files = _walk_files(golden_root)
    actual_files = _walk_files(actual_root)

    diff = SnapshotDiff()

    for rel_path in sorted(actual_files - golden_files):
        diff.added.append(FileDiff(
            path=rel_path,
            kind="added",
            actual_lines=_read_lines(actual_root / rel_path, rel_path,
                                       project_dir, output_dir, normalize_paths=True),
        ))

    for rel_path in sorted(golden_files - actual_files):
        diff.removed.append(FileDiff(
            path=rel_path,
            kind="removed",
            golden_lines=_read_lines(golden_root / rel_path, rel_path,
                                       None, None, normalize_paths=False),
        ))

    for rel_path in sorted(golden_files & actual_files):
        golden_lines = _read_lines(golden_root / rel_path, rel_path,
                                     None, None, normalize_paths=False)
        actual_lines = _read_lines(actual_root / rel_path, rel_path,
                                     project_dir, output_dir, normalize_paths=True)
        if golden_lines != actual_lines:
            diff.modified.append(FileDiff(
                path=rel_path,
                kind="modified",
                golden_lines=golden_lines,
                actual_lines=actual_lines,
            ))

    return diff


# ──────────────────────────────────────────────────────────────────────────────
# Diff rendering
# ──────────────────────────────────────────────────────────────────────────────

def render_diff(diff: SnapshotDiff, max_lines_per_file: int = 40) -> str:
    """Render a SnapshotDiff as a human-readable report."""
    out: list[str] = [f"Snapshot diff: {diff.summary()}"]

    for fd in diff.added:
        out.append("")
        out.append(f"+++ ADDED: {fd.path} ({len(fd.actual_lines)} lines)")
        out.extend("    + " + ln for ln in fd.actual_lines[:max_lines_per_file])
        if len(fd.actual_lines) > max_lines_per_file:
            out.append(f"    ... ({len(fd.actual_lines) - max_lines_per_file} more lines)")

    for fd in diff.removed:
        out.append("")
        out.append(f"--- REMOVED: {fd.path} ({len(fd.golden_lines)} lines)")
        out.extend("    - " + ln for ln in fd.golden_lines[:max_lines_per_file])
        if len(fd.golden_lines) > max_lines_per_file:
            out.append(f"    ... ({len(fd.golden_lines) - max_lines_per_file} more lines)")

    for fd in diff.modified:
        out.append("")
        out.append(f"*** MODIFIED: {fd.path}")
        out.extend(_render_unified_diff(fd.golden_lines, fd.actual_lines, max_lines_per_file))

    return "\n".join(out)


def _render_unified_diff(golden: list[str], actual: list[str], limit: int) -> list[str]:
    """Compact line-by-line diff. Not a full unified-diff format; enough to
    eyeball discrepancies in golden tests."""
    import difflib
    rows: list[str] = []
    for line in difflib.unified_diff(golden, actual, lineterm="",
                                      fromfile="golden", tofile="actual"):
        rows.append("    " + line)
        if len(rows) >= limit:
            rows.append("    ... (diff truncated)")
            break
    return rows


# ──────────────────────────────────────────────────────────────────────────────
# Golden update helpers
# ──────────────────────────────────────────────────────────────────────────────

def update_golden(actual_root: Path, golden_root: Path) -> None:
    """Replace the golden tree with the actual tree (raw bytes, no normalization).

    Prefer :func:`freeze_actual_as_golden` for snapshot use — it produces a
    portable golden by substituting machine-specific absolute paths.
    """
    if golden_root.exists():
        shutil.rmtree(golden_root)
    shutil.copytree(actual_root, golden_root)


def freeze_actual_as_golden(actual_root: Path, golden_root: Path,
                              project_dir: Path, output_dir: Path | None = None) -> None:
    """Copy ``actual_root`` to ``golden_root``, normalizing absolute paths.

    Every text file is rewritten with ``<PROJECT_DIR>`` and ``<OUTPUT_DIR>``
    placeholders so that the resulting golden tree is portable across machines
    and CI environments. Binary/unreadable files are copied byte-for-byte.

    Args:
      actual_root: Source tree produced by the scanner.
      golden_root: Destination (will be removed and recreated if it exists).
      project_dir: Project path that was passed to the scanner.
      output_dir: Output path that was passed to the scanner. Defaults to
                   ``actual_root``.
    """
    output_dir = output_dir or actual_root

    if golden_root.exists():
        shutil.rmtree(golden_root)
    golden_root.mkdir(parents=True)

    for src in actual_root.rglob("*"):
        if src.is_symlink():
            continue
        rel = src.relative_to(actual_root)
        dst = golden_root / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            raw = src.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # Binary content — copy bytes verbatim.
            dst.write_bytes(src.read_bytes())
            continue
        normalized = normalize(raw, project_dir, output_dir)
        dst.write_text(normalized, encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="snapshot", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    cmp_p = sub.add_parser("compare", help="Compare actual output to golden")
    cmp_p.add_argument("golden", type=Path)
    cmp_p.add_argument("actual", type=Path)
    cmp_p.add_argument("--project", type=Path, required=True,
                        help="Project root (for path normalization)")
    cmp_p.add_argument("--output", type=Path,
                        help="Output dir used in the actual run (defaults to actual path)")

    upd_p = sub.add_parser("update", help="Overwrite golden with actual (raw copy)")
    upd_p.add_argument("golden", type=Path)
    upd_p.add_argument("actual", type=Path)

    frz_p = sub.add_parser("freeze",
                            help="Copy actual into golden with absolute paths normalized "
                                 "(produces a portable golden)")
    frz_p.add_argument("golden", type=Path)
    frz_p.add_argument("actual", type=Path)
    frz_p.add_argument("--project", type=Path, required=True,
                        help="Project root that was passed to the scanner")
    frz_p.add_argument("--output", type=Path,
                        help="Output dir that was passed to the scanner (defaults to actual path)")

    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.cmd == "compare":
        diff = compare(
            golden_root=args.golden,
            actual_root=args.actual,
            project_dir=args.project,
            output_dir=args.output or args.actual,
        )
        if diff.has_changes():
            print(render_diff(diff))
            return 1
        print(f"OK: snapshots match ({diff.summary()})")
        return 0

    if args.cmd == "update":
        update_golden(args.actual, args.golden)
        print(f"Golden updated: {args.golden}")
        return 0

    if args.cmd == "freeze":
        freeze_actual_as_golden(
            actual_root=args.actual,
            golden_root=args.golden,
            project_dir=args.project,
            output_dir=args.output or args.actual,
        )
        print(f"Golden frozen (paths normalized): {args.golden}")
        return 0

    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
