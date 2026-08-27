# Phase 3 — Flagship & Strategic: Detailed Implementation Plan

> The differentiators. Builds on Phase 0 (foundations), Phase 1 (packaging/tiers,
> the D3 `Finding` schema + seed rules, `starboard_x`), and Phase 2 (native
> architecture + the **ports with public adapters behind a closed-by-default
> gate**). Phase 3 **attaches the gated internal adapters** to those ports and
> ships the **Workload Review** flagship on top of the harvested methodology.
> Evidence: `internal_harvest/`, `agent_integration/`, `starboard_optimization/`
> `technical.md`; UNIFIED_PLAN §3.5 (the gate), §4 (Phase 3), §7 (governance).
>
> **Phase 3 items (UNIFIED_PLAN §4):** D1 Workload Review engine · D6 internal
> diagnostic/log adapters · D7 fleet mode · D8 Genie · D9 Codex/OpenCode +
> `.isaac/rules/` · D10 Apps OBO · B5 layered catalog / per-domain plugins. Plus
> the three Phase-2-review items routed here (managed-VS `columns`, similarity-cache
> backend routing, NL→domain recall — see §11).

---

## 0. Goal & definition of done (phase-level)

**Goal:** deliver Starboard's differentiating capability — a **"Workload Review"** that reviews a
customer's jobs/queries/warehouses the way Isaac `/review` reviews code — built entirely from
**harvested methodology running on public `system.*` data**, and then **light up the gated internal
adapters** (dbr-doctor / logs-summariser / centralized fleet tables / Genie) so the same capabilities
run with higher fidelity for authorized Databricks employees — **additively, never reducing the public
capability** (UNIFIED_PLAN §3.5).

Phase 3 runs as **three workstreams**:
- *3a Flagship (public):* **D1** Workload Review engine on public data + the Phase-1 `Finding` schema.
- *3b Internal enablement (gated):* **D6/D7/D8** internal adapters attached to the Phase-2 ports,
  shipped **outside the public wheel** (see D-3.1) and selected by the closed-by-default gate.
- *3c Reach & hosting:* **D9** Codex/OpenCode host coverage + `.isaac/rules/`, **D10** Apps OBO,
  **B5** layered catalog / per-domain plugins.

**Phase-3 exit criteria (all must hold):**
1. **Workload Review runs end-to-end on public data:** `starboard review <workspace>` (and the
   `workload-review` skill / `starboard_x` helper) produces a ranked `Finding` set with severity ×
   impact/effort scores, evidence citations (query-pack `query_id` + row refs), and remediation, using
   only `system.*` + reference files — **no internal data, no MCP required**. *(D1)*
