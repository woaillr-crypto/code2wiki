"""code2wiki: Multi-language Business Context Layer scanner.

Public surface lives under:
  - code2wiki.core     Language-agnostic shared utilities (io, markdown,
                             domain inference, git history, writers, models,
                             cross-cutting registry, language detection,
                             plugin registry)
  - code2wiki.plugins  Per-language scanner plugins
                             (language_{java,python,go,kotlin,typescript})
  - code2wiki.cli      CLI dispatch entry point

The Java/Spring scanner code lives in ``plugins.language_java``;
``scripts/analyze_java_project.py`` remains as a thin deprecation shim that
re-exports from there for backwards compatibility with the original CLI.
"""

import sys
from pathlib import Path

# Make scripts/ importable so we can re-export from analyze_java_project.py
# during the refactor transition.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

__version__ = "0.4.0"
