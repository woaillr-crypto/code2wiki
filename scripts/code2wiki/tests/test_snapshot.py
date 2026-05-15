"""Golden snapshot integration tests.

For each fixture under ``tests/fixtures/<lang>/`` we run the full scanner and
compare the result to the committed ``tests/golden/<lang>/`` tree.

If a change to the scanner causes a legitimate output difference, regenerate
the affected golden with::

    python3 -m code2wiki.tests.snapshot update <golden_root> <actual_root>

…after a deliberate human review of the diff.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "analyze_project.py"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"


# Make the code2wiki package importable.
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from code2wiki.tests.snapshot import compare, render_diff  # noqa: E402


# ──────────────────────────────────────────────────────────────────────────────
# Fixture parameter set
# ──────────────────────────────────────────────────────────────────────────────

# Parameterize on the *fixtures* directory (the source of truth). Missing
# goldens are caught by the assert in test_fixture_matches_golden plus the
# dedicated test_all_fixtures_have_golden sanity check.
FIXTURE_NAMES = sorted(p.name for p in FIXTURES_DIR.iterdir() if p.is_dir())


@pytest.fixture(params=FIXTURE_NAMES)
def fixture_name(request) -> str:
    return request.param


# ──────────────────────────────────────────────────────────────────────────────
# Scanner runner
# ──────────────────────────────────────────────────────────────────────────────

def _run_scanner(project: Path, output: Path) -> None:
    """Invoke analyze_project.py with deterministic flags (no git)."""
    cmd = [
        sys.executable,
        str(SCRIPT_PATH),
        str(project),
        "--output", str(output),
        "--no-git",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.fail(
            f"Scanner failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Per-fixture snapshot tests
# ──────────────────────────────────────────────────────────────────────────────

def test_fixture_matches_golden(fixture_name: str, tmp_path: Path) -> None:
    """Scanner output for each fixture must match its committed golden."""
    project = FIXTURES_DIR / fixture_name
    golden = GOLDEN_DIR / fixture_name
    actual = tmp_path / fixture_name

    assert project.exists(), f"Fixture {project} is missing"
    assert golden.exists(), f"Golden {golden} is missing — regenerate with `snapshot update`"

    _run_scanner(project, actual)

    diff = compare(
        golden_root=golden,
        actual_root=actual,
        project_dir=project,
        output_dir=actual,
    )

    if diff.has_changes():
        pytest.fail(
            f"Snapshot diff for fixture '{fixture_name}':\n"
            + render_diff(diff, max_lines_per_file=30)
        )


# ──────────────────────────────────────────────────────────────────────────────
# Sanity checks that the fixtures themselves stay correctly configured
# ──────────────────────────────────────────────────────────────────────────────

def test_all_fixtures_have_golden():
    """Every fixture directory must have a matching golden directory."""
    fixture_dirs = {p.name for p in FIXTURES_DIR.iterdir() if p.is_dir()}
    golden_dirs = {p.name for p in GOLDEN_DIR.iterdir() if p.is_dir()}
    missing = fixture_dirs - golden_dirs
    assert not missing, (
        f"Missing golden snapshots for fixtures: {sorted(missing)}.\n"
        "Regenerate them with: python3 scripts/analyze_project.py "
        "scripts/code2wiki/tests/fixtures/<name> "
        "--output scripts/code2wiki/tests/golden/<name> --no-git"
    )


def test_mixed_fixture_triggers_multi_plugin(tmp_path: Path):
    """The mixed fixture must trigger two plugins (auto-detect monorepo path)."""
    project = FIXTURES_DIR / "mixed"
    output = tmp_path / "mixed-out"

    cmd = [
        sys.executable, str(SCRIPT_PATH),
        str(project), "--output", str(output),
        "--no-git", "--verbose",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

    # The verbose banner should list both languages.
    assert "[CLI] Languages:" in result.stdout
    languages_line = next(ln for ln in result.stdout.splitlines() if ln.startswith("[CLI] Languages:"))
    assert "java" in languages_line and "typescript" in languages_line, (
        f"Mixed fixture must trigger both java and typescript plugins. Got: {languages_line}"
    )