2. A **RuleRegistry** loads the Phase-1 D3 seed rules as its first rule sets, each rule names a **real**
   query-pack `evidence_query` (closes Phase-1 finding #3), and rules are versioned + testable in
   isolation. *(D1)*
3. A **validator council** (multi-pass self-critique / model-ensemble) gates findings before they
   surface; a **severity gate** suppresses low-confidence/low-impact noise; the loop is bounded and
   deterministic under a fixed seed (no unbounded model spend). *(D1)*
4. **Ports gain internal adapters** (`LogRetrievalPort`→logs-summariser, `DiagnosticBackendPort`→
   dbr-doctor, `FleetSqlPort`→centralized tables, `NLQueryPort`→Genie). Each is a **strict superset**
   of its public adapter: with the gate closed the public adapter is used and every capability still
   works; with the gate open the internal adapter **enriches or replaces** results. A parity test
   asserts no capability is lost when the gate closes. *(D6/D7/D8, §3.5 invariant)*
5. **Internal adapters ship separately from the public wheel** (D-3.1): the public wheel contains the
   ports + public adapters + gate + a registration entry-point contract only. Internal adapters live in
   a **separately-distributed internal package** that registers via entry points; **`pip install
   starboard` from a public index never pulls internal-namespace code.** *(§7)*
6. **`genie ask`** exposes NL→SQL through the `NLQueryPort` public path (native analytics-SQL
   generation) with the curated-Genie-room internal adapter behind the gate. *(D8)*
7. **Host coverage:** Codex and OpenCode can invoke the skills/helpers (documented + smoke-tested);
   a baseline `.isaac/rules/` guidance file ships. *(D9)*
8. **Apps OBO auth** path exists (`ModelServingUserCredentials()` wired through the A1 resolver's
   `credentials_strategy` seam) so a multi-tenant Databricks App resolves per-user UC/Genie grants;
   documented + tested with a stub credentials strategy. *(D10)*
9. **Layered catalog / per-domain plugins:** capability tiers (kernel → capability → experience) are
   installable independently; optional per-domain plugins discover tools via a `starboard.mcp_tools`
   (or equivalent) entry-point contract. *(B5)*
10. **Governance grep** of the **public** wheel + all shipped public artifacts finds **no** internal
    namespaces (`centralized_system_tables`, `fin_live_gold`, `gtm_*`, `eng_*`, logfood workspace,
    ClickHouse, `hmr_stack_hash`, `go/…`); internal identifiers exist only in the separately-distributed
    internal package. **$ on the public path stays a list-price estimate; finance-grade $ only via the
    internal adapter.** *(§3.5/§7)*
11. Repo-wide gates green: `ruff`, `mypy`, `pytest`, **import-linter** (kernel boundary holds; the new
    contract "public wheel imports no internal-adapter package" is added and KEPT).

**Phase 3 is gated on five owner/validation inputs (UNIFIED_PLAN §6 + OWNER_RUNBOOK G3–G6):**
the Action-Rate feedback-loop design (D1, no PR/merge gate — synthesize via re-scan), the available
model ids for the validator council in a customer deployment (D1), Isaac plugin onboarding + review
gates (G3), the `databricks aitools` bundle format (G4), and Genie auth in the target workspace (G6).

## 1. Guardrails (apply to every task)

- **TDD:** failing test(s) first, then implement to green. Each task lists its tests.
- **Additive / back-compat / no capability regression** — the UNIFIED_PLAN §3.5 invariant is now
  load-bearing: **closing the gate must never remove or degrade a capability.** Every internal adapter
  ships with a parity test proving the public adapter alone satisfies the capability contract.
- **The gate is the governance boundary** — internal data flows **only** through the gated internal
  adapter at runtime, and internal-adapter code **does not ship in the public wheel** (D-3.1). Public
  artifacts stay clean (§7); grep before release.
- **Harvest methodology, not artifacts** — rules/prompts/heuristics are **paraphrased** re-expressions
  of internal methodology; no internal prompt text, namespace, or `go/` link enters public code.
- **Bounded model spend** — the validator council and Action-Rate loop are bounded (max passes/attempts,
  fixed seed where possible); no unbounded fan-out. Document the per-run ceiling.
- **Kernel boundary holds** — import-linter: kernel stays free of `databricks-sdk`/`openai`/`fastapi`/
  `mcp`; the RuleRegistry + `Finding` scorer live in the kernel (pure), adapters do not.
- **Verification per task:** `ruff`, `mypy`, `lint-imports`, and the task's pytest selection pass before
  the task is "done"; run the three package test dirs **separately** (cross-package basename collision).

## 2. Branch & PR strategy

Off `main` (Phases 0–2 landed). Workstreams **3a/3b/3c** are largely independent. Reviewable PRs:

| PR | Item | Workstream | Branch | Rough size |
|----|------|-----------|--------|-----------|
| 1 | D1a RuleRegistry + `Finding` scorer wiring (seed rules → real `evidence_query`) | 3a | `phase3/rule-registry` | M |
| 2 | D1b Workload Review engine + `review` CLI/skill/helper (public data) | 3a | `phase3/workload-review` | L |
| 3 | D1c validator council + severity gate + bounded Action-Rate re-scan loop | 3a | `phase3/validator-council` | M–L |
| 4 | D-3.1 internal-package skeleton + entry-point registration contract + import-linter contract | 3b | `phase3/internal-package-seam` | M |
| 5 | D6 internal adapters (logs-summariser `LogRetrievalPort`, dbr-doctor `DiagnosticBackendPort`) | 3b | `phase3/internal-diagnostic-adapters` | M–L |
| 6 | D7 fleet-mode internal `FleetSqlPort` adapter (namespace-rewrite over centralized tables) | 3b | `phase3/fleet-mode` | M |
| 7 | D8 Genie: `NLQueryPort` public NL→SQL + `genie ask` + gated curated-room adapter | 3b | `phase3/genie` | M |
| 8 | D9 Codex/OpenCode host coverage + `.isaac/rules/` baseline | 3c | `phase3/host-coverage` | S–M |
| 9 | D10 Apps OBO auth (per-user credentials strategy through the A1 seam) | 3c | `phase3/apps-obo` | M |
| 10 | B5 layered catalog / per-domain plugins (entry-point discovery) | 3c | `phase3/layered-catalog` | L |

**Dependency edges (see §12):** D1a → D1b → D1c (the flagship is sequential). D-3.1 (PR4) is the
**seam that must land before any internal adapter** (D6/D7/D8 register through it). D6/D7 reuse the
Phase-2 C5 ports unchanged; D8's public half reuses `NLQueryPort`. D9/D10/B5 are independent of the
flagship and can proceed in parallel. Each PR: reviewed with `/review`, gates green, merged; the
per-phase land-to-`main` flow follows Phases 0–2 (await user review before landing).

## 3. Decisions to lock before coding

| # | Decision | Recommendation | Rationale |
|---|----------|---------------|-----------|
| D-3.1 | **Where do internal adapters live** so their namespaces never ship publicly? | A **separately-distributed internal package** (e.g. `starboard-internal`, internal index only) that registers adapters through a `starboard.port_adapters` **entry-point contract**. The public wheel ships ports + public adapters + the registry + the entry-point *contract*, never an internal adapter. | Makes §7 an enforced build property, not a review checklist. import-linter contract: "public packages import no `starboard_internal` module." Aligns with B5's entry-point discovery. |
| D-3.2 | **Validator council** shape | Bounded **multi-pass self-critique** with an optional **model-ensemble** when >1 model id is available; fixed max passes; deterministic seed for tests. Model ids resolved from config (OWNER input G5). | Bounds spend; degrades to single-pass when only one model is available; testable. |
| D-3.3 | **Action-Rate feedback loop** (no PR/merge gate exists for workloads) | Synthesize the loop via **re-scan**: persist findings, re-run the review after N days, compute a resolved-rate delta. No write-back to the customer workspace. | Workloads have no merge event; re-scan is the observable proxy. Read-only. |
| D-3.4 | **Fleet mode** mechanism | A **namespace-rewrite adapter** over `FleetSqlPort`: rewrite `system.<schema>` → centralized-tables equivalents at query-build time; **near-zero pack edits** (packs stay public + unchanged). Internal-package-only. | UNIFIED_PLAN D7; keeps public packs clean; the rewrite table is internal. |
| D-3.5 | **Genie** integration | Public: `NLQueryPort` native analytics-SQL generation + `genie ask` (NL→SQL over the resolved workspace). Internal (gated): route to **curated Genie rooms** for higher fidelity. | Public path universal; curated rooms are internal enrichment. |
| D-3.6 | **Apps OBO** | Reuse the A1 resolver's `credentials_strategy` seam with `ModelServingUserCredentials()`; do **not** add a new auth path. | A1 already exposes the seam (`resolve_workspace_client(credentials_strategy=…)`); OBO is per-request strategy injection. |
| D-3.7 | **Workload Review scope (v1)** | Ship **jobs + queries + warehouses** review first (the three highest-value, best-covered public surfaces); DLT/ML/pipelines are v2. | Depth over breadth for the flagship; matches the strongest seed-rule coverage. |
| D-3.8 | **$ semantics** | Public review = **list-price DBU estimates**, labeled as estimates everywhere. Finance-grade $ only via the internal adapter (`fin_live_gold`), never on the public path. | §7 red-line; consistent with Phases 0–2. |

## 4. Task D1 — Workload Review engine (flagship, workstream 3a)

**Goal:** review a workspace's jobs/queries/warehouses and emit a ranked, evidence-backed `Finding` set,
the way Isaac `/review` reviews code — on **public data only**.

**D1a — RuleRegistry + scorer (PR1).**
- Kernel `RuleRegistry` (pure) that loads the Phase-1 D3 seed rules (`domain/rules/seed/*.yaml`),
  validates each rule's `evidence_query` against the live query-pack registry, and exposes
  `rules_for(domain)`.
- **Closes Phase-1 review finding #3:** repoint the five dangling `evidence_query` strings
  (`query_performance.*`, `warehouse.*`, `uc.*`) to real pack `query_id`s, and add the
  `test_seed_rules.py` validating test that was planned but not implemented in Phase 1.
- Wire the D3 severity × impact/effort scorer to produce a total order.
- **Tests:** every seed rule resolves to a real `query_id`; scorer ordering is stable; registry is
  pure (import-linter — no SDK).

**D1b — Review engine + surfaces (PR2).**
- `WorkloadReviewService` (kernel-adjacent, public data): run the relevant query packs for the target
  workspace → feed rows to the RuleRegistry → produce scored `Finding`s with evidence citations
  (`query_id` + row refs) and paraphrased remediation.
- Surfaces: `starboard review [--domains jobs,sql,warehouse] [--workspace …]` CLI, a `workload-review`
  skill (dual-mode), and a `starboard_x` helper emitting the Phase-0 JSON envelope + exit codes.
- **Tests:** golden review over a fixture `system.*` dataset → expected ranked findings; empty/degraded
  data degrades gracefully (no crash, partial findings); `--domains` filters correctly.

**D1c — Validator council + severity gate + Action-Rate loop (PR3).**
- Bounded validator council (D-3.2): each candidate finding is self-critiqued / ensemble-voted; a
  severity gate drops sub-threshold findings; the pass count is bounded and seedable.
- Action-Rate re-scan loop (D-3.3): persist a review snapshot; `starboard review --since <prior>`
  computes resolved-rate delta. Read-only; no workspace write-back.
- **Tests:** council is deterministic under a fixed seed; severity gate suppresses a known-noise
  fixture; re-scan delta computes correctly against two snapshots; spend ceiling is enforced (max
  passes asserted).

## 5. Task D-3.1 — Internal-package seam + registration contract (PR4, workstream 3b — **lands before any internal adapter**)

- Define a `starboard.port_adapters` **entry-point contract**: the public registry discovers adapters
  by entry point; if the internal package is installed, its adapters register and (when the gate opens)
  supersede the public ones.
- Create the internal-package skeleton (`starboard-internal`, internal index only) with a no-op sample
  adapter to prove the seam. The public wheel ships **only** the contract + registry.
- **import-linter contract (new, KEPT):** "public packages (`starboard`, `starboard_core`,
  `starboard_x`, `starboard_skills`) import no `starboard_internal.*` module."
