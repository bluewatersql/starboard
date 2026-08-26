# Phase 0 + Phase 1 code review — findings

> Recall-oriented review (high effort). Scope: `git diff main...HEAD` on
> `phase1/foundations` (merge-base `091ab2ed`). Phase 0 (A1–A5) is already on
> `main` and was reviewed previously (`impl/phase0_review_findings.md`); this
> pass covers the Phase-1 diff (B1, B2, B2-skill, B3, B4, B6, D2, D3) which
> builds directly on the Phase-0 substrate.
>
> Method: 8 finder angles (3 correctness, 3 cleanup, altitude, conventions),
> deduped. Overall the diff is high quality — pure-kernel discipline, lazy SDK
> imports, back-compat shims, and stable JSON envelopes are all implemented
> cleanly. The findings below are mostly packaging/altitude/deferred-correctness
> gaps rather than crashes.

## Findings (ranked most-severe first)

### 1. `plugin.json` loads the MCP server unconditionally; `enable_mcp` toggle is never referenced (B6)
- **File:** `plugin/.claude-plugin/plugin.json`
- **Severity:** High
- The manifest sets `"mcpServers": "./.mcp.json"` unconditionally and declares a
  `userConfig.enable_mcp` boolean (`default: false`), but that config value is
  **never referenced** anywhere (no `${user_config.enable_mcp}` substitution, no
  gating). Claude Code starts bundled `mcpServers` when the plugin is enabled;
  an unreferenced boolean does not gate startup.
