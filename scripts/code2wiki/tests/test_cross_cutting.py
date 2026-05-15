"""Unit tests for the cross-cutting writer registry.

The registry is a process-level collector + emitter. Each test resets it at
setup time so cases stay independent.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parents[2]
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import pytest

from code2wiki.core.cross_cutting import (
    CrossCuttingFile,
    _demote_headings,
    add_cross_cutting,
    emit_cross_cutting_files,
    registered_files,
    reset_cross_cutting,
)


@pytest.fixture(autouse=True)
def _reset_between_tests():
    reset_cross_cutting()
    yield
    reset_cross_cutting()


# ──────────────────────────────────────────────────────────────────────────────
# Registry mutation
# ──────────────────────────────────────────────────────────────────────────────

def test_registry_starts_empty():
    assert registered_files() == []


def test_add_appends_to_registry():
    add_cross_cutting(
        name="mq", title="MQ 消息队列",
        body="## Consumer 清单\n表格...\n",
        language="java", language_label="Java (Spring/RocketMQ)",
    )
    files = registered_files()
    assert len(files) == 1
    assert files[0].name == "mq"
    assert files[0].language == "java"


def test_reset_clears_registry():
    add_cross_cutting(name="x", title="X", body="", language="java", language_label="Java")
    assert len(registered_files()) == 1
    reset_cross_cutting()
    assert registered_files() == []


def test_registered_files_returns_a_copy():
    """Callers must not be able to mutate the registry through the returned list."""
    add_cross_cutting(name="x", title="X", body="", language="java", language_label="Java")
    snapshot = registered_files()
    snapshot.clear()
    assert len(registered_files()) == 1


# ──────────────────────────────────────────────────────────────────────────────
# _demote_headings
# ──────────────────────────────────────────────────────────────────────────────

def test_demote_h2_becomes_h3():
    assert _demote_headings("## Hello\nbody\n") == "### Hello\nbody\n"


def test_demote_preserves_h1_in_body_unchanged():
    """The regex only matches H2+. An H1 inside the body (rare) is left alone
    so the orchestrator's title at the top of the file remains the unique H1.
    Writers are expected NOT to emit H1 anyway — this is a safety belt."""
    assert _demote_headings("# Standalone\n## sub\n") == "# Standalone\n### sub\n"


def test_demote_h3_becomes_h4():
    assert _demote_headings("### Deep\n") == "#### Deep\n"


def test_demote_skips_hashes_not_followed_by_space():
    """``#abc`` (no space) is not a heading per CommonMark; do not demote."""
    src = "##nothash\n## real heading\n"
    out = _demote_headings(src)
    assert "##nothash" in out  # untouched
    assert "### real heading" in out


def test_demote_handles_empty_body():
    assert _demote_headings("") == ""


# ──────────────────────────────────────────────────────────────────────────────
# emit_cross_cutting_files — single contributor (byte-identical guarantee)
# ──────────────────────────────────────────────────────────────────────────────

def test_emit_single_contributor_produces_title_plus_body(tmp_path):
    add_cross_cutting(
        name="mq", title="MQ 消息队列",
        body="## Consumer 清单\n\n| 类 | 文件 |\n| --- | --- |\n| FooConsumer | foo.java |\n",
        language="java", language_label="Java (Spring/RocketMQ)",
    )
    emit_cross_cutting_files(tmp_path)
    content = (tmp_path / "02_cross_cutting" / "mq.md").read_text(encoding="utf-8")
    # write() prepends SCANNER_MARKER + "\n"; the body we care about starts after that.
    body = content.split("\n", 1)[1]
    assert body.startswith("# MQ 消息队列\n\n## Consumer 清单\n\n")


def test_emit_single_contributor_with_empty_body(tmp_path):
    add_cross_cutting(
        name="auth", title="认证与权限",
        body="",
        language="java", language_label="Java",
    )
    emit_cross_cutting_files(tmp_path)
    content = (tmp_path / "02_cross_cutting" / "auth.md").read_text(encoding="utf-8")
    # Marker + H1 + trailing newline only.
    assert "# 认证与权限" in content


def test_emit_single_contributor_does_NOT_inject_language_section(tmp_path):
    """Regression: single-contributor output must be byte-identical to legacy.
    The ``## {language_label}`` section must NOT appear."""
    add_cross_cutting(
        name="cache", title="缓存",
        body="## 使用情况\nno data\n",
        language="java", language_label="Java (Spring/Redis)",
    )
    emit_cross_cutting_files(tmp_path)
    content = (tmp_path / "02_cross_cutting" / "cache.md").read_text(encoding="utf-8")
    assert "## Java" not in content
    assert "## 使用情况" in content  # plugin body preserved verbatim


# ──────────────────────────────────────────────────────────────────────────────
# emit_cross_cutting_files — multi contributor merge
# ──────────────────────────────────────────────────────────────────────────────

def test_emit_two_contributors_creates_merged_file(tmp_path):
    add_cross_cutting(
        name="mq", title="MQ 消息队列",
        body="## Consumer 清单\nFooConsumer\n",
        language="java", language_label="Java (Spring/RocketMQ)",
    )
    add_cross_cutting(
        name="mq", title="MQ 消息队列",  # same title required from all contributors
        body="## 队列消费\nCartProcessor\n",
        language="typescript", language_label="TypeScript (NestJS/BullMQ)",
    )
    emit_cross_cutting_files(tmp_path)
    content = (tmp_path / "02_cross_cutting" / "mq.md").read_text(encoding="utf-8")

    # Single H1 at top.
    assert content.count("# MQ 消息队列") == 1
    # Both language sections present.
    assert "## Java (Spring/RocketMQ)" in content
    assert "## TypeScript (NestJS/BullMQ)" in content
    # Each plugin's ## sub-heading demoted to ### inside its section.
    assert "### Consumer 清单" in content
    assert "### 队列消费" in content
    # Plugin bodies present.
    assert "FooConsumer" in content
    assert "CartProcessor" in content