- **Tests:** with the internal package absent, the public adapter is selected and every port capability
  works (parity); with a stub internal package present + gate open, its adapter is selected; governance
  grep of the public wheel is clean.

## 6. Task D6 — Internal diagnostic/log adapters (PR5, gated)

- `LogRetrievalPort` internal adapter → **logs-summariser** indexed ClickHouse triage (vs. the public
  adapter's delivered-log parsing). `DiagnosticBackendPort` internal adapter → **dbr-doctor** semantic
  layer + trace-RCA + `hmr_stack_hash` (vs. the public extractor + harvested evidence-tag/RCA model).
- Both live in `starboard-internal`; both are **strict supersets** — the parity test asserts closing
  the gate leaves the public capability whole.
- **Tests (in the internal package):** gate-open routes to the internal adapter; gate-closed routes to
  public; enrichment fields are additive (public fields still present); no internal namespace leaks to
  a `Finding` rendered on a would-be public surface.

## 7. Task D7 — Fleet-mode internal adapter (PR6, gated)

- `FleetSqlPort` internal adapter: namespace-rewrite over `centralized_system_tables.*` giving a
  cross-account fleet view with **near-zero pack edits** (D-3.4). Public `FleetSqlPort` adapter stays
  single-workspace `system.*`.
- **Tests:** rewrite maps `system.<schema>.<table>` → centralized equivalent for the covered set;
  gate-closed keeps single-workspace behavior; public packs are byte-for-byte unchanged.

## 8. Task D8 — Genie (PR7)

- **Public:** `NLQueryPort` native NL→SQL generation + `genie ask "<question>"` over the resolved
  workspace (uses the A1 client; no internal dependency).
- **Internal (gated):** route to **curated Genie rooms** for higher-fidelity answers.
- **Tests:** `genie ask` produces valid SQL against a fixture schema; gate-closed uses native
  generation; gate-open routes to the curated-room adapter (stubbed).

## 9. Task D9 — Codex/OpenCode host coverage + `.isaac/rules/` (PR8, workstream 3c)

- Confirm + document that the skills/helpers run under **Codex** and **OpenCode** hosts (the no-MCP
  path); add host-specific invocation docs and a smoke test per host where feasible.
- Ship a baseline `.isaac/rules/` guidance file (paraphrased, public) so Isaac sessions get sane
  defaults.
- **Tests/gates:** helper `python -m starboard_x …` runs under each host's invocation convention;
  `.isaac/rules/` passes governance grep.

## 10. Task D10 — Apps OBO auth (PR9, workstream 3c)

- Wire **`ModelServingUserCredentials()`** through the existing A1 seam
  (`resolve_workspace_client(credentials_strategy=…)`) so a multi-tenant Databricks App resolves
  **per-user** UC/Genie grants (D-3.6). No new auth path.
- **Tests:** a stub credentials strategy proves per-user resolution flows through `build_config` +
  `resolve_workspace_client`; describe_auth stays redacted; the default (no strategy) path is unchanged.

## 11. Task B5 — Layered catalog / per-domain plugins (PR10, workstream 3c)

- Make the capability tiers (kernel → capability → experience) independently installable (thin wheels)
  and let optional **per-domain plugins** register tools via the `starboard.mcp_tools` (or the
  D-3.1 `port_adapters`) entry-point contract.
- **Tests:** installing only the kernel tier works; a per-domain plugin registers its tools via entry
  point and is discoverable; absent plugins degrade cleanly.

## 12. Carried-over Phase-2 review findings (fold into this phase)

From `reviews/phase2_review_findings.md` (all on the opt-in managed-VS path or a design decision):
- **#1 managed VS `columns=["*"]`** and **#3 similarity-cache backend routing** — fix within D6/D8-era
  managed-VS work, validated against a **live** Vector Search index (schema was unknowable at review
  time). Both only bite when someone opts into `vector_backend="vectorsearch"`.
- **#2 NL→domain recall** — a **Phase-3 design decision** (D1 is the main consumer): add a lightweight
  keyword→domain mapping so un-annotated NL queries still select a reference-file domain. Decide as part
  of D1b's retrieval quality.
- **#4/#6** (TTL-cache tag flush; build-script parse fragility) — low-priority hardening tracked as
  follow-ups; **#6** gets the CI parse-roundtrip guard alongside the Preview-pack schema-validation
  follow-up.

## 13. Task ordering & dependency graph (within Phase 3)

```
D1a RuleRegistry ─► D1b Review engine ─► D1c validator council + Action-Rate      [3a, sequential]

D-3.1 internal seam ─┬─► D6 diagnostic/log adapters                                [3b]
   (lands first)     ├─► D7 fleet mode
                     └─► D8 (gated curated-room half)
D8 public NL→SQL ────(independent of the seam)

D9 host coverage ─(independent)─►                                                  [3c parallel]
D10 Apps OBO     ─(independent, reuses A1 seam)─►
B5 layered catalog ─(independent; shares entry-point contract with D-3.1)─►
```

**Longest pole:** D1a → D1b → D1c (the flagship). **Fast independent value:** D9, D10, D8-public.
**Hard gate:** D-3.1 must land before D6/D7/D8-internal.

## 14. Verification & Definition of Done (phase-level)

- All 10 PRs reviewed with `/review`, gates green (`ruff`, `mypy`, `lint-imports`, `pytest` per package
  dir separately), merged.
- Exit criteria §0 (1)–(11) all demonstrably hold; the **§3.5 additive invariant parity tests** pass
  for every port.
- **Governance grep** of the public wheel + shipped public artifacts is clean; the new import-linter
  contract ("public packages import no `starboard_internal.*`") is KEPT.
- Workload Review demoed on a live public workspace (e.g. `e2-demo-field-eng`) producing ranked
  findings with evidence — the flagship acceptance demo.

## 15. Risks & mitigations

| Risk | Mitigation |
|------|-----------|
| Validator council → unbounded model spend | Hard max-pass ceiling + fixed seed (D-3.2); assert the ceiling in tests; the **$2250 `ai-devtools-prod-runaway` cap** must be raised before council dev. |
| Internal namespace leaks into the public wheel | D-3.1 separate package + import-linter contract + governance grep in CI; internal-adapter code never in the public tree. |
| Capability regression when the gate closes | Per-port parity test is a merge gate for every internal adapter (§3.5 invariant). |
| Action-Rate has no merge/PR event for workloads | Re-scan proxy (D-3.3), read-only; no workspace write-back. |
| Managed-VS fixes (#1/#3) guessed wrong | Validate against a **live** VS index before merging; keep the opt-in default off. |
| Owner gates unanswered (G3–G6, model ids) | D9/D10/B5 proceed independently; flagship D1 needs the model-id + Action-Rate design inputs — sequence D1c after they land. |

## 16. Explicitly out of scope for Phase 3 (deferred)

- **Workload Review v2 surfaces** (DLT/ML/pipelines/vector-search) — after the jobs/sql/warehouse v1
  (D-3.7).
- **Write-back / auto-remediation** into customer workspaces — Phase 3 is read-only advisory.
- **A curated public Genie space** (beyond `genie ask`) — later.
- **Multi-tenant hosting hardening** beyond the OBO auth path (rate-limits, quotas, per-tenant state).

---

## Implementation status (2026-08-27)

Built + verified on branch **`phase3/foundations`** (off `main`; **not pushed / not landed** — awaiting
review, per the Phase 0/1/2 pattern). Worktree-agent + verify-after-merge; suites run separately.

| Item | Status | Notes |
|------|--------|-------|
| **D1a** RuleRegistry + Finding scorer | ✅ built + verified | kernel `RuleRegistry`; **closed Phase-1 finding #3** (repointed 5 dangling `evidence_query` → real pack query_ids) |
| **D-3.1** internal-package entry-point seam | ✅ built + verified | `starboard.port_adapters` contract + `starboard-internal` pkg (no-op sample) + **4th import-linter contract** "public packages import no `starboard_internal`" |
| **D1b** Workload Review engine (flagship) | ✅ built + verified | `WorkloadReviewService` (public `system.*`, jobs+sql+warehouse v1); surfaces: `starboard review` CLI, `workload-review` skill, `python -m starboard_x.review`; evidence citations (`query_id`+row); list-price $ |
| **D10** Apps OBO auth | ✅ built + verified | `ModelServingUserCredentials` via the A1 `credentials_strategy` seam; stub-tested; default path unchanged |
| **D8-public** `genie ask` | ⏳ deferred (scoped) | needs the LLM-backed SQL-generator wired into `AnalyticsSqlAdapter` — a focused follow-up, not a trivial CLI wrapper |
| **D9** host coverage + `.isaac/rules` | ⏳ deferred | design resolved (`PHASE_3_D9_host_coverage.md`); ships `.isaac/rules` in the plugin bundle |
| **B5** layered catalog / per-domain plugins | ⏳ deferred (L) | builds on the D-3.1 entry-point contract |
| **D1c** validator council + Action-Rate | ⏸ **gated** | needs **G5** (available model ids for the council) + the Action-Rate design decision |
| **D6/D7** internal diagnostic/log + fleet adapters | ⏸ **gated** | need internal-tool access; **internal-package-only** (never in the public wheel) |
| **D8-internal** curated Genie rooms | ⏸ **gated** | needs **G6** (Genie auth in the target workspace) |

**Verification (phase3/foundations tip `549aeede`):** core **700** / starboard **3163** / skills **28** /
internal **6** pass (separate invocations); **import-linter 4 contracts KEPT**; ruff + mypy clean.

**Known non-blocking gaps / follow-ups:**
- D1b engine supports the **jobs** domain but D1a ships **no `jobs` seed ruleset** yet — add one (small, D1a-style).
- D8-public SQL-generator wiring; B5; D9 `.isaac/rules` file + host smoke tests.
- Carried Phase-2 review items #1/#3 (managed-VS `columns`/cache backend) still apply on the opt-in path.

**Learning:** worktree agents branch off **`origin/main`**, not local HEAD — an agent needing unmerged local
work can land on a stale base (D10 did, harmlessly, since its work was self-contained). Verify each item
branch's merge-base before merging; prefer building items that depend on unmerged local work **directly** in
the main tree.