- **Failure scenario:** A skills-only install (the advertised default, and the
  external-customer `databricks aitools` path) has no `starboard-mcp` entry
  point and no LLM credentials. Because the server is always declared, Claude
  Code attempts to launch `starboard-mcp --transport stdio` on plugin load and
  errors — contradicting the B6 contract ("Leave off to use the skills-only
  path"). Toggling `enable_mcp` off does **not** fall back cleanly.
- **Note:** `test_plugin_manifest.py` only asserts the fields exist; no test
  asserts the toggle actually gates the server, so the gap is uncaught.

### 2. `plugin/skills` is a symlink that escapes the plugin root; the "materialization" build step it relies on is not implemented (B3/B4)
- **File:** `plugin/skills` (symlink → `../packages/starboard-skills/skills/starboard`)
- **Severity:** High / Medium
- The plugin is not self-contained: `plugin/skills` points **outside** `plugin/`.
  `plugin/README.md` claims the symlink "is materialized into real files by the
  same vendoring step" for standalone artifacts, but there is **no build hook**
  in the repo (`grep` finds no `hatch_build.py`, no `[tool.hatch.build.hooks]`,
  no vendoring script).
- **Failure scenario:** Any consumer that copies only `./plugin` — the
  marketplace entry uses `source: "./plugin"`, and the B4 `databricks aitools`
  bundle is described as extracting the plugin dir — gets a **dangling** skills
  link and ships zero skills. Same on a symlink-unaware checkout (Windows / some
  archive tooling). `test_vendored_tree_matches_canonical_source_of_truth`
  passes locally *through* the symlink, so it does not catch this.

### 3. Seed-rule `evidence_query` values reference query-pack entries that do not exist (D3)
- **Files:** `packages/starboard-core/starboard_core/domain/rules/seed/query.yaml`
  (`query_performance.slowest_queries`, `query_performance.full_partition_scans`),
  `seed/warehouse.yaml` (`warehouse.auto_stop_waste`, `warehouse.utilization_bands`),
  `seed/unity_catalog.yaml` (`uc.table_maintenance_history`)
- **Severity:** Medium (deferred — `evidence_query` is documented free-text in Phase 1)
- None of these strings resolve to a real query-pack entry. The query-perf pack
  has `pack_id="query_perf"` with query ids `C-Q01..C-Q05`; the warehouse pack
  (added in this same diff) has ids `W-W01..W-W05`. The D3 acceptance criterion
  ("`evidence_query` names a real query-pack entry") is unmet, and the planned
  validating test (`PHASE_1.md` §10) was **not** implemented in
  `tests/unit/domain/rules/test_seed_rules.py`.
- **Failure scenario:** When the Phase-3 engine (D1) resolves `evidence_query`
  against the packs, every seed rule fails to bind its evidence query — a
  silent latent break shipped as "validated" seed content.

### 4. Warehouse band thresholds are duplicated (Python constants vs. hardcoded SQL literals) and diverge on a NULL-ratio edge case (D2)
- **File:** `packages/starboard/starboard/discovery/query_packs/warehouse.py`
  (`classify_utilization_band` / `W_W01_SQL`, `classify_load_bucket` / `W_W03_SQL`)
- **Severity:** Low / Medium (maintainability + edge-case logic)
- `UNDER_UTILIZED_MAX = 0.30` / `OPTIMAL_MAX = 0.80` are defined as constants for
  the Python classifier, but `W_W01_SQL` hardcodes `0.30`/`0.80` and
  `classify_load_bucket` vs `W_W03_SQL` both hardcode `10/100/1000`. The whole
  point of the paired classifiers is to "narrate the same bands the SQL
  produces" — tuning a threshold in one place silently drifts from the other.
- **Divergence:** For `running_seconds>0, total_queries>0, utilization_ratio IS
  NULL` (e.g. all `execution_duration_ms` null), the Python classifier returns
  `No-utilization` while the SQL `CASE` falls through to `Resource-starved`
  (`TRY_DIVIDE(NULL, …) <= 0.80` is NULL → `ELSE`). The two labelers disagree on
  the same row.

### 5. `starboard_x/diagnostic/__init__.py` eagerly imports the whole trio, contradicting its documented "trimmed `__init__`" goal (B2)
- **File:** `packages/starboard-core/starboard_x/diagnostic/__init__.py`
- **Severity:** Low (altitude / efficiency)
- The package docstring states it "carries a **trimmed** `__init__` so a single
  verb (e.g. `triage-exit`) does not pull the whole diagnostic subsystem", but
  the `__init__` eagerly imports `evidence_extractor`, `exit_code_triager`,
  `models`, and `root_cause_synthesizer`. `__main__.py` and the back-compat
  shims import the submodules directly, so the eager package imports are
  unnecessary for the CLI path and undercut the stated design intent (cost is
  small since all four are stdlib-only, hence Low).

### 6. `starboard_x/contract.py` re-implements the Phase-0 `starboard_skills.helpers.contract` (B2)
- **File:** `packages/starboard-core/starboard_x/contract.py`
- **Severity:** Low (reuse — largely defensible)
- The envelope builder, exit-code constants, and `HelperError`/`AuthError`/
  `NotFoundError`/`ApiError`/`ArgError` hierarchy duplicate the Phase-0
  `starboard_skills.helpers.contract` (the docstring says so: "Mirrors the
  Phase-0 starboard-helper contract"). Two copies must be kept in lockstep for
  the "same envelope" guarantee to hold. The duplication is *defensible* — the
  import-linter forbids `starboard_x` reaching into `starboard`, and
  `starboard-skills` is a separate package, so a shared module would need a new
  kernel home. Flagged so the drift risk is tracked, not necessarily fixed now.

## Fixes applied (`--fix`)

No code fixes were applied. Every finding's fix was judged to change intended
behavior, require changes outside the reviewed diff, or be blocked on an owner
design decision:

- **#1 (enable_mcp):** the correct fix (drop `mcpServers`, or wire a gating
  mechanism) is a B6 design decision and would break the current, test-locked
  manifest shape. Owner call. **Skipped — documented.**
- **#2 (symlink):** implementing the missing hatch vendoring/materialization
  build hook, or replacing the symlink with a committed real copy of 9 skill
  trees, is a build/packaging change outside the reviewed code and is
  cross-cutting with B4 (owner-gated). **Skipped — documented.**
- **#3 (evidence_query):** the values are documented free-text for Phase 1; the
  canonical target-slug scheme is a Phase-3 design decision, so any concrete
  rewrite would be a guess. **Skipped — documented.**
- **#4 (warehouse thresholds):** de-duplicating requires either threading extra
  format params through `executor._render_sql` (out of diff) or building the SQL
  from the constants (brace-conflicts with the executor's `format_map`); the
  NULL-ratio alignment needs a product call on the intended label. **Skipped —
  documented.**
- **#5 / #6:** cosmetic/altitude; low value, non-behavioral. **Skipped —
  documented.**
