"""Unit tests for Java/Kotlin Spring mapping extraction.

Phase 1.4 focus: array-form ``path = [...]`` / ``arrayOf(...)`` / ``{...}``
syntax must yield one entry per path string.

These tests serve as regression protection for the existing behavior — the
implementation in ``analyze_java_project.extract_mappings`` already handles
the array forms (via the generic ``extract_string_values`` helper), but
Phase 4 will refactor ``generate_cross_cutting`` and the mapping logic; the
suite below pins the contract so that refactor cannot silently regress.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make scripts/ importable so we can load analyze_java_project.
_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import pytest

from code2wiki.plugins.language_java import extract_mappings


# ──────────────────────────────────────────────────────────────────────────────
# Single-string forms (baseline)
# ──────────────────────────────────────────────────────────────────────────────

def test_single_string_value():
    assert extract_mappings('@GetMapping("/orders")') == ["/orders"]


def test_value_keyword_argument():
    assert extract_mappings('@RequestMapping(value = "/orders")') == ["/orders"]


def test_path_keyword_argument():
    assert extract_mappings('@GetMapping(path = "/orders")') == ["/orders"]


def test_request_mapping_no_args_emits_class_level_marker():
    """A bare @RequestMapping (used at class level) records a marker so the
    mapping count is non-zero for the class-level annotation."""
    assert extract_mappings("@RequestMapping") == ["<class-level>"]


# ──────────────────────────────────────────────────────────────────────────────
# Java array form: @GetMapping({"/foo", "/bar"})
# ──────────────────────────────────────────────────────────────────────────────

def test_java_brace_array_two_paths():
    """`@GetMapping({"/foo", "/bar"})` is Java's array-of-strings syntax."""
    result = extract_mappings('@GetMapping({"/foo", "/bar"})')
    assert "/foo" in result
    assert "/bar" in result


def test_java_brace_array_with_value_keyword():
    result = extract_mappings('@RequestMapping(value = {"/api/v1", "/api/v2"})')
    assert result == ["/api/v1", "/api/v2"]


def test_java_brace_array_with_path_keyword():
    result = extract_mappings('@RequestMapping(path = {"/x", "/y", "/z"})')
    assert result == ["/x", "/y", "/z"]


# ──────────────────────────────────────────────────────────────────────────────
# Kotlin array form: path = ["/foo", "/bar"]
# ──────────────────────────────────────────────────────────────────────────────

def test_kotlin_bracket_array_path():
    """Kotlin uses `path = ["/x", "/y"]` (the Kotlin array literal syntax)."""
    result = extract_mappings('@RequestMapping(path = ["/foo", "/bar"])')
    assert "/foo" in result
    assert "/bar" in result


def test_kotlin_bracket_array_value():
    result = extract_mappings('@RequestMapping(value = ["/list", "/all"])')
    assert "/list" in result
    assert "/all" in result


# ──────────────────────────────────────────────────────────────────────────────
# Kotlin arrayOf(...) form
# ──────────────────────────────────────────────────────────────────────────────

def test_kotlin_arrayof_two_paths():
    result = extract_mappings('@GetMapping(arrayOf("/x", "/y"))')
    assert "/x" in result
    assert "/y" in result


def test_kotlin_arrayof_with_path_keyword():
    result = extract_mappings('@RequestMapping(path = arrayOf("/m", "/n"))')
    assert "/m" in result
    assert "/n" in result


# ──────────────────────────────────────────────────────────────────────────────
# Mixed annotations on the same file
# ──────────────────────────────────────────────────────────────────────────────

def test_multiple_annotations_in_same_file():
    src = """
    @GetMapping({"/list", "/all"})
    public List<Order> list() {}

    @PostMapping("/create")
    public Order create() {}

    @DeleteMapping(path = ["/{id}", "/by-no/{no}"])
    public void delete() {}
    """
    result = extract_mappings(src)
    assert "/list" in result
    assert "/all" in result
    assert "/create" in result
    assert "/{id}" in result
    assert "/by-no/{no}" in result


def test_class_level_array_combined_with_method_level():
    src = """
    @RequestMapping(path = ["/api/v1", "/api/v2"])
    public class OrderController {
        @GetMapping("/list")
        public List<Order> list() {}
    }
    """
    result = extract_mappings(src)
    assert "/api/v1" in result
    assert "/api/v2" in result
    assert "/list" in result


# ──────────────────────────────────────────────────────────────────────────────
# Edge cases
# ──────────────────────────────────────────────────────────────────────────────

def test_empty_string_path_is_skipped():
    """`@GetMapping("")` shouldn't pollute mappings — skipped via the
    `if v and not v.startswith('${')` filter in extract_string_values."""
    # The current implementation does NOT skip empty strings explicitly
    # (it only skips strings starting with ${). Document the current behavior.
    result = extract_mappings('@GetMapping("")')
    # Currently empty paths fall through the `if values: result.extend(values)`
    # branch with an empty list. Confirm no empties appear.
    assert "" not in result


