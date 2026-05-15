#!/usr/bin/env python3
"""Multi-language Business Context Layer scanner entry point.

Run ``python3 scripts/analyze_project.py --help`` for full usage.

By default the language is auto-detected from build manifests + file
extensions. Supported languages: java, python, go, kotlin, typescript.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the code2wiki package is importable when this script is invoked
# directly (without installing as a package).
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from code2wiki.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
