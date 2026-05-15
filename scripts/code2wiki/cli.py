"""CLI dispatch for the multi-language scanner."""

from __future__ import annotations

import argparse
from pathlib import Path

from code2wiki.core import detect, registry
from code2wiki.core.cross_cutting import (
    emit_cross_cutting_files,
    reset_cross_cutting,
)
from code2wiki.core.io import set_force_overwrite


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="analyze_project.py",
        description="Generate a Business Context Layer for a backend project. "
                    "Supports Java, Python, Go, Kotlin, TypeScript.",
    )
    parser.add_argument("project", type=Path, help="Project root directory")
    parser.add_argument("--output", type=Path, help="Output directory (default: <project>/.code2wiki/business-context-layer)")
    parser.add_argument(
        "--language",
        choices=("auto",) + registry.SUPPORTED_LANGUAGES,
        default="auto",
        help="Source language. Defaults to auto-detection.",
    )
    parser.add_argument("--max-files", type=int, default=100_000)
    parser.add_argument("--top-domains", type=int, default=30)
    parser.add_argument("--no-merge", action="store_true", help="禁用域聚合")
    parser.add_argument("--force", action="store_true", help="强制覆盖 AI-ENRICHED 文件")
    parser.add_argument("--no-git", action="store_true", help="跳过 git history 分析")
    parser.add_argument("--verbose", "-v", action="store_true", help="打印插件 trace")
    parser.add_argument(
        "--plugin-only",
        metavar="NAME",
        help="混合项目里只跑指定插件 (debug)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    project = args.project.resolve()
    if not project.exists() or not project.is_dir():
        raise SystemExit(f"Project path does not exist or is not a directory: {project}")

    languages = _resolve_languages(project, args)
    if args.verbose or len(languages) > 1:
        print(f"[CLI] Languages: {', '.join(languages)}")

    # Reset all process-level state up front. Library-mode callers running
    # ``cli.main()`` multiple times in the same Python process must NOT
    # inherit anything from a previous invocation:
    #   - cross-cutting registry (Phase 4)
    #   - --force flag in core.io (would silently overwrite AI-ENRICHED files
    #     on a subsequent run if the previous run set it)
    # The ``finally`` clause at the end mirrors both resets so the next
    # cli.main() call always starts from a clean slate even on crash.
    reset_cross_cutting()
    set_force_overwrite(False)

    output = (args.output.resolve() if args.output
              else project / ".code2wiki" / "business-context-layer")

    rc = 0
    try:
        for lang in languages:
            try:
                plugin = registry.get_plugin(lang)
            except KeyError as exc:
                print(f"[ERROR] {exc}")
                rc = 2
                continue

            if hasattr(plugin, "run_pipeline"):
                rc |= plugin.run_pipeline(args) or 0
            else:
                print(f"[WARN] Plugin '{lang}' has no run_pipeline() yet; skipping.")
                rc = 1

        # Emit cross-cutting files AFTER every plugin has had a chance to
        # register. Single-plugin runs produce byte-identical output;
        # mixed-language runs get a merged file with ``## <Language>`` sections.
        emit_cross_cutting_files(output)
    finally:
        reset_cross_cutting()
        set_force_overwrite(False)

    return rc


def _resolve_languages(project: Path, args: argparse.Namespace) -> list[str]:
    if args.plugin_only:
        return [args.plugin_only]
    if args.language != "auto":
        return [args.language]
    detected = detect.pick_languages(project)
    if not detected:
        # Backwards compatibility: previously the tool was Java-only.
        # When nothing is detected, fall through to Java to avoid breaking
        # existing users; the plugin itself will produce a meaningful error
        # if there really are no source files.
        print("[CLI] 未能自动识别项目语言，回退到 Java。可以用 --language 显式指定。")
        return ["java"]
    return detected


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