def test_property_placeholder_skipped():
    """Spring property placeholders like ${api.prefix} are NOT real paths."""
    result = extract_mappings('@GetMapping("${api.prefix}/orders")')
    # The whole string starts with ${ → skipped by extract_string_values.
    # We expect only the literal portion (which doesn't exist standalone),
    # so the list should be empty or contain class-level marker.
    assert "${api.prefix}/orders" not in result


def test_no_mapping_annotation_returns_empty():
    result = extract_mappings("public class Foo {}")
    assert result == []


def test_duplicate_paths_deduplicated():
    """Same path repeated across annotations should not produce duplicates."""
    src = """
    @GetMapping("/orders")
    public List<Order> list() {}

    @PostMapping("/orders")
    public Order create() {}
    """
    result = extract_mappings(src)
    # The implementation uses dict.fromkeys() to dedupe.
    assert result.count("/orders") == 1


# ──────────────────────────────────────────────────────────────────────────────
# Combined produces/consumes do not leak as paths
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("annotation,expected_path", [
    ('@GetMapping(value = "/foo", produces = "application/json")', "/foo"),
    ('@PostMapping(path = "/bar", consumes = "application/xml")', "/bar"),
])
def test_paths_extracted_despite_other_string_attrs(annotation, expected_path):
    """The existing extractor grabs ALL strings, so MIME types may also appear.
    We assert the path itself is present; the (acknowledged) over-capture of
    MIME strings is documented in references/discovery/java.md."""
    result = extract_mappings(annotation)
    assert expected_path in result


# ──────────────────────────────────────────────────────────────────────────────
# JavaPlugin.run_pipeline — argparse SystemExit handling
# ──────────────────────────────────────────────────────────────────────────────

class _StubArgs:
    """Minimal argparse.Namespace-like object for run_pipeline contracts."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_run_pipeline_converts_argparse_systemexit_into_return_code(tmp_path, monkeypatch):
    """Regression for code-review Finding 1: argparse raises SystemExit on
    malformed argv. ``run_pipeline`` must catch and turn that into an int
    return code so the outer orchestrator does not bubble the exception."""
    from code2wiki.plugins.language_java import JavaPlugin

    # Project path that does not exist — _run_legacy_pipeline calls
    # raise SystemExit("Project path does not exist...") which surfaces as
    # SystemExit with the message as the code (a string, not int).
    args = _StubArgs(
        project=tmp_path / "nonexistent",
        output=tmp_path / "out",
        max_files=100,
        top_domains=10,
        no_merge=False,
        force=False,
        no_git=True,
    )
    rc = JavaPlugin().run_pipeline(args)
    # The legacy pipeline raises ``SystemExit("Project path does not exist…")``
    # with a STRING code. The wrapper falls back to 1 for non-int codes.
    assert rc == 1


def test_run_pipeline_restores_sys_argv_even_on_error(tmp_path):
    """The argv backup/restore in run_pipeline must survive a SystemExit raised
    inside the pipeline. Otherwise downstream tests inherit a garbled argv."""
    import sys

    from code2wiki.plugins.language_java import JavaPlugin

    original_argv = sys.argv[:]
    args = _StubArgs(
        project=tmp_path / "nonexistent",
        output=tmp_path / "out",
        max_files=100,
        top_domains=10,
        no_merge=False,
        force=False,
        no_git=True,
    )
    JavaPlugin().run_pipeline(args)
    assert sys.argv == original_argv


# ──────────────────────────────────────────────────────────────────────────────
# Legacy entry-point cross-cutting coverage (code-review Finding 2)
# ──────────────────────────────────────────────────────────────────────────────

def test_legacy_main_emits_cross_cutting_files(tmp_path):
    """Regression for code-review Finding 2: callers using the legacy
    ``python3 analyze_java_project.py`` entry point must also receive the
    full ``02_cross_cutting/`` output. Before the fix, the legacy path only
    registered with the registry but never emitted, leaving the directory
    empty (Java produced 31 output files instead of 41).
    """
    import subprocess
    import sys

    fixtures = Path(__file__).resolve().parent / "fixtures"
    project = fixtures / "java"
    out_dir = tmp_path / "legacy-out"

    repo_scripts = Path(__file__).resolve().parents[2]
    legacy_script = repo_scripts / "analyze_java_project.py"
    result = subprocess.run(
        [sys.executable, str(legacy_script),
         str(project), "--output", str(out_dir), "--no-git"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr

    cross_cutting_dir = out_dir / "02_cross_cutting"
    assert cross_cutting_dir.exists(), \
        "Legacy entry point must produce 02_cross_cutting/ (Phase 4 regression)"
    files = sorted(p.name for p in cross_cutting_dir.iterdir())
    # Java contributes 11 cross-cutting files. Spot-check the canonical ones.
    assert "mq.md" in files
    assert "scheduler.md" in files
    assert "cache.md" in files
    assert "transaction.md" in files
    assert "auth.md" in files

    # Deprecation banner must appear on stderr.
    assert "[DEPRECATED]" in result.stderr
