#!/usr/bin/env python3
"""Legacy Java-only entry point for the BCL scanner.

DEPRECATED — prefer ``scripts/analyze_project.py`` which auto-detects the
project language and dispatches to the right plugin. This script remains
for backwards compatibility and forwards everything to
``code2wiki.plugins.language_java._run_legacy_pipeline``.

The Java analyzer / writer code lives in
``code2wiki.plugins.language_java``; core utilities live under
``code2wiki.core.*``.

Deprecation surface:
  - Running this file as a script (``python3 analyze_java_project.py ...``)
    prints a [DEPRECATED] banner and issues a DeprecationWarning.
  - **Programmatic callers** that do ``from analyze_java_project import main``
    receive ``_run_legacy_pipeline`` without any warning — the warning is
    scoped to the ``if __name__ == "__main__"`` block. This is intentional
    so library use cases stay quiet, but callers should migrate to importing
    from ``code2wiki.plugins.language_java`` directly.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

# Make the code2wiki package importable when this script is invoked
# directly without an installed entry point.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Re-export the Java pipeline + every consumer-facing name that historical
# callers used to import from this module.
from code2wiki.plugins.language_java import (  # noqa: E402, F401
    _run_legacy_pipeline as main,
    analyze_java_file,
    build_project_context,
    extract_mappings,
    generate_cross_cutting,
    parse_mybatis_xmls,
    parse_pom_dependencies,
    risk_signals,
)
from code2wiki.core.models import (  # noqa: E402, F401
    FileInfo, GitContext, JavaFileInfo, MyBatisXmlInfo, ProjectContext,
)


def _legacy_main_with_cross_cutting() -> int:
    """Wrapper around ``main()`` that brackets the legacy pipeline with the
    cross-cutting registry's reset/emit calls.

    Without this, callers using the legacy ``python3 analyze_java_project.py``
    entry point would produce an empty ``02_cross_cutting/`` directory because
    the Java plugin's ``generate_cross_cutting`` only **registers** content in
    the in-process registry (Phase 4); the actual disk writes happen inside
    :func:`code2wiki.core.cross_cutting.emit_cross_cutting_files`.
    """
    from code2wiki.core.cross_cutting import (
        emit_cross_cutting_files,
        reset_cross_cutting,
    )

    # The legacy main() parses ``sys.argv`` to discover ``--output``. We re-parse
    # the same way so we know where to emit, but only for this thin wrapper —
    # the inner main() does the real argparse pass.
    out_dir: Path | None = None
    argv = sys.argv[1:]
    for i, tok in enumerate(argv):
        if tok == "--output" and i + 1 < len(argv):
            out_dir = Path(argv[i + 1]).resolve()
            break
    if out_dir is None and argv:
        # Default output path matches the CLI's default: <project>/.code2wiki/...
        first_positional = next((a for a in argv if not a.startswith("--")), None)
        if first_positional:
            out_dir = (Path(first_positional).resolve()
                       / ".code2wiki" / "business-context-layer")

    reset_cross_cutting()
    try:
        rc = main()
        if out_dir is not None:
            emit_cross_cutting_files(out_dir)
        return rc
    finally:
        # Always clear the registry so subsequent process-internal invocations
        # do not inherit leftover contributions on crash.
        reset_cross_cutting()


if __name__ == "__main__":
    print(
        "[DEPRECATED] analyze_java_project.py is the legacy entry point. "
        "Prefer: python3 scripts/analyze_project.py --language java <project>",
        file=sys.stderr,
    )
    warnings.warn(
        "analyze_java_project.py is deprecated; "
        "use scripts/analyze_project.py --language java instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    raise SystemExit(_legacy_main_with_cross_cutting())
