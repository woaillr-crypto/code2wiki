# code2wiki tests

## Layout

```
tests/
├── snapshot.py                # Golden snapshot utility (compare + CLI)
├── test_snapshot_util.py      # Unit tests for snapshot.py itself
├── test_snapshot.py           # Integration: every fixture vs its golden tree
├── fixtures/<name>/           # Mini sample projects per language + 1 mixed
└── golden/<name>/             # Expected scanner output, committed alongside code
```

## Running

```bash
# All tests
python3 -m pytest scripts/code2wiki/tests -v

# Just the snapshot regressions (every fixture)
python3 -m pytest scripts/code2wiki/tests/test_snapshot.py -v

# Coverage of the snapshot utility
cd scripts && python3 -m pytest code2wiki/tests/test_snapshot_util.py \
    --cov=code2wiki.tests.snapshot --cov-report=term-missing
```

## Golden snapshots

The `golden/<fixture>/` trees contain the **expected scanner output** for each
fixture project. They are committed to source control so any change to the
scanner that affects on-disk output is caught by CI.

**Goldens are stored in normalized form**: machine-specific absolute paths
(project root, output dir) are replaced with `<PROJECT_DIR>` and `<OUTPUT_DIR>`
placeholders. This makes them portable across developers' machines and CI.

Always produce a golden with the `freeze` command (never raw copy), otherwise
the test will fail on any machine other than the one that generated it.

### Updating a golden

When a scanner change legitimately changes output (new field, fixed bug,
output reformat), regenerate the affected golden(s) **after a deliberate
human review of the diff**:

```bash
# 1. Run scanner into a temp dir
python3 scripts/analyze_project.py \
    scripts/code2wiki/tests/fixtures/<name> \
    --output /tmp/new-<name> --no-git

# 2. Inspect the diff vs the existing golden
cd scripts
python3 -m code2wiki.tests.snapshot compare \
    code2wiki/tests/golden/<name> \
    /tmp/new-<name> \
    --project code2wiki/tests/fixtures/<name>

# 3. If the diff is intentional, freeze the new actual into the golden
python3 -m code2wiki.tests.snapshot freeze \
    code2wiki/tests/golden/<name> \
    /tmp/new-<name> \
    --project code2wiki/tests/fixtures/<name>

# 4. Re-run the snapshot tests to confirm green
python3 -m pytest code2wiki/tests/test_snapshot.py -v
```

**Do NOT** generate a golden by passing `--output golden/<name>` directly to
the scanner — that bakes your machine's absolute paths into committed files
and will break CI on every other machine. Always go through `freeze`.

## Path normalization

The scanner embeds the **absolute project path** and **absolute output dir**
into several output files (`generation_report.md`, `inventory.json`, etc.).
These are volatile across machines and across runs.

The normalization strategy:
- **Goldens**: stored with `<PROJECT_DIR>` / `<OUTPUT_DIR>` placeholders, produced
  by `freeze_actual_as_golden()`. Goldens are read **as-is** at compare time.
- **Actual** (scanner run): always normalized at compare time using the actual
  project and output paths.

The substitution handles both the literal path and its resolved form (macOS
`/tmp` ↔ `/private/tmp`). See `test_normalize_handles_resolved_path_variants`.

### Symlinks

Both `compare()` and `freeze_actual_as_golden()` skip symlinks: they are never
followed, copied, or compared. This prevents infinite recursion and data
leakage from outside the snapshot tree.

### Binary files

Binary files (anything that fails UTF-8 decoding) are compared via a sentinel
that includes only the **relative path**, so identical bytes at different
absolute locations compare equal. This is a deliberate limitation — BCL
scanner output is all text, so byte-level binary diffing is not required.
See `test_compare_binary_files_with_different_content_currently_collide`.

## Adding a new fixture

1. Create `tests/fixtures/<name>/` with a representative mini-project for the
   stack you want to cover.
2. Generate the initial golden:
   ```bash
   python3 scripts/analyze_project.py \
       scripts/code2wiki/tests/fixtures/<name> \
       --output scripts/code2wiki/tests/golden/<name> --no-git
   ```
3. Run `pytest scripts/code2wiki/tests/test_snapshot.py -v` — your new
   fixture is auto-discovered via `FIXTURE_NAMES` in `test_snapshot.py`.
4. Inspect the golden directory by hand to confirm the output is sensible.

## What the fixtures cover

| Fixture | Stack | Purpose |
| --- | --- | --- |
| `java/` | Spring Boot + MyBatis + RocketMQ + Feign | Baseline Java parity (legacy gate) |
| `python/` | FastAPI + SQLAlchemy + Celery + APScheduler | Python plugin smoke |
| `go/` | Gin + GORM + cron | Go plugin smoke, exercises `func (T) TableName()` |
| `typescript/` | NestJS + TypeORM + BullMQ | TS plugin smoke, exercises `@Controller + @Get` path stitching |
| `mixed/` | Java + TS Monorepo | Multi-plugin orchestration; **mq.md collision** is a known Phase 4 fix target |

### Known limitations captured in the `mixed/` golden

The current `golden/mixed/` records **only TypeScript** in `inventory.json` and
`generation_report.md`. This is not a bug in the test — it accurately captures
the **current scanner behavior**, where the second plugin to run overwrites the
first plugin's overview and inventory files (Phase 4 will introduce per-file
merging).

When Phase 4 ships and `mq.md` / `inventory.json` correctly merge both
languages, the `mixed/` golden will be regenerated. The Phase 4 acceptance
gate is exactly: `golden/mixed/mq.md` must contain both `## Java` and
`## TypeScript` sub-sections after the freeze.
