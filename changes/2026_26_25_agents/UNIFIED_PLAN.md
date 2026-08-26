# Starboard — Unified Recommendations & Implementation Plan

> Coalesces all **7 envisioning topics** (Round 1: agent-integration, auth, optimization,
> decomposition · Round 2: progressive-helpers, internal-harvest, native-simplification) into **one
> prioritized recommendation set** and a **high-level, dependency-ordered implementation plan** for review.
> Evidence lives in each topic's `opportunities/recommendation/technical.md`; this doc references, not repeats, it.
> Baseline: starboard 0.1.1 @ `b927dfaa`. **Envisioning only — nothing here is built yet.**

---

## 1. The unifying vision (one paragraph)

Turn Starboard from a **heavy, server-centric, store-backed monolith** into a **native, file-based,
server-optional toolkit** that ships as **skills/plugins** and reaches both internal engineers (via
Isaac) and external customers (via Claude Code / `databricks aitools`). Depth is delivered on a
**3-tier model** — a zero-dep fetch CLI, dep-ful progressive-disclosure helper scripts, and an
optional MCP server for full LLM orchestration — with **no required external store** (in-memory +
Databricks-native UC state; RAG replaced by reference files + query packs) and **auth by subtraction**
(delegate to the SDK credential chain). The public-data path is universal; an **internal-data
enablement gate** additively lights up richer internal backends (dbr-doctor, LogFood, logs-summariser,
centralized/fleet tables) for Databricks employees — enriching or replacing results, never reducing the
public capability. Its differentiating new capability is a **"Workload Review"** that reviews a
customer's jobs/queries/warehouses the way Isaac `/review` reviews code, built from **harvested internal
methodology** running on public data — and deepened by real internal telemetry when the gate is open.

## 2. Design principles (the throughlines across all 7 topics)

1. **Native & file-based over infrastructure.** Progressive-disclosure files, YAML registries, and
  query packs instead of servers, vector DBs, and external stores. *(5, 6, 7)*
2. **Subtraction over addition.** The simplest wins are deletions: forced auth → SDK chain; required
  stores → optional extras; RAG vector DB → reference files. *(2, 7)*
3. **One implementation, many surfaces.** Each capability backs a lib, a CLI, a skill, an MCP tool.
  *(4, 5)*
4. **Skills-first, MCP-optional.** Lead with the frictionless no-server path; offer depth as opt-in. *(1, 5)*
5. **Harvest methodology, ship on public data.** Capture expert IP; the *public* path never contains
  internal data/namespaces. *(6)*
6. **Reach where users already are.** Isaac wraps Claude Code → one plugin reaches the whole org. *(1)*
7. **Internal data is additive, gated, never required.** Every internal-augmentable capability is a
  **port with two adapters** — a public adapter (default, universal) and an internal adapter (gated to
   employees). The internal path **enriches or replaces** results; disabling it always leaves a
   fully-functional public capability. Enabling internal must never reduce what's available. *(3, 6)*

## 3. Unified recommendations (deduplicated, grouped into 4 pillars)

Consensus items (flagged by multiple independent streams) are marked **‹consensus›**.

### Pillar A — Foundations (shared prerequisites; do first)


| #   | Recommendation                                                                                                                                                 | Sources | LOE |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- | --- |
| A1  | **Auth by subtraction** — one `resolve_workspace_client()`; pass only set fields to SDK `Config`; drop forced host/token; PAT stays one strategy               | 2       | S–M |
| A2  | **Collapse skill duplication + fenced `SKILL.md` frontmatter** — one canonical `skills/` tree, vendored not copied ‹consensus: 1,3,4›                          | 1,3,4   | S   |
| A3  | **Zero-store default** — flip cache/rate-limit to in-memory; move `redis`/`asyncpg`/`pgvector`/`aiosqlite`/`sqlite-vec` to optional extras; Protocol preserved | 7       | S   |
| A4  | **Harden `starboard-helper` CLI** — stable JSON contract; add `analyze`/`discovery`/`genie` verbs so 9 skills map 1:1                                          | 1,3     | S–M |
| A5  | **4 mapped-but-unimplemented query packs** — Predictive Optimization, Data Quality, Data Classification, Networking already route to an empty pack             | 3       | S   |


### Pillar B — Packaging, tiers & distribution


