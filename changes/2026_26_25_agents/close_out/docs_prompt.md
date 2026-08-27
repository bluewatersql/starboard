# Multi-agent prompt — Starboard documentation overhaul

> Paste this as the driving prompt for a multi-agent docs run. Written for **parallel worktree agents
> with disjoint doc-area ownership** + a lead that reconciles cross-references and builds the nav. The
> single source of truth is the **code on `main` @ `9bb1457f`** (Phases 0–3). Read
> [`open_items.md`](./open_items.md), [`../UNIFIED_PLAN.md`](../UNIFIED_PLAN.md), and
> [`../impl/PHASE_3.md`](../impl/PHASE_3.md) first.

## Objective

Clean up, optimize, update, replace, or rewrite **all** project documentation so it is **accurate to
the shipped implementation** and complete **end-to-end for two personas**: the **developer** (extends/
operates Starboard) and the **user** (runs analyses via CLI / skills / notebooks). ~148 files under
`docs/`, plus root governance docs.

## Ground truth — what the code actually does now (align every doc to this)

The docs predate Phases 0–3 and describe a heavier, store-backed system. Correct them to today's design:

- **State:** default `database_backend="memory"`; durable option is **UC-native** (`"uc"`); `sqlite`/
  `postgres`/`lakebase` are optional extras, not the default. (Many `docs/diagrams/.../state-management-*`
  and `docs/admin/state-backends.md` reflect the old default — update.)
- **RAG:** default `vector_backend="none"` — **reference files + query packs**, not an embedding/vector
  DB. Managed Databricks Vector Search is opt-in behind `[vectorsearch]`.
- **Memory/cache:** semantic cache is **TTL-only** by default; reflexion/episodic-vector memory is gated
  behind `[memory]`/`[vectorsearch]`.
- **Auth:** "auth by subtraction" — one resolver delegates to the SDK credential chain; `--profile`/
  ambient; PAT optional. Apps OBO via the `credentials_strategy` seam.
- **Distribution/reach:** skills-only Claude Code plugin + `marketplace.json`; reaches Isaac (wraps
  Claude Code); Codex/OpenCode via `python -m starboard_x.<cap>`; `databricks aitools` channel. **Plugins
  are not MCP servers**; MCP is optional.
- **New capabilities:** **Workload Review** (`starboard review`, `workload-review` skill,
  `python -m starboard_x.review`) with the RuleRegistry + Finding scorer + optional validator council +
  Action-Rate re-scan; **`genie ask`** (NL→SQL); the **internal-data enablement gate** (ports + public
  adapters, closed-by-default, additive — internal adapters live only in `starboard-internal`);
  **layered catalog** (tiered extras + entry-point tool discovery).
- **Packages:** `starboard-core` (pure kernel + `starboard_x` helpers), `starboard`, `starboard-skills`,
  `starboard-internal` (internal-only), `starboard-plugin-sample`.
- **$ semantics:** public path is **list-price DBU estimates** (label everywhere); finance-grade is
  internal-only.

## Non-negotiable guardrails (every agent)

1. **Docs match code, not aspiration.** Verify every command, import, config key, flag, and file path
   against the source before documenting it. If a doc describes something not in the code, fix the doc
   (or file it in [`open_items.md`](./open_items.md)) — never invent behavior.
2. **Governance.** No internal namespaces or internal-only capabilities in public docs (the gate is the
   boundary). $ = list-price estimates.
3. **No dead links / stale diagrams.** Every internal link resolves; regenerate diagrams whose `.mmd`
   source describes the old architecture (`make diagrams` / `scripts/generate_diagrams.py`).
4. **Personas end-to-end.** Each area serves the developer and/or user persona with a clear path from
   install → first success → depth.
5. **`changes` folder is out-of-bounds.** Do not clean-up, change or alter documents captured in the `changes` folder. You may append your status, progress and reports to the relevant tracking document but this folder should not be cleaned up.

## Method (lead)

- Assign the disjoint areas below; dispatch one worktree agent each (**first step:**
  `git merge --no-edit <integration-branch>`). Reconcile cross-references, `docs/index.md` nav, and
  duplicate/overlapping docs centrally. Verify `make docs`/mkdocs builds (see `mkdocs.yml`) and
  `scripts/check_doc_staleness.py` passes.

## Workstreams (disjoint ownership)

