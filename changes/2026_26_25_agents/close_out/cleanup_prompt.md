# Multi-agent prompt — Starboard codebase cleanup

> Paste this as the driving prompt for a multi-agent cleanup run (e.g. autopilot/ultrawork or a
> team). It is written for **parallel worktree agents with disjoint file ownership** + a lead that
> integrates and verifies. Baseline: `main` @ `9bb1457f` (Phases 0–3 landed). Read
> [`open_items.md`](./open_items.md) and [`../impl/PHASE_3.md`](../impl/PHASE_3.md) first.

## Objective

A **comprehensive, deep, code-level cleanup** of the Starboard monorepo: remove dead code and
out-of-scope capability, pay down technical debt, and tighten tests, scripts, config, Makefile,
dependencies, and demos — **without changing public behavior or reducing capability**.

## Non-negotiable guardrails (every agent)

1. **No capability regression.** Every public import path, CLI command, skill, config value, port,
   and backend keeps working. The **internal-data gate stays closed-by-default and additive**
   (UNIFIED_PLAN §3.5): closing it (or removing `starboard-internal`) must leave a fully-functional
   public path.
2. **Governance.** No internal namespaces (`centralized_system_tables`, `fin_live_gold`, `gtm_*`,
   `eng_*`, logfood, ClickHouse, `hmr_stack_hash`, internal shortlinks) may appear in any **public**
   package — they live only in `packages/starboard-internal/`. Grep before every commit.
3. **TDD & evidence.** Deleting code requires proving it is unreachable (no imports, no entry point,
   no test, no config/skill reference) — cite the search. Behavior changes need a failing test first.
4. **Gates stay green.** `make lint`, `make type-check`, `make test-unit`, `make test-architecture`
   (import-linter, 4 contracts) all pass. Kernel purity holds (no `databricks-sdk`/`openai`/`fastapi`/
   `mcp` in `starboard_core`).
5. **Additive vs breaking.** Prefer deletion of truly-dead code over deprecation. If a symbol *might*
   be public API, deprecate (keep a shim + warning) rather than delete; flag it for the lead.

## Method (lead)

- Decompose into the workstreams below with **disjoint file ownership**; dispatch one worktree agent
  each. **Every agent's first step:** `git merge --no-edit <integration-branch>` to rebase onto the
  current base (worktree agents branch off `origin/main`).
- Each agent: inventory → prove-dead → remove/simplify with tests → `ruff`/`mypy` on changed files →
  commit on its branch → report (files, deletions with evidence, risks). The lead merges in dependency
  order, runs the full gates after each merge, and fixes integration drift.
- **Verify after merge in the main tree** (the shared editable `.venv` resolves imports to the main
  tree; in-worktree pytest of new/moved modules is unreliable). Run the three package test dirs
  **separately**.

## Workstreams (disjoint ownership)

### A — Dead code & unreachable modules (kernel + server)
- Find symbols/modules/functions with **zero inbound references** (imports, entry points, tests,
  skills, config). Use `ruff --select F401,F811`, `vulture`, `grep`, and import-graph checks.
- **Known starting points:** back-compat **shims** left by the refactors — e.g. `starboard/tools/
  domain/diagnostic/*` (re-homed to `starboard_x.diagnostic`), any `product_surfaces` originals
  superseded by expanded packs, and other "shim"/"legacy"/"deprecated"-commented modules. Confirm each
  shim has no remaining importers before removing; if it is a documented public alias, keep + mark.
- Owns: `packages/starboard-core/starboard_core/**` (non-rules), `packages/starboard/starboard/tools/**`
  except adapters owned by B.

### B — Out-of-scope / dormant capability behind defaults
- **Dormant memory/reflexion + vector stores.** Phase-2 C4 made the semantic cache TTL-only and gated
  reflexion/episodic-vector memory behind `[memory]`/`[vectorsearch]`. Audit for **dead code paths that
  can no longer be reached on any supported config**, and for the two Phase-2 review bugs on the opt-in
  managed-VS path (`columns=["*"]`, similarity-cache hardwired to `SQLiteVectorStore` — see
  `reviews/phase2_review_findings.md`): fix or clearly quarantine behind the extra with a test.
- **Legacy stores.** `redis`/`asyncpg`/`pgvector`/`aiosqlite`/`sqlite-vec` are optional extras with a
  lazy-import guard. Confirm no eager import drags them into the default install; delete any store
  adapter/branch that no supported `database_backend`/`vector_backend` value selects.
- Owns: `starboard/adapters/**`, `starboard/infra/{cache,rag,reflexion,memory}/**`, `starboard/infra/
  core/{config,container}.py` (coordinate config edits with the lead).

### C — Tests: dead, redundant, flaky, mis-scoped
- Remove tests for deleted code; de-duplicate overlapping tests; fix any skips/xfails that are now
  obsolete; ensure every new Phase-3 surface (workload review, genie, validator council, internal
  adapters, plugins) has adequate coverage. Verify the three-package **separate-invocation** rule and
  the cross-package basename-collision constraint still hold.
- Owns: `packages/*/tests/**`, `tests/**`, `conftest.py`s, `pytest.ini`.

### D — Scripts, Makefile, config, dependencies, demos
- **Scripts:** audit `scripts/*` for orphans (e.g. RAG vector-store build/export scripts if the default
  is now reference-files) — delete or mark clearly experimental. Ensure `vendor_plugin_skills.py`,
  `dev_plugin_local.sh`, `build_rag_reference_files.py` are current.
- **Makefile:** every target runs and is referenced; remove dead targets; ensure `check` = the real gate
  set. Confirm `PY_PACKAGES` includes all shipped packages (`starboard-core`, `starboard`,
  `starboard-skills`, `starboard-internal`, `starboard-plugin-sample`).
- **Dependencies:** prune unused deps; confirm the extras taxonomy (`[vectorsearch]`, `[memory]`,
  `[sqlite]`, `[postgres]`, diagnostics/discovery/warehouse, B5 tiers) is accurate and minimal; the
  default `pip install starboard` must pull **no** heavy/store drivers. Check `[tool.uv.workspace]`
  members list all packages.
- **Demos:** the two `examples/*.ipynb` install URLs + APIs are current (already fixed); verify
  `examples/*.json` / `env.example` match the shipped CLI/MCP config.
- Owns: `scripts/**`, `Makefile`, root `pyproject.toml` (packaging), each package `pyproject.toml`,
  `examples/**`, `.mcp.json`/plugin config.

## Definition of done
- `make check` green; `make lint`/`type-check`/`test-unit`/`test-architecture` all pass; the three test
  dirs green separately; import-linter 4 contracts KEPT.
- Governance grep of public packages clean.
- A short **cleanup report** listing every deletion with its unreachability evidence, every dep removed,
  and any symbol deprecated-not-deleted (with reason). No net capability change.
- `pip install starboard` (default) still pulls no store/vector drivers; `starboard --help`, `starboard
  review`, `starboard genie ask`, and `python -m starboard_x.<cap>` all still run.
