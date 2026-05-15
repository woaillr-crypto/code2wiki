"""In-process integration tests that exercise each plugin's full pipeline.

The snapshot suite (``test_snapshot.py``) spawns a subprocess per fixture,
which gives perfect isolation but bypasses ``coverage.py`` instrumentation.
This file re-runs the same fixtures **in-process** via ``cli.main`` so the
plugin pipelines (analyze_file, build_context, generate_*, _generate_cross_cutting)
all contribute to coverage measurement.

These tests do NOT replace the subprocess snapshot suite — they exist purely
to give coverage.py visibility. The byte-identical contract is enforced
elsewhere; here we only assert that each run completes successfully.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parents[2]
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import pytest


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(params=sorted(p.name for p in FIXTURES_DIR.iterdir() if p.is_dir()))
def fixture_name(request) -> str:
    return request.param


def test_pipeline_runs_in_process(fixture_name: str, tmp_path):
    """Run the scanner via cli.main() rather than subprocess so plugin code
    contributes to coverage. Smoke check the output directory was populated."""
    from code2wiki.cli import main as cli_main

    project = FIXTURES_DIR / fixture_name
    output = tmp_path / "out"
    rc = cli_main([str(project), "--output", str(output), "--no-git"])
    assert rc == 0, f"Scanner failed for fixture '{fixture_name}' (rc={rc})"

    # Spot-check the expected top-level files were produced.
    assert (output / "SKILL.md").exists()
    assert (output / "00_project_overview.md").exists()
    assert (output / "inventory.json").exists()
    # Cross-cutting dir exists (Phase 4 — emit_cross_cutting_files always
    # creates it even if empty).
    assert (output / "02_cross_cutting").exists()


def test_pipeline_force_flag_overwrites_ai_enriched(tmp_path):
    """Cover the --force code path in core.io.set_force_overwrite + write()."""
    from code2wiki.cli import main as cli_main
    from code2wiki.core.io import AI_ENRICHED_MARKER

    project = FIXTURES_DIR / "java"
    output = tmp_path / "out"

    # First run: produce baseline.
    cli_main([str(project), "--output", str(output), "--no-git"])
    # Mark a domain file as AI-enriched.
    skill_file = next(output.rglob("01_business_domains/*/skill.md"))
    original_content = skill_file.read_text()
    skill_file.write_text(AI_ENRICHED_MARKER + "\nhand-curated\n")

    # Second run WITHOUT --force should skip the enriched file.
    cli_main([str(project), "--output", str(output), "--no-git"])
    assert "hand-curated" in skill_file.read_text()

    # Third run WITH --force overwrites.
    cli_main([str(project), "--output", str(output), "--no-git", "--force"])
    assert "hand-curated" not in skill_file.read_text()


def test_pipeline_force_flag_does_NOT_leak_across_cli_calls(tmp_path):
    """Regression for the code-review finding: ``_force_overwrite`` is a
    module-level global. A previous ``cli.main()`` call with ``--force`` must
    NOT cause a subsequent ``cli.main()`` call WITHOUT ``--force`` to silently
    overwrite AI-ENRICHED files.

    Without ``set_force_overwrite(False)`` in the CLI's try/finally, the flag
    would survive between library-mode calls and the second cli.main below
    would behave as though ``--force`` were still in effect.
    """
    from code2wiki.cli import main as cli_main
    from code2wiki.core.io import AI_ENRICHED_MARKER

    project = FIXTURES_DIR / "java"
    output_a = tmp_path / "a"
    output_b = tmp_path / "b"

    # Run 1 — populate output_a WITH --force.
    cli_main([str(project), "--output", str(output_a), "--no-git", "--force"])

    # Populate output_b first run, then AI-enrich one of its files.
    cli_main([str(project), "--output", str(output_b), "--no-git"])
    enriched = next(output_b.rglob("01_business_domains/*/skill.md"))
    enriched.write_text(AI_ENRICHED_MARKER + "\nhand-curated\n")

    # Run 2 — no --force this time. If state leaked from Run 1, the hand
    # curation would be wiped.
    cli_main([str(project), "--output", str(output_b), "--no-git"])
    assert "hand-curated" in enriched.read_text(), (
        "cli.main must reset --force state between calls — the second run "
        "without --force overwrote an AI-ENRICHED file."
    )


def test_pipeline_no_merge_flag_disables_domain_merging(tmp_path):
    """Cover the --no-merge branch in the legacy pipeline."""
    from code2wiki.cli import main as cli_main
    project = FIXTURES_DIR / "java"
    rc = cli_main([str(project), "--output", str(tmp_path / "out"),
                    "--no-git", "--no-merge"])
    assert rc == 0


def test_pipeline_verbose_flag(tmp_path, capsys):
    """Cover the --verbose banner in cli.main."""
    from code2wiki.cli import main as cli_main
    project = FIXTURES_DIR / "java"
    cli_main([str(project), "--output", str(tmp_path / "out"),
              "--no-git", "--verbose"])
    captured = capsys.readouterr()
    assert "[CLI] Languages:" in captured.out


def test_pipeline_explicit_language_flag(tmp_path):
    """Cover the explicit --language path (bypasses auto-detect)."""
    from code2wiki.cli import main as cli_main
    project = FIXTURES_DIR / "java"
    rc = cli_main([str(project), "--output", str(tmp_path / "out"),
                    "--no-git", "--language", "java"])
    assert rc == 0


def test_pipeline_plugin_only_flag(tmp_path):
    """Cover the --plugin-only debug path."""
    from code2wiki.cli import main as cli_main
    project = FIXTURES_DIR / "mixed"
    rc = cli_main([str(project), "--output", str(tmp_path / "out"),
                    "--no-git", "--plugin-only", "java"])
    assert rc == 0


def test_pipeline_top_domains_truncates(tmp_path):
    """Cover the --top-domains argument."""
    from code2wiki.cli import main as cli_main
    project = FIXTURES_DIR / "python"
    rc = cli_main([str(project), "--output", str(tmp_path / "out"),
                    "--no-git", "--top-domains", "1"])
    assert rc == 0


# ──────────────────────────────────────────────────────────────────────────────
# Git history analysis coverage
# ──────────────────────────────────────────────────────────────────────────────

def test_pipeline_with_real_git_repo(tmp_path):
    """Initialize a git repo on a copy of the Java fixture, then run the
    scanner WITHOUT --no-git so :mod:`code2wiki.core.git` is exercised.

    The Java fixture has 6 files and a small commit will produce hot-file +
    contributor signals that the git analyzer reads back from ``git log``.
    """
    import shutil
    import subprocess
    from code2wiki.cli import main as cli_main

    # Copy the java fixture into a fresh temp dir so we can git-init in place
    # without polluting the canonical fixtures tree.
    project = tmp_path / "java-with-git"
    shutil.copytree(FIXTURES_DIR / "java", project)

    # Use raw subprocess + isolated env so the test does not pick up the
    # developer's ~/.gitconfig defaults that might enable signing or hooks.
    env = {
        "GIT_AUTHOR_NAME": "tester",
        "GIT_AUTHOR_EMAIL": "tester@example.com",
        "GIT_COMMITTER_NAME": "tester",
        "GIT_COMMITTER_EMAIL": "tester@example.com",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "HOME": str(tmp_path),
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    subprocess.run(["git", "init", "-q", "-b", "main", str(project)], env=env, check=True)
    subprocess.run(["git", "-C", str(project), "add", "-A"], env=env, check=True)
    subprocess.run(
        ["git", "-C", str(project), "commit", "-q",
         "--no-gpg-sign", "-m", "添加 订单 模块基线"],
        env=env, check=True,
    )

    output = tmp_path / "out"
    rc = cli_main([str(project), "--output", str(output)])
    assert rc == 0
    # Git activity report must be produced (it's empty-string-content tolerant
    # but the file should exist).
    activity = output / "05_indexes" / "git_activity.md"
    assert activity.exists()
    # Should detect at least the single commit we made.
    content = activity.read_text(encoding="utf-8")
    assert "Git Activity" in content


def test_git_cmd_returns_none_on_non_git_dir(tmp_path):
    """Direct unit test for the low-level git helper — covers the
    ``rev-parse`` failure branch."""
    from code2wiki.core.git import _git_cmd
    # tmp_path is not a git repo.
    result = _git_cmd(tmp_path, ["rev-parse", "--is-inside-work-tree"])
    assert result is None


def test_analyze_git_history_returns_empty_for_non_git_dir(tmp_path):
    """The high-level analyzer must early-return a default GitContext when
    the project is not a git repository."""
    from code2wiki.core.git import analyze_git_history
    ctx = analyze_git_history(tmp_path, infos=[], top_domains=[])
    assert ctx.is_git_repo is False
    assert ctx.hot_files == []
    assert ctx.recent_commits == []


def test_generate_git_activity_renders_placeholder_when_not_git_repo(tmp_path):
    """When :class:`GitContext.is_git_repo` is False, the report file must
    contain a placeholder message, not an empty body."""
    from code2wiki.core.git import generate_git_activity
    from code2wiki.core.models import GitContext
    generate_git_activity(tmp_path, GitContext(is_git_repo=False), top_domains=[])
    report = tmp_path / "05_indexes" / "git_activity.md"
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert "本项目不是 git 仓库" in text