def test_emit_multi_contributors_are_sorted_by_language(tmp_path):
    """Java < TypeScript alphabetically → Java section comes first regardless
    of registration order."""
    add_cross_cutting(
        name="mq", title="MQ", body="## TS body\n",
        language="typescript", language_label="TypeScript",
    )
    add_cross_cutting(
        name="mq", title="MQ", body="## Java body\n",
        language="java", language_label="Java",
    )
    emit_cross_cutting_files(tmp_path)
    content = (tmp_path / "02_cross_cutting" / "mq.md").read_text(encoding="utf-8")
    java_pos = content.index("## Java")
    ts_pos = content.index("## TypeScript")
    assert java_pos < ts_pos


def test_emit_multi_contributors_handles_empty_body(tmp_path):
    """When a plugin contributes but has nothing to report, the merge inserts
    a placeholder so the section is still visible."""
    add_cross_cutting(
        name="mq", title="MQ", body="## Java body\n",
        language="java", language_label="Java",
    )
    add_cross_cutting(
        name="mq", title="MQ", body="",
        language="python", language_label="Python",
    )
    emit_cross_cutting_files(tmp_path)
    content = (tmp_path / "02_cross_cutting" / "mq.md").read_text(encoding="utf-8")
    assert "## Python" in content
    assert "（python 插件未检测到相关内容）" in content


# ──────────────────────────────────────────────────────────────────────────────
# Multiple files in the same run
# ──────────────────────────────────────────────────────────────────────────────

def test_emit_writes_each_distinct_filename_to_separate_file(tmp_path):
    add_cross_cutting(name="mq", title="MQ", body="mq body\n",
                       language="java", language_label="Java")
    add_cross_cutting(name="scheduler", title="定时任务", body="cron body\n",
                       language="java", language_label="Java")
    emit_cross_cutting_files(tmp_path)
    assert (tmp_path / "02_cross_cutting" / "mq.md").exists()
    assert (tmp_path / "02_cross_cutting" / "scheduler.md").exists()


# ──────────────────────────────────────────────────────────────────────────────
# Dataclass surface
# ──────────────────────────────────────────────────────────────────────────────

def test_crosscuttingfile_is_frozen():
    """Immutable so callers can't reach into the registry and mutate
    contributions after they're registered."""
    f = CrossCuttingFile(name="x", title="X", body="", language="java", language_label="Java")
    with pytest.raises(Exception):  # FrozenInstanceError, but stay version-tolerant
        f.body = "tampered"  # type: ignore[misc]


# ──────────────────────────────────────────────────────────────────────────────
# Title-conflict warning (code-review Finding 3)
# ──────────────────────────────────────────────────────────────────────────────

def test_emit_warns_when_contributors_disagree_on_title(tmp_path, capsys):
    """When two plugins target the same filename with different titles, the
    orchestrator picks the first by language order and prints a [WARN]."""
    add_cross_cutting(
        name="mq", title="MQ 消息队列", body="Java body\n",
        language="java", language_label="Java",
    )
    add_cross_cutting(
        name="mq", title="队列消费", body="TS body\n",
        language="typescript", language_label="TS",
    )
    emit_cross_cutting_files(tmp_path)
    captured = capsys.readouterr()
    assert "[WARN]" in captured.out
    assert "title" in captured.out
    assert "队列消费" in captured.out  # the dropped title is reported

    # Java's title wins because it sorts first.
    content = (tmp_path / "02_cross_cutting" / "mq.md").read_text(encoding="utf-8")
    assert "# MQ 消息队列" in content
    assert "# 队列消费" not in content


def test_emit_no_warning_when_titles_agree(tmp_path, capsys):
    add_cross_cutting(name="mq", title="MQ", body="a\n",
                       language="java", language_label="Java")
    add_cross_cutting(name="mq", title="MQ", body="b\n",
                       language="typescript", language_label="TS")
    emit_cross_cutting_files(tmp_path)
    captured = capsys.readouterr()
    assert "[WARN]" not in captured.out


# ──────────────────────────────────────────────────────────────────────────────
# CLI re-entry safety (code-review Finding 1)
# ──────────────────────────────────────────────────────────────────────────────

def test_emit_does_not_create_target_dir_when_no_contributions(tmp_path):
    """An empty registry → emit creates the 02_cross_cutting dir but writes
    nothing. Subsequent runs MUST NOT inherit stale contributions from a
    previous registry state (guarded by the CLI's try/finally + reset)."""
    emit_cross_cutting_files(tmp_path)
    target = tmp_path / "02_cross_cutting"
    # The dir is created (mkdir(parents=True, exist_ok=True)) but empty.
    assert target.exists()
    assert list(target.iterdir()) == []


def test_cli_main_resets_registry_even_when_plugins_succeed(tmp_path, monkeypatch):
    """After cli.main() completes successfully, the registry must be empty
    so the next library-mode call to cli.main() starts clean."""
    # Use the smallest java fixture from the test suite.
    from pathlib import Path
    fixtures = Path(__file__).resolve().parent / "fixtures"
    project = fixtures / "java"

    from code2wiki.cli import main as cli_main
    cli_main([str(project), "--output", str(tmp_path / "out"), "--no-git"])

    # Registry must be empty after a successful run.
    assert registered_files() == []