### A — Governance docs (root, agent-facing) — **create + align**
- **Create `AGENTS.md`** and a **project `CLAUDE.md`** at repo root (neither exists today): how coding
  agents should work in this repo — build/test/lint commands, the worktree/verify-after-merge pattern,
  the 3-package layout + kernel-purity/import-linter contracts, the governance red-lines, and the
  additive-gate rule. Keep them short and command-accurate. Reconcile with `CONTRIBUTING.md`.
- Owns: `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `README.md`.

### B — User docs (persona: user) — end-to-end
- `docs/QUICKSTART.md`, `QUICK_REFERENCE.md`, `docs/guides/GETTING_STARTED.md`, `docs/user-guide/**`
  (cli, workflows/*, understanding-reports, troubleshooting), `docs/overview/**`, `examples/*.ipynb`
  narrative. Add/refresh workflows for the **new** surfaces: `starboard review` (workload review),
  `genie ask`, workspace discovery. Ensure the install matrix (`pip install starboard` vs `-skills` vs
  extras) is correct.
- Owns: `docs/QUICKSTART.md`, `docs/QUICK_REFERENCE.md`, `docs/guides/**`, `docs/user-guide/**`,
  `docs/overview/**`, `docs/SKILLS.md`.

### C — Developer & architecture docs (persona: developer)
- `docs/architecture/SYSTEM_ARCHITECTURE.md`, `docs/TOOL_ARCHITECTURE.md`, `docs/developer/**`,
  `docs/packages/**`, `docs/api/API_REFERENCE.md`, `docs/agents/**`, `docs/contracts/**`,
  `docs/integration/**`, `docs/TESTING.md`, `docs/MAKEFILE_GUIDE.md`. Update to the ports+gate model, the
  kernel/`starboard_x` split, the RuleRegistry/Finding schema, the entry-point adapter/tool seams, and
  the internal-package boundary. Document `starboard-internal` and `starboard-plugin-sample` at the
  architecture level (public docs describe the *seam*, not internal contents).
- Owns: `docs/architecture/**`, `docs/developer/**`, `docs/packages/**`, `docs/api/**`, `docs/agents/**`,
  `docs/contracts/**`, `docs/integration/**`, `docs/tools/**`, `docs/TOOL_ARCHITECTURE.md`,
  `docs/TESTING.md`, `docs/MAKEFILE_GUIDE.md`.

### D — Admin/ops, config, distribution — and de-duplication
- `docs/admin/**`, `docs/RUNBOOK.md`, `docs/runbooks/**`, `docs/DEPLOYMENT.md`, `docs/CONFIGURATION.md`,
  `docs/TOKEN_BUDGET.md`, `docs/INTERRUPTIBLE_REASONING.md`, `docs/S3_CONNECTOR_GUIDE.md`. Update
  `state-backends.md` to memory/UC defaults + extras. **Reconcile duplicates:** fold
  `docs/AGENT_SKILLS_DISTRIBUTION.md` ↔ `docs/distribution/databricks-aitools.md` into one, and
  `docs/HOST_COVERAGE.md` ↔ `docs/CLAUDE_CODE_INTEGRATION.md` into a coherent reach story (keep one
  canonical, cross-link).
- Owns: `docs/admin/**`, `docs/runbooks/**`, `docs/distribution/**`, `docs/RUNBOOK.md`,
  `docs/DEPLOYMENT.md`, `docs/CONFIGURATION.md`, `docs/HOST_COVERAGE.md`,
  `docs/AGENT_SKILLS_DISTRIBUTION.md`, `docs/CLAUDE_CODE_INTEGRATION.md`, `docs/*_GUIDE.md`.

### E — Diagrams (lead or a 5th agent)
- Audit `docs/diagrams/source/*.mmd`; regenerate PNGs. Update or retire diagrams describing the retired
  architecture (embedding-RAG, reflexion memory, default sqlite/postgres state). Add diagrams for the
  ports+gate, workload-review flow, and the layered catalog.

## Definition of done
- Every documented command/import/flag/path verified against `main`; `scripts/check_doc_staleness.py`
  passes; the docs site builds (`mkdocs`), no dead internal links.
- Root `AGENTS.md` + `CLAUDE.md` exist, are command-accurate, and agree with `CONTRIBUTING.md`.
- Duplicate docs reconciled to one canonical each; `docs/index.md` nav reflects the final set.
- Developer and user personas each have a coherent end-to-end path; new Phase-3 surfaces (review, genie,
  gate, catalog) are documented; governance red-lines and list-price-$ framing are consistent throughout.
