"""Language auto-detection.

Scans build manifests + file extensions in the project tree, returns languages
ordered by confidence (highest first). Empty result means we could not detect
anything and the caller should error out (or fall back to Java for legacy
compatibility).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from code2wiki.core.io import IGNORE_DIRS

# Manifest filename → language. Presence of a manifest is a strong signal
# (weight 10). File extensions are weak signals (weight 1 per file).
MANIFEST_MAP: dict[str, str] = {
    "pom.xml": "java",
    "build.gradle": "java",
    "settings.gradle": "java",
    "build.gradle.kts": "kotlin",
    "settings.gradle.kts": "kotlin",
    "go.mod": "go",
    "package.json": "typescript",
    "tsconfig.json": "typescript",
    "pyproject.toml": "python",
    "requirements.txt": "python",
    "setup.py": "python",
    "manage.py": "python",
}

EXT_MAP: dict[str, str] = {
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".go": "go",
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "typescript",
    ".mjs": "typescript",
}

MIN_SIGNAL_THRESHOLD = 5
DOMINANT_RATIO = 3.0  # if top language is >= 3x runner-up, treat as solo


def detect_languages(root: Path, sample_limit: int = 4000) -> list[tuple[str, int]]:
    """Return [(language, score), ...] in descending score order."""
    signals: Counter[str] = Counter()

    # Manifest scan (top 2 levels only, manifests live at project root).
    for entry in root.iterdir() if root.exists() else []:
        if entry.is_file() and entry.name in MANIFEST_MAP:
            signals[MANIFEST_MAP[entry.name]] += 10
        # One level deep (e.g. a frontend/ subdir with its own package.json).
        if entry.is_dir() and entry.name not in IGNORE_DIRS:
            for child in entry.iterdir() if entry.exists() else []:
                if child.is_file() and child.name in MANIFEST_MAP:
                    signals[MANIFEST_MAP[child.name]] += 5

    # Sampled extension scan.
    count = 0
    for current_root, dirs, files in _walk(root):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".")]
        for fname in files:
            if count >= sample_limit:
                break
            suffix = "." + fname.rsplit(".", 1)[-1] if "." in fname else ""
            lang = EXT_MAP.get(suffix)
            if lang:
                signals[lang] += 1
                count += 1
        if count >= sample_limit:
            break

    return [(lang, score) for lang, score in signals.most_common() if score >= MIN_SIGNAL_THRESHOLD]


def pick_languages(root: Path) -> list[str]:
    """Return languages to scan: solo if one dominates, otherwise all detected."""
    ranked = detect_languages(root)
    if not ranked:
        return []
    if len(ranked) == 1:
        return [ranked[0][0]]
    top_lang, top_score = ranked[0]
    runner_up_score = ranked[1][1]
    if runner_up_score == 0 or top_score / runner_up_score >= DOMINANT_RATIO:
        return [top_lang]
    return [lang for lang, _ in ranked]


def _walk(root: Path):
    import os
    if not root.exists():
        return
    yield from os.walk(root)
