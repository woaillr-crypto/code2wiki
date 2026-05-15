# Update Playbook

Use this after every meaningful requirement, bug fix, or refactor.

## After A Requirement Is Implemented

1. Identify the touched business domain.
2. Update the domain's `examples.md` with the requirement, changed files, and behavior.
3. Update `workflows.md` if the flow, state transition, or branch changed.
4. Update `api_map.md`, `db_map.md`, `integration_map.md`, or `code_entrypoints.md` if entrypoints changed.
5. Update `risk_points.md` if concurrency, transaction, idempotency, permission, cache, or compatibility risk was discovered.
6. Update global indexes if new APIs, tables, jobs, topics, or external dependencies were added.

## Before A New Requirement

1. Read `00_project_overview.md`.
2. Search `01_business_domains/*/skill.md` for the business terms in the request.
3. Load the best domain's L1 docs.
4. Load L2 maps only for the selected domain.
5. Inspect source code paths referenced by the maps.

## Regeneration Policy

The scanner may be rerun safely, but do not blindly overwrite manually enriched content. Prefer regenerating into a temporary output directory, then merge new indexes and newly discovered entrypoints.
