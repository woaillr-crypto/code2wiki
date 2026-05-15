"""Explicit plugin registry.

We avoid dynamic plugin discovery in favour of a simple, auditable list so that
import-time failures surface immediately.
"""

from __future__ import annotations

from typing import Any

# Lazy imports keep optional plugins from breaking on import errors during the
# refactor (e.g. when a plugin file is added before its dependencies are
# wired up). Each entry yields a callable that returns the plugin instance.

def _load_java() -> Any:
    from code2wiki.plugins.language_java import PLUGIN
    return PLUGIN


def _load_python() -> Any:
    from code2wiki.plugins.language_python import PLUGIN
    return PLUGIN


def _load_kotlin() -> Any:
    from code2wiki.plugins.language_kotlin import PLUGIN
    return PLUGIN


def _load_go() -> Any:
    from code2wiki.plugins.language_go import PLUGIN
    return PLUGIN


def _load_typescript() -> Any:
    from code2wiki.plugins.language_typescript import PLUGIN
    return PLUGIN


PLUGIN_LOADERS = {
    "java": _load_java,
    "python": _load_python,
    "kotlin": _load_kotlin,
    "go": _load_go,
    "typescript": _load_typescript,
}

SUPPORTED_LANGUAGES = tuple(PLUGIN_LOADERS.keys())


def get_plugin(name: str):
    """Return the plugin instance for ``name`` or raise KeyError."""
    if name not in PLUGIN_LOADERS:
        raise KeyError(
            f"Unknown language '{name}'. Supported: {', '.join(SUPPORTED_LANGUAGES)}"
        )
    return PLUGIN_LOADERS[name]()


def available_languages() -> list[str]:
    """Return languages whose plugin imports successfully."""
    available = []
    for name, loader in PLUGIN_LOADERS.items():
        try:
            loader()
            available.append(name)
        except (ImportError, ModuleNotFoundError):
            continue
    return available