| #   | Recommendation                                                                                                               | Sources | LOE |
| --- | ---------------------------------------------------------------------------------------------------------------------------- | ------- | --- |
| B1  | **Carve `starboard-kernel`** — pure DTOs + analyzers, pydantic/polars only, no `databricks-sdk`                              | 4       | M   |
| B2  | `**starboard-x` middle tier** — dep-ful `python -m` helpers via progressive disclosure, per-capability extras (3-tier model) | 5       | M   |
| B3  | **Skills-only Claude Code plugin + `marketplace.json`** — reaches Claude Code **and** all Isaac users                        | 1       | M   |
| B4  | `**databricks aitools install**` distribution for external customers                                                         | 1       | S–M |
| B5  | **Layered catalog / thin wheels** (kernel → capability → experience tiers); optional per-domain plugins                      | 4       | L   |
| B6  | **Optional-MCP toggle in the same plugin** — raise depth ceiling to the 7-agent stack without a 2nd artifact                 | 1,5     | M   |


### Pillar C — Native architecture (store-free)


| #   | Recommendation                                                                                                                                                                                                                                                                                                               | Sources | LOE |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- | --- |
| C1  | **RAG → progressive-disclosure reference files + query packs** (the marquee simplification; drops sqlite-vec + embeddings + `.npz`)                                                                                                                                                                                          | 7,6     | M–L |
| C2  | **Native UC-table state** — promote the orphaned `UCStorageAdapter`/`repository.py` as Protocol state/memory/user/feedback stores (reuses A1's client)                                                                                                                                                                       | 7       | M   |
| C3  | **JSON/agent-host CLI sessions** — replace the `aiosqlite` CLI session store; thin CLI needs no driver                                                                                                                                                                                                                       | 7       | M   |
| C4  | **Retire dormant memory/reflexion by default**; semantic cache TTL-only                                                                                                                                                                                                                                                      | 7       | S   |
| C5  | **Internal-data enablement gate** — a port/adapter interface where each internal-augmentable capability has a public adapter (default) + a gated internal adapter (dbr-doctor, LogFood, logs-summariser, centralized/fleet tables), selected by employee-context detection + authorization; **strictly additive** (see §3.5) | 3,6,2   | M   |


### Pillar D — Capability expansion (differentiators)


| #   | Recommendation                                                                                                                                                                                                    | Sources | LOE   |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- | ----- |
| D1  | **Workload Review (flagship)** — harvest `/review` methodology (rule registry + validator council + severity gate + Action-Rate loop) to review workspaces; on the existing pattern registry                      | 6       | L     |
| D2  | **Harvest LogFood metric framings** → warehouse/finops/compute packs (utilization bands, auto-stop waste, load buckets, client-app mix, trend windows)                                                            | 6       | S–M   |
| D3  | **Shared Finding schema + seed rules** from `databricks-elt-review` (severity×impact/effort scorer + per-domain checklists)                                                                                       | 6       | S–M   |
| D4  | **Progressive-helper depth**: diagnostic RCA pack, discovery `data_only`, sparklog, warehouse/uc analyzers, chart-renderer                                                                                        | 5       | M–L   |
| D5  | **New data packs + reuse**: compute reliability/right-sizing, column-lineage, discovery result caching                                                                                                            | 3       | M     |
| D6  | **Internal-tool methodology harvests**: log-triage (logs-summariser), trace-RCA + query-diff + evidence-tags (dbr-doctor) — public adapter; the real internal tools attach as the **gated internal adapter** (C5) | 6       | M–L   |
| D7  | **Fleet mode** — namespace-rewrite adapter over centralized system tables (near-zero pack edits); an **internal adapter behind the gate** (C5)                                                                    | 3       | M     |
| D8  | **Genie** — consume via `genie ask` (NL→SQL), later expose a curated space                                                                                                                                        | 1,3     | M / L |
| D9  | **Codex + OpenCode host coverage**; `.isaac/rules/` baseline guidance                                                                                                                                             | 1       | S–M   |
| D10 | **Apps OBO auth** (deferred) — per-user UC/Genie grants for multi-tenant hosting                                                                                                                                  | 2       | L     |


## 3.5 The Internal-Data Enablement Gate (C5) — additive by construction

The gate is how the two ends of the study meet: **Topic 6** harvests internal *methodology* to run on
public data (the default, universal path), and **Topic 3** wires the *real internal tools* as backends.
They are the **two adapters behind one port** — the gate chooses which is active.

**The port pattern.** Each internal-augmentable capability is a Protocol with two adapters:


| Port                    | Public adapter (default, ships to everyone)                          | Internal adapter (gated, employees) — enriches/replaces            |
| ----------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `LogRetrievalPort`      | parse delivered log4j/event logs from DBFS/Volumes                   | `logs-summariser` indexed ClickHouse triage                        |
| `DiagnosticBackendPort` | Starboard extractors + harvested evidence-tag/RCA model              | `dbr-doctor` semantic layer + trace-RCA + `hmr_stack_hash`         |
| Metric packs            | `system.*` + harvested LogFood framings; **$ = list-price estimate** | LogFood JVM/GC/crash detail; **finance-grade $** (`fin_live_gold`) |
| `FleetSqlPort`          | single-workspace `system.*`                                          | `centralized_system_tables.*` cross-account fleet view             |
| `NLQueryPort`           | native analytics-SQL generation                                      | curated Genie rooms                                                |


**The additive rule (invariant).** Enabling the internal adapter may **enrich** (add fields, depth,
accuracy) or **replace** a result with a higher-fidelity one — but must **never remove or degrade** a
capability. Disabling it (external customer, gate closed) always leaves a fully-functional public path.
Capabilities are declared public-first; the internal adapter is a superset.

**Gating.** Open the gate when **both** hold: (1) an internal context is detected — internal workspace
host (e.g. `e2-demo-field-eng`), Isaac-managed identity, or presence of the internal MCP tools /
entitlements — and (2) the user/deployment is authorized (employee). Detection reuses the auth resolver
(A1), which already resolves host + identity. Default is **closed** (public path).

**The gate IS the governance boundary.** Internal data flows *only* through the gated internal adapter
at runtime; shipped public artifacts (code, prompts, packs, reference files) never contain internal
namespaces (§7 red-lines still hold, unchanged, for everything on the public side). This makes §7 an
enforced property of the architecture rather than a review checklist.

**Sequencing.** Land the **port interfaces with public adapters** in Phase 2 (part of C5); attach the
**internal adapters** in Phase 3 (D6/D7) once the ports exist. The public product is complete without
them; internal enrichment is pure upside.

## 4. High-level implementation plan (phased, dependency-ordered)

Each phase is independently shippable and de-risks the next. LOE is rough for one engineer; phases overlap where noted.

### Phase 0 — Foundations (quick, high-confidence) — *weeks*

**Goal:** the shared substrate everything else builds on; visible data value immediately.

**→ Detailed, execution-ready plan:** [`impl/PHASE_0.md`](./impl/PHASE_0.md) — file targets, TDD tests, acceptance criteria, PR strategy.

- A1 auth resolver · A2 skill de-dup + frontmatter · A3 zero-store default · A4 CLI hardening ·
A5 four quick-win packs · C4 retire dormant memory.
- **Exit criteria:** default `pip install starboard` pulls no redis/postgres/pgvector/sqlite-vec;
one canonical skill tree; PAT-optional auth resolves across profile/env/ambient; 4 new packs live.
- **Mostly S; A1 is S–M.** No new architecture — packaging + defaults + content.

### Phase 1 — Packaging, tiers & no-server distribution — *weeks* (needs Phase 0)

**Goal:** ship the frictionless, server-free product to both audiences; prove the middle tier.

- B1 kernel carve-out · B2 `starboard-x` with the diagnostic **0-dep trio** + chart-renderer ·
B3 skills-only plugin + marketplace · B4 `databricks aitools` · D3 shared Finding schema +
D2 LogFood framings (seed content).
- **Enabling smoke test (gate):** confirm Isaac-injected Databricks auth reaches the CLI's SDK
chain (`isaac --claude` + `starboard-helper`) — gates the "just works" no-MCP UX.
- **Exit criteria:** `pip install "starboard-x[diagnostics]"` (no heavy deps) + a skill that shells
to it with no permission prompt; plugin installs in Claude Code and Isaac; resident context bounded.

### Phase 2 — Native architecture + capability depth — *weeks–months* (parallelizable)

**Goal:** remove the last stores; deepen analysis. Two independent workstreams.

- *Workstream 2a (native):* C1 RAG → reference files [parallel, touches `infra/rag`] ·
C2 UC-native state adapter · C3 JSON CLI sessions.
- *Workstream 2b (depth):* D4 progressive-helper depth (discovery `data_only`, sparklog,
analyzers) · D5 new packs + discovery caching · B6 optional-MCP toggle ·
**C5 port interfaces + public adapters** (LogRetrieval/DiagnosticBackend/FleetSql/NLQuery + the
employee-context detection hook on the auth resolver — internal adapters land in Phase 3).
- **Exit criteria:** durable server state with no external DB; analytics agent runs on reference
files (embeddings behind `[vectorsearch]` only); discovery/RCA available as dep-ful helpers;
capabilities expressed as ports with working public adapters + a closed-by-default gate.

### Phase 3 — Flagship & strategic — *months* (needs Phases 0–2 content)

**Goal:** the differentiators.

- D1 **Workload Review** engine (consumes Phase-1 finding schema + seed rules as its first rule sets) ·
**attach the gated internal adapters (C5)**: D6 dbr-doctor/logs-summariser backends + D7 fleet mode
(each enriches its public adapter, additively) · D8 Genie · D9 Codex/OpenCode ·
B5 full marketplace + per-domain plugins · D10 Apps OBO.

## 5. Critical path & dependencies

```
A1 auth ─────────────┬─► C2 UC-native state ─► (durable zero-store server)
                     ├─► D7 fleet mode
                     └─► D10 OBO
A2 skills ───────────┬─► B3 plugin ─► B4 aitools ─► (reach: Claude Code + Isaac + customers)
                     └─► B2 starboard-x skills
B1 kernel ─► B2 starboard-x ─► D4 progressive-helper depth
A3 zero-store ─(parallel)─► C1 RAG→files ─► (analytics needs no vector DB)
D3 finding schema + D2 LogFood ─► D1 Workload Review (flagship)
A5 quick packs ─(independent, ship anytime)
```

**Longest pole:** A1/A2 → B-pillar → D1 Workload Review. **Fast independent value:** A5 packs, A3 zero-store, D2 LogFood framings.

## 6. Decision points to resolve before/at each phase


| When    | Decision                                                                                                  | Owner input needed |
| ------- | --------------------------------------------------------------------------------------------------------- | ------------------ |
| Phase 0 | Canonical skill dir + `SKILL.md` frontmatter schema (verified in topic 1)                                 | confirm            |
| Phase 1 | Does Isaac inject Databricks auth onto the SDK chain? (smoke test) — gates no-MCP UX                      | test result        |
| Phase 1 | Isaac plugin onboarding + review gates (go/llmpolicy) for shipping a plugin/CLI internally                | internal process   |
| Phase 2 | Can `starboard-kernel` avoid `databricks-sdk` entirely? (import audit)                                    | audit              |
| Phase 2 | RAG fidelity: do reference files match embedding retrieval for SQL accuracy? Escape hatch = Vector Search | validate           |
| Phase 2 | UC-table state latency/concurrency — where is Lakebase/Postgres genuinely required?                       | validate           |
| Phase 3 | Workload Review feedback loop (Action-Rate has no PR/merge gate — synthesize via re-scan)                 | design             |
| Phase 3 | Which model ids are available for the validator/ensemble council in a customer deployment                 | confirm            |


## 7. Governance — the gate enforces it (from topic 6, reframed by C5)

The rules below bind the **public path and all shipped artifacts**. Internal data/namespaces are *not*
forbidden outright — they are allowed **at runtime, only through the gated internal adapter (C5), only
for authorized employees**. The gate makes governance an architectural property, not a review checklist.

- **Public artifacts stay clean.** No internal namespaces (`eng_`*, `centralized_system_tables`,
`fin_live_gold`, `gtm_*`, logfood workspace, ClickHouse) in shipped code/prompts/packs/reference
files — **grep artifacts before release**. Internal identifiers live only inside the internal-adapter
code path, never in the default wheel's public content.
- **$ labeling depends on the path:** the public adapter emits **list-price estimates**; finance-grade
$ appears **only** when the LogFood internal adapter is active (gate open).
- **Fleet/cross-account** is an **internal-adapter capability** (gate open), never in the public path.
`hmr_stack_hash` stays internal; the public analog is fresh log4j-stack fingerprinting.
- **Paraphrase** harvested prompts (the *pattern* is the asset, not the string); strip internal `go/`
links + team keys from any content that ships in the public path.
- **Gate invariant (from §3.5):** closing the gate must always leave a fully-functional public
capability — internal enrichment is additive, never load-bearing for the public product.

## 8. What we are deliberately NOT doing (scope guards)

- Not rewriting the analyzers — Round 2 confirmed "the weight is in the wheel, not the code."
- Not deleting the MCP server or the heavy backends — they become **opt-in** (Tier 2 / extras), not removed.
- Not exploding into N repos — one uv monorepo, many thin distributables.
- Not putting fleet/cross-account or finance-grade data in the **public path** — but these *are*
available to employees via the gated internal adapter (C5). Internal enablement is additive, never a
reduction of the public capability, and never required for the public product to work.

## 9. Suggested first slice (smallest thing that proves the direction)

**Phase 0 A3 (zero-store default) + Phase 1 B2 diagnostic 0-dep trio as `starboard-x` + one skill.**
Small, verifiable, no external deps, no server — and it exercises the whole native/progressive spine
end to end. Pair with A5 (quick-win packs) for immediate, independent customer-visible value.