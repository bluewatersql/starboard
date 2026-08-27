# Starboard — Open Items (closeout, 2026-08-27)

Status of everything not fully "done + wired for production" after Phases 0–3 landed on `main`
(`origin/main` = `9bb1457f`). Three buckets: **Open/Stubbed**, **Deferred**, and **Discovery — not
planned/included**. Each item notes where it lives and what "done" would require.

---

## 1. Open / Stubbed items (built, but not production-wired)

| # | Item | State | What "done" needs |
|---|------|-------|-------------------|
| O1 | **Internal adapters D6/D7/D8-internal** (`packages/starboard-internal/`) | Adapters + entry-point registration + parity tests exist, but each is **stub/injected-backend-driven**; the zero-arg entry-point factory builds a default backend that **raises unless a live client is wired**. | Deploy-time wiring to the real backends (logs-summariser ClickHouse, dbr-doctor, `centralized_system_tables`, curated Genie rooms), plus an internal-only integration test env. Internal-index-only; never ships in the public wheel. |
| O2 | **Managed Vector Search path** (`vector_backend="vectorsearch"`) | Opt-in, off by default. Phase-2 review found two latent bugs: **#1** `similarity_search(columns=["*"])` is invalid for the VS API (silent empty context); **#3** the similarity semantic cache is hardwired to `SQLiteVectorStore` regardless of backend. | Fix against a **live** Vector Search index (schema was unknowable at review time). See `reviews/phase2_review_findings.md`. |
| O3 | **D1c validator council** (`starboard/tools/services/validator_council.py`) | Bounded multi-pass + ensemble; **tests use a deterministic stub model client**. Model ids are config-driven (G5). | Validate against live models (`system.ai.claude-opus-4-8[1m]` / `claude-fable-5` / gateway) in a customer deployment; tune `max_passes` / temperature. |
| O4 | **Apps OBO auth (D10)** | Wired through the A1 `credentials_strategy` seam; **stub-tested** (`ModelServingUserCredentials` imported lazily). | Validate in a real multi-tenant Databricks App (per-user UC/Genie grants). |
| O5 | **`databricks aitools` distribution (G4)** | **Format confirmed + documented** (`docs/AGENT_SKILLS_DISTRIBUTION.md`); the canonical skills tree is the source of truth. | Implement the mirror into the agent-skills layout + generated `manifest.json` (`scripts/skills.py`) and publish; today only the Claude Code / Isaac plugin channel is materialized. |
| O6 | **Codex / OpenCode host coverage (D9)** | Documented + a local Isaac plugin-dev script (`scripts/dev_plugin_local.sh`); the invocation is host-agnostic. | Automated per-host smoke tests in CI (currently manual verification). |
| O7 | **`.isaac/rules` baseline (D9)** | `plugin/rules/starboard.md` ships in the plugin bundle. | An install step that deploys it into a consumer's `.isaac/rules/` (today it is copy-by-hand). |

## 2. Deferred items (explicitly out of scope, by decision)

| # | Item | Source | Rationale |
|---|------|--------|-----------|
| D-a | **Workload Review v2 surfaces** — DLT / ML / pipelines / vector-search domains | PHASE_3 §16, D-3.7 | v1 ships jobs + sql + warehouse (highest-value, best-covered). |
| D-b | **Write-back / auto-remediation** into customer workspaces | PHASE_3 §16 | Phase 3 is read-only advisory; the Action-Rate loop uses re-scan, never writes. |
| D-c | **Curated public Genie space** (beyond `genie ask`) | PHASE_3 §16 | `genie ask` (public NL→SQL) ships; a curated space is later. |
| D-d | **Multi-tenant hosting hardening** — rate limits, quotas, per-tenant state — beyond the OBO auth path | PHASE_3 §16 | Out of scope for the flagship. |
| D-e | **NL→domain recall for un-annotated NL queries** (reference-file RAG returns empty context without a domain hint) | Phase-2 review #2 (intended D-2.3 tradeoff) | A lightweight keyword→domain mapping is a Phase-3+ retrieval-quality decision; the Workload Review engine is the main consumer. |
| D-f | **TTL semantic cache `invalidate(tags=…)`** flushes all when no pattern is given | Phase-2 review #4 | Documented behavior; low-priority hardening. |
| D-g | **RAG build-script parse fragility** (`scripts/build_rag_reference_files.py`) + a CI parse-roundtrip guard | Phase-2 review #6 | Pairs with the queued Preview-pack schema-validation guard. |
| D-h | **CI schema-validation for Preview `system.*` packs** | Phase-0/1 follow-up | Preview tables can change shape; a CI check would catch drift. |

## 3. Discovery items — envisioned but not planned/included

From the Round-1/2 envisioning study (`agent_integration`, `databricks_auth`, `starboard_optimization`,
`starboard_decomposition`, `progressive_helpers`, `internal_harvest`, `native_simplification`), items that
were surfaced but not carried into the phased plan:

| # | Item | Where it came from | Note |
|---|------|--------------------|------|
| X1 | **Full fleet-mode UX** (cross-account exploration, not just the `FleetSqlPort` namespace-rewrite adapter) | Topic 3 (D7) | Only the gated internal `FleetSqlPort` rewrite shipped; a fleet-level product surface was not built. |
| X2 | **`starboard_x.{cluster, charts}` depth** — cluster analyzers, a chart renderer | Topic 5 (progressive helpers) | Beyond the shipped `discovery/sparklog/warehouse/uc/review/diagnostic`; `cluster`/`charts` not implemented. |
| X3 | **Full thin-wheel layered catalog** (kernel/capability/experience as separately-published wheels) | Topic 4 (decomposition, B5) | B5 shipped tiered extras + entry-point tool discovery + a sample plugin; publishing separate wheels per tier was not done. |
| X4 | **Additional internal-tool harvests** beyond logs-summariser / dbr-doctor / LogFood / `/review` | Topic 6 (internal_harvest) | Other internal tools were catalogued but not harvested. |
| X5 | **Finance-grade `$`** via the internal `fin_live_gold` path | Topic 6, §3.5 | The public path is list-price estimates; the finance-grade internal metric pack was scoped to the gated path and not implemented (O1). |
| X6 | **Genie NL→SQL curated rooms as a first-class product** | Topic 1/3 (D8) | `genie ask` (public) + a stub curated-room adapter shipped; a curated-room product was not built. |
| X7 | **Deeper `.isaac/rules` / Codex `AGENTS`-style rulesets** per domain | Topic 1 (D9) | Only a single baseline rules file shipped. |

---

## Pointers
- Phase-2 code-review findings: [`../reviews/phase2_review_findings.md`](../reviews/phase2_review_findings.md)
- Phase 3 plan + status: [`../impl/PHASE_3.md`](../impl/PHASE_3.md)
- Owner gates (G1–G7): [`../impl/OWNER_RUNBOOK.md`](../impl/OWNER_RUNBOOK.md)
- The additive-gate invariant (why internal items stay optional): [`../UNIFIED_PLAN.md`](../UNIFIED_PLAN.md) §3.5

---

# Addendum — Docs overhaul open items (2026-08-27 reconcile)

Gaps, follow-ups, and owner decisions surfaced during the documentation overhaul
(Workstreams A–E + central reconcile). These are things the docs pass could **not**
resolve on its own (code bugs, product decisions, or owner confirmations). Numbered
`DOC-*` to avoid clashing with the O/D/X items above.

## Code / runtime (out of docs scope)

- **DOC-1 — Bootstrap eager import breaks store-free install.** `packages/starboard/starboard/bootstrap.py`
  eagerly imports `SQLiteStateStore`, so a bare `pip install starboard` can raise
  `ModuleNotFoundError: aiosqlite` before `starboard --help` runs — contradicting the
  documented "store-free by default" promise. Fix: make the SQLite/state-store import
  lazy so the default in-memory path needs no store drivers. (Flagged by Workstream B.)

- **DOC-2 — `genie ask` NL→SQL not exercised end-to-end.** Because of DOC-1 the CLI could
  not be launched during the pass; `genie ask` flags were verified from source
  (`genie_command.py`) but example outputs in the docs are illustrative. Re-verify once
  DOC-1 is fixed.

- **DOC-3 — Out-of-scope code changes left in the working tree.** The docs subagents also
  made non-docs edits (a discovery-CLI auth feature: `--profile`/`--host`/`--warehouse-id`
  across `starboard_x/discovery/__main__.py`, `cli/cli/auth_commands.py`,
  `discovery/query_cache.py`, `packages/starboard/pyproject.toml`, plus tests). These were
  **deliberately kept out** of the docs commits and remain uncommitted for separate review.

## Repository hygiene

- **DOC-4 — Duplicate/stale skills tree at repo root.** `skills/starboard/` still contains
  the old roster (includes `starboard-workspace`, lacks `starboard-workload-review`) and
  diverges from the canonical `packages/starboard-skills/skills/starboard/`. Docs now point
  at the canonical tree; the stale root tree should be reconciled or removed. (Workstream B.)

## Product / surface decisions

- **DOC-5 — Interruptible reasoning has no plain-CLI injection path.** True mid-flight
  injection (`inject-input` / `respond-to-solicitation`) is only reachable via the optional
  server/SDK. `docs/user-guide/interruptible-reasoning.md` was reframed to turn-based CLI +
  programmatic. If a supported CLI interrupt path is intended, add it and expand the doc.
  (Workstream B.)

- **DOC-6 — Databricks AI Tools distribution — owner confirmations needed.**
  `docs/distribution/databricks-aitools.md` §5 lists open owner questions: installer-side
  manifest/registry shape, install locations/precedence, CLI-version/auth prerequisites, and
  the `starboard-helper` acquisition step. (Workstream D.) Related to O5 above.

## Docs infrastructure (fixed this pass, noted for follow-up)

- **DOC-7 — `packages/starboard/README.md` was fiction — now reframed.** It described a
  `starboard-server` FastAPI backend with a full REST chat API, SSE streaming, and
  feedback/clarification/visualization endpoints. Those services were removed in the cleanup;
  the real app (`starboard.main:create_app`) exposes only `/`, `/health/*`, and an optional
  `/mcp` transport. README rewritten to match.

- **DOC-8 — Diagram sources retired.** Removed three stale Mermaid sources tied to the old
  package split: `packages/starboard-server-multi-agent.mmd`,
  `packages/starboard-log-parser-pipeline.mmd`, `integration/log-parser-integration.mmd`
  (no doc referenced their generated PNGs). If wanted, add a refreshed `starboard`
  multi-agent diagram and a `starboard-core` log-source diagram and reference them.

- **DOC-9 — Broken Mermaid edge labels fixed.** `uc/cluster/warehouse-agent-workflow.mmd`
  used double-quoted keyword lists inside `|…|` edge labels, which fail to parse in Mermaid
  10.x (so those PNGs silently never regenerated). Rewritten to plain text; all 36 remaining
  sources now generate cleanly.

- **DOC-10 — Docs toolchain was undeclared.** Added a `docs` optional-dependency group to the
  root `pyproject.toml` (`mkdocs`, `mkdocs-material`, `mermaid2`, git-revision, macros) so
  `make docs` is reproducible. **CI does not build docs at all** — consider adding a docs job
  that runs `mkdocs build --strict` + `scripts/validate_doc_links.py`.

- **DOC-11 — `mkdocs build --strict` is now clean.** All 35 original strict warnings resolved
  (nav, out-of-tree links, anchors, macros). The git-revision-date plugin's GitPython
  "no git logs" fallback (which the git CLI resolves fine) is kept non-fatal via the plugin's
  own `strict: false`; page dates fall back to the build date.

## Consistency to verify later

- **DOC-12 — Tool-count phrasing.** "45+ tools" appears in several docs (e.g.
  `architecture/SYSTEM_ARCHITECTURE.md`, package READMEs). It was not independently re-counted
  against the live registry this pass; verify the figure if precision matters and align all
  mentions.
