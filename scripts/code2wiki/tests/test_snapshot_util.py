"""Unit tests for the snapshot comparison utility itself.

This test suite is independent of any fixture; it builds tiny temp directories
in-memory to validate the diff engine and path normalization.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the code2wiki package importable
_HERE = Path(__file__).resolve().parent.parent.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import pytest

from code2wiki.tests.snapshot import (
    SnapshotDiff,
    compare,
    freeze_actual_as_golden,
    normalize,
    render_diff,
    update_golden,
)


# ──────────────────────────────────────────────────────────────────────────────
# normalize()
# ──────────────────────────────────────────────────────────────────────────────

def test_normalize_replaces_output_dir_string(tmp_path):
    output = tmp_path / "out"
    content = f"输出目录: {output}\n其他正文\n"
    result = normalize(content, project_dir=None, output_dir=output)
    assert "<OUTPUT_DIR>" in result
    assert str(output) not in result
    assert "其他正文" in result


def test_normalize_replaces_project_dir_string(tmp_path):
    project = tmp_path / "proj"
    content = f'"project": "{project}"\n'
    result = normalize(content, project_dir=project, output_dir=None)
    assert "<PROJECT_DIR>" in result
    assert str(project) not in result


def test_normalize_handles_both_substitutions(tmp_path):
    project = tmp_path / "proj"
    output = tmp_path / "out"
    content = f"{project}|{output}|{project}"
    result = normalize(content, project_dir=project, output_dir=output)
    assert result == "<PROJECT_DIR>|<OUTPUT_DIR>|<PROJECT_DIR>"


def test_normalize_handles_resolved_path_variants(tmp_path):
    """On macOS /tmp resolves to /private/tmp. Snapshot content may have either
    form depending on whether Path.resolve() was used."""
    output = tmp_path / "out"
    # Simulate a resolved variant by appending /private/ prefix manipulation.
    raw_str = str(output)
    resolved_str = str(output.resolve())
    content = f"line-1: {raw_str}\nline-2: {resolved_str}\n"
    result = normalize(content, project_dir=None, output_dir=output)
    # Both forms get replaced.
    assert raw_str not in result
    assert resolved_str not in result
    assert result.count("<OUTPUT_DIR>") >= 1


def test_normalize_is_idempotent(tmp_path):
    output = tmp_path / "out"
    content = f"path: {output}"
    once = normalize(content, project_dir=None, output_dir=output)
    twice = normalize(once, project_dir=None, output_dir=output)
    assert once == twice


def test_normalize_returns_content_unchanged_when_no_paths(tmp_path):
    content = "no paths here, just business text\n"
    result = normalize(content, project_dir=tmp_path / "proj", output_dir=tmp_path / "out")
    assert result == content


# ──────────────────────────────────────────────────────────────────────────────
# compare()
# ──────────────────────────────────────────────────────────────────────────────

def _write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def test_compare_identical_trees_no_diff(tmp_path):
    golden = tmp_path / "g"
    actual = tmp_path / "a"
    files = {"a.md": "hello", "sub/b.md": "world"}
    _write_tree(golden, files)
    _write_tree(actual, files)

    diff = compare(golden, actual)
    assert not diff.has_changes()
    assert diff.summary() == "added=0 removed=0 modified=0"


def test_compare_detects_added_file(tmp_path):
    golden = tmp_path / "g"
    actual = tmp_path / "a"
    _write_tree(golden, {"keep.md": "x"})
    _write_tree(actual, {"keep.md": "x", "new.md": "fresh"})

    diff = compare(golden, actual)
    assert len(diff.added) == 1
    assert diff.added[0].path == "new.md"
    assert diff.added[0].actual_lines == ["fresh"]


def test_compare_detects_removed_file(tmp_path):
    golden = tmp_path / "g"
    actual = tmp_path / "a"
    _write_tree(golden, {"keep.md": "x", "gone.md": "bye"})
    _write_tree(actual, {"keep.md": "x"})

    diff = compare(golden, actual)
    assert len(diff.removed) == 1
    assert diff.removed[0].path == "gone.md"


def test_compare_detects_modified_file(tmp_path):
    golden = tmp_path / "g"
    actual = tmp_path / "a"
    _write_tree(golden, {"f.md": "line-A\nline-B\n"})
    _write_tree(actual, {"f.md": "line-A\nline-X\n"})

    diff = compare(golden, actual)
    assert len(diff.modified) == 1
    assert diff.modified[0].path == "f.md"
    assert diff.modified[0].golden_lines == ["line-A", "line-B"]
    assert diff.modified[0].actual_lines == ["line-A", "line-X"]


def test_compare_path_normalization_suppresses_output_dir_diff(tmp_path):
    """A frozen golden with <OUTPUT_DIR> placeholder must compare equal to a
    fresh scanner run that embeds the actual output path."""
    golden = tmp_path / "g-out"
    actual = tmp_path / "a-out"
    project = tmp_path / "proj"
    project.mkdir()

    # Golden is pre-normalized (placeholder form, machine-independent).
    _write_tree(golden, {"report.md": "输出目录: <OUTPUT_DIR>\n业务正文\n"})
    # Actual contains a real absolute path that compare() must normalize.
    _write_tree(actual, {"report.md": f"输出目录: {actual}\n业务正文\n"})

    diff = compare(golden, actual, project_dir=project, output_dir=actual)
    assert not diff.has_changes(), render_diff(diff)


def test_compare_path_normalization_does_not_mask_real_diff(tmp_path):
    """Path normalization must not hide content differences outside path lines."""
    golden = tmp_path / "g"
    actual = tmp_path / "a"
    _write_tree(golden, {"report.md": "path: <OUTPUT_DIR>\nstatus: GOOD\n"})
    _write_tree(actual, {"report.md": f"path: {actual}\nstatus: BAD\n"})

    diff = compare(golden, actual, output_dir=actual)
    assert len(diff.modified) == 1
    # After normalization both sides agree on the path token; only `status:` differs.
    modified = diff.modified[0]
    assert "status: GOOD" in modified.golden_lines
    assert "status: BAD" in modified.actual_lines


def test_compare_missing_golden_root_treats_everything_as_added(tmp_path):
    golden = tmp_path / "missing"
    actual = tmp_path / "a"
    _write_tree(actual, {"f.md": "x"})

    diff = compare(golden, actual)
    assert len(diff.added) == 1
    assert diff.removed == []
    assert diff.modified == []


def test_compare_handles_deeply_nested_paths(tmp_path):
    golden = tmp_path / "g"
    actual = tmp_path / "a"
    deep = "01_business_domains/order/skill.md"
    _write_tree(golden, {deep: "old"})
    _write_tree(actual, {deep: "new"})

    diff = compare(golden, actual)
    assert len(diff.modified) == 1
    assert diff.modified[0].path == deep


# ──────────────────────────────────────────────────────────────────────────────
# render_diff()
# ──────────────────────────────────────────────────────────────────────────────

def test_render_diff_includes_added_files(tmp_path):
    golden = tmp_path / "g"
    actual = tmp_path / "a"
    _write_tree(golden, {})
    _write_tree(actual, {"new.md": "fresh content"})

    diff = compare(golden, actual)
    report = render_diff(diff)
    assert "ADDED" in report
    assert "new.md" in report
    assert "fresh content" in report


def test_render_diff_includes_modified_with_unified_format(tmp_path):
    golden = tmp_path / "g"
    actual = tmp_path / "a"
    _write_tree(golden, {"f.md": "line-A\nline-B\n"})
    _write_tree(actual, {"f.md": "line-A\nline-X\n"})

    diff = compare(golden, actual)
    report = render_diff(diff)
    assert "MODIFIED" in report
    assert "f.md" in report
    # difflib unified format markers
    assert "-line-B" in report or "- line-B" in report
    assert "+line-X" in report or "+ line-X" in report


def test_render_diff_truncates_huge_files(tmp_path):
    golden = tmp_path / "g"
    actual = tmp_path / "a"
    big = "\n".join(f"line-{i}" for i in range(200))
    _write_tree(golden, {})
    _write_tree(actual, {"big.md": big})

    diff = compare(golden, actual)
    report = render_diff(diff, max_lines_per_file=20)
    assert "more lines" in report


# ──────────────────────────────────────────────────────────────────────────────
# update_golden()
# ──────────────────────────────────────────────────────────────────────────────

def test_update_golden_replaces_existing(tmp_path):
    golden = tmp_path / "g"
    actual = tmp_path / "a"
    _write_tree(golden, {"old.md": "stale"})
    _write_tree(actual, {"new.md": "fresh", "sub/x.md": "deep"})

    update_golden(actual, golden)

    assert not (golden / "old.md").exists()
    assert (golden / "new.md").read_text() == "fresh"
    assert (golden / "sub" / "x.md").read_text() == "deep"


def test_update_golden_creates_when_missing(tmp_path):
    golden = tmp_path / "nope"
    actual = tmp_path / "a"
    _write_tree(actual, {"f.md": "x"})

    update_golden(actual, golden)
    assert (golden / "f.md").read_text() == "x"


# ──────────────────────────────────────────────────────────────────────────────
# Edge cases — binary files, render_diff for removed files
# ──────────────────────────────────────────────────────────────────────────────

def test_compare_handles_binary_file_no_false_positive(tmp_path):
    """Two binary files with the SAME bytes living under different absolute
    paths must NOT be reported as modified.

    Regression test for P1-A: the binary-sentinel previously embedded the
    absolute path, producing a different sentinel for golden vs actual even
    when contents matched.
    """
    golden = tmp_path / "g"
    actual = tmp_path / "a"
    golden.mkdir()
    actual.mkdir()
    same_bytes = b"\xff\xfe\x00\x01same"
    (golden / "icon.bin").write_bytes(same_bytes)
    (actual / "icon.bin").write_bytes(same_bytes)

    diff = compare(golden, actual)
    # Sentinel now uses rel_path, which is identical between both sides.
    # NOTE: We accept false-negatives for binary content (we don't byte-compare
    # binary files); this test only guards against false-positive flapping.
    assert not diff.modified, render_diff(diff)


def test_compare_binary_files_with_different_content_currently_collide(tmp_path):
    """Documents the deliberate limitation: binary files are compared via the
    sentinel only. Differing binary content is NOT detected.

    If we ever need byte-level binary comparison, the sentinel approach has
    to be replaced. For BCL snapshots, only text outputs are emitted, so this
    is acceptable.
    """
    golden = tmp_path / "g"
    actual = tmp_path / "a"
    golden.mkdir()
    actual.mkdir()
    (golden / "icon.bin").write_bytes(b"\xff\xfe\x00\x01")
    (actual / "icon.bin").write_bytes(b"\xff\xfe\x00\x02")

    diff = compare(golden, actual)
    assert not diff.modified  # known limitation


def test_render_diff_includes_removed_files(tmp_path):
    golden = tmp_path / "g"
    actual = tmp_path / "a"
    _write_tree(golden, {"goner.md": "deprecated content"})
    _write_tree(actual, {})

    diff = compare(golden, actual)
    report = render_diff(diff)
    assert "REMOVED" in report
    assert "goner.md" in report
    assert "deprecated content" in report


def test_render_diff_truncates_huge_removed_files(tmp_path):
    golden = tmp_path / "g"
    actual = tmp_path / "a"
    big = "\n".join(f"old-{i}" for i in range(200))
    _write_tree(golden, {"big.md": big})
    _write_tree(actual, {})

    diff = compare(golden, actual)
    report = render_diff(diff, max_lines_per_file=10)
    assert "more lines" in report


# ──────────────────────────────────────────────────────────────────────────────
# CLI surface — compare and update commands
# ──────────────────────────────────────────────────────────────────────────────

from code2wiki.tests.snapshot import main as snapshot_main


def test_cli_compare_returns_zero_when_match(tmp_path, capsys):
    golden = tmp_path / "g"
    actual = tmp_path / "a"
    project = tmp_path / "proj"
    project.mkdir()
    _write_tree(golden, {"f.md": "x"})
    _write_tree(actual, {"f.md": "x"})

    rc = snapshot_main([
        "compare", str(golden), str(actual),
        "--project", str(project),
    ])
    assert rc == 0
    captured = capsys.readouterr()
    assert "OK" in captured.out


def test_cli_compare_returns_one_when_diff(tmp_path, capsys):
    golden = tmp_path / "g"
    actual = tmp_path / "a"
    project = tmp_path / "proj"
    project.mkdir()
    _write_tree(golden, {"f.md": "old"})
    _write_tree(actual, {"f.md": "new"})

    rc = snapshot_main([
        "compare", str(golden), str(actual),
        "--project", str(project),
    ])
    assert rc == 1
    captured = capsys.readouterr()
    assert "MODIFIED" in captured.out


def test_cli_update_overwrites_golden(tmp_path, capsys):
    golden = tmp_path / "g"
    actual = tmp_path / "a"
    _write_tree(golden, {"old.md": "stale"})
    _write_tree(actual, {"new.md": "fresh"})

    rc = snapshot_main(["update", str(golden), str(actual)])
    assert rc == 0
    assert not (golden / "old.md").exists()
    assert (golden / "new.md").read_text() == "fresh"


# ──────────────────────────────────────────────────────────────────────────────
# freeze_actual_as_golden — produces portable goldens
# ──────────────────────────────────────────────────────────────────────────────

def test_freeze_replaces_paths_in_text_files(tmp_path):
    """The golden produced by freeze must contain placeholders, not raw paths."""
    actual = tmp_path / "a-out"
    golden = tmp_path / "g-out"
    project = tmp_path / "proj"
    project.mkdir()

    _write_tree(actual, {
        "inventory.json": f'{{"project": "{project}", "output": "{actual}"}}',
        "01_business_domains/order/skill.md": "no paths inside\n",
    })

    freeze_actual_as_golden(actual, golden, project_dir=project, output_dir=actual)

    inv = (golden / "inventory.json").read_text(encoding="utf-8")
    assert "<PROJECT_DIR>" in inv
    assert "<OUTPUT_DIR>" in inv
    assert str(project) not in inv
    assert str(actual) not in inv

    # Files with no paths to substitute are copied unchanged.
    assert (golden / "01_business_domains/order/skill.md").read_text() == "no paths inside\n"


def test_freeze_recreates_existing_golden(tmp_path):
    actual = tmp_path / "a"
    golden = tmp_path / "g"
    _write_tree(golden, {"old.md": "stale"})
    _write_tree(actual, {"new.md": "fresh"})

    freeze_actual_as_golden(actual, golden, project_dir=tmp_path)
    assert not (golden / "old.md").exists()
    assert (golden / "new.md").read_text() == "fresh"


def test_freeze_copies_binary_bytes_verbatim(tmp_path):
    actual = tmp_path / "a"
    golden = tmp_path / "g"
    actual.mkdir()
    binary = b"\xff\xfe\x00\x01\x02PNG"
    (actual / "icon.bin").write_bytes(binary)

    freeze_actual_as_golden(actual, golden, project_dir=tmp_path)
    assert (golden / "icon.bin").read_bytes() == binary


def test_freeze_round_trip_with_compare(tmp_path):
    """Golden produced by freeze + a fresh actual run with different output dir
    must compare as identical."""
    project = tmp_path / "proj"
    project.mkdir()

    # Simulate a "first run" → golden produced
    first_run = tmp_path / "first"
    _write_tree(first_run, {
        "report.md": f"project: {project}\noutput: {first_run}\nstatus: OK\n",
    })
    golden = tmp_path / "golden"
    freeze_actual_as_golden(first_run, golden, project_dir=project, output_dir=first_run)

    # Simulate a "test run" → actual with a different output path
    second_run = tmp_path / "test-out"
    _write_tree(second_run, {
        "report.md": f"project: {project}\noutput: {second_run}\nstatus: OK\n",
    })

    diff = compare(golden, second_run, project_dir=project, output_dir=second_run)
    assert not diff.has_changes(), render_diff(diff)


def test_freeze_skips_symlinks(tmp_path):
    """Symlinks in actual must be skipped, not blindly copied or recursed into."""
    actual = tmp_path / "a"
    actual.mkdir()
    (actual / "real.md").write_text("real content")

    # Create a symlink inside actual — content outside actual.
    outside = tmp_path / "outside.md"
    outside.write_text("MUST NOT APPEAR IN GOLDEN")
    (actual / "link.md").symlink_to(outside)

    golden = tmp_path / "g"
    freeze_actual_as_golden(actual, golden, project_dir=tmp_path)

    assert (golden / "real.md").read_text() == "real content"
    assert not (golden / "link.md").exists()


# ──────────────────────────────────────────────────────────────────────────────
# Symlink safety in compare()
# ──────────────────────────────────────────────────────────────────────────────

def test_compare_skips_symlinks(tmp_path):
    """Symlinks in either tree must be ignored to prevent loops / data leakage."""
    golden = tmp_path / "g"
    actual = tmp_path / "a"
    golden.mkdir()
    actual.mkdir()

    (golden / "real.md").write_text("x")
    (actual / "real.md").write_text("x")

    outside = tmp_path / "outside.md"
    outside.write_text("ignored")
    (actual / "link.md").symlink_to(outside)

    diff = compare(golden, actual)
    # The symlink in actual is skipped, so no "added" file is reported.
    assert not diff.added
    assert not diff.modified


# ──────────────────────────────────────────────────────────────────────────────
# CLI freeze subcommand
# ──────────────────────────────────────────────────────────────────────────────

def test_cli_freeze_normalizes_paths(tmp_path):
    actual = tmp_path / "a"
    project = tmp_path / "proj"
    project.mkdir()
    _write_tree(actual, {"inv.json": f'"project":"{project}","output":"{actual}"'})

    golden = tmp_path / "g"
    rc = snapshot_main([
        "freeze", str(golden), str(actual),
        "--project", str(project),
        "--output", str(actual),
    ])
    assert rc == 0
    inv = (golden / "inv.json").read_text()
    assert "<PROJECT_DIR>" in inv
    assert "<OUTPUT_DIR>" in inv
