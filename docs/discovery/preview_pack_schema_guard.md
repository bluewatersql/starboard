# Preview Pack Schema Guard

## What it is

`packages/starboard/tests/contract/test_preview_pack_schema.py` is the CI
schema-validation guard for the four **Public Preview** `system.*` query packs:

| Pack | Table |
|------|-------|
| `predictive_optimization` | `system.storage.predictive_optimization_operations_history` |
| `data_quality` | `system.data_quality_monitoring.table_results` |
| `data_classification` | `system.data_classification.results` |
| `networking` | `system.access.outbound_network` |

Each pack's `SystemQuery` declares `required_columns` — the source columns its
SQL reads.  The CI test asserts that every declared column appears in the
recorded manifest at
`packages/starboard/tests/contract/fixtures/system_table_columns.json`.

This is a **recorded-manifest** approach (Decision D-0.5, `PHASE_0.md §11`):
the manifest is a checked-in baseline that catches column renames or removals
without requiring a live Databricks connection in CI.

## Refreshing the manifest (owner step — requires workspace access)

When a Preview table's schema changes, refresh the manifest by running a
`LIMIT 0` probe against the table and capturing its column names:

```sql
-- Example: run in any workspace with the table available
SELECT * FROM system.storage.predictive_optimization_operations_history LIMIT 0;
-- Capture the column names from the result schema and update the JSON manifest.
```

Then update `system_table_columns.json` with the new column list and re-run:

```bash
pytest packages/starboard/tests/contract/test_preview_pack_schema.py -v
```

If new columns appear that the pack's SQL references, also add them to
`required_columns` in the relevant pack file (e.g.
`starboard/discovery/query_packs/predictive_optimization.py`).

## CI snippet (add to Makefile / CI)

```makefile
test-contract-schema:
	pytest packages/starboard/tests/contract/test_preview_pack_schema.py -v
```

Or in a GitHub Actions step:

```yaml
- name: Contract — Preview pack schema guard
  run: |
    export PATH="$PWD/.venv/bin:$PATH"
    pytest packages/starboard/tests/contract/test_preview_pack_schema.py -v
```
