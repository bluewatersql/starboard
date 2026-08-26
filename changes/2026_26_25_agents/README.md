# Starboard — "Art of the Possible" Envisioning Study

**Date:** 2026-08-26
**Type:** Research / brainstorming / envisioning / documentation (no code changes)
**Baseline:** starboard 0.1.1 @ commit `b927dfaa`

## ⭐ Start here for review

**[`UNIFIED_PLAN.md`](./UNIFIED_PLAN.md)** — all 7 topics coalesced into one prioritized
recommendation set (4 pillars) + a phased, dependency-ordered implementation plan, critical path,
decision points, and governance gate. The per-topic folders below hold the supporting evidence.

## Purpose

Envision — from **first principles**, unconstrained by the current implementation — how Starboard
should integrate into existing agent ecosystems, simplify Databricks auth, expand and reuse its
capabilities, and unbundle into individually consumable parts. All claims are **evidence-based**
(repo `file:line` + current official docs).

## Ground Rules

- Do **not** anchor to current architecture/limitations — reason from first principles.
- Every claim cites evidence: repo `file:line` or a verified current doc URL.
- Verify against the **most current** version of all APIs/docs (SDKs and agent platforms move fast).

## Shared Evidence Base

- [`_grounding_brief.md`](./_grounding_brief.md) — factual baseline about the current codebase
  (packages, architecture, MCP server, skills, auth, data sources, tools) shared by all streams.
- [`_grounding_brief_round2.md`](./_grounding_brief_round2.md) — Round-2 addendum: external-store
  usage, RAG/memory, dep-ful helper candidates, internal-tool IP to harvest.

## Topics & Deliverables

Each topic folder contains: `opportunities.md` (options + strengths/weaknesses/trade-offs/complexity/LOE),
`recommendation.md` (ranked recommendations), `technical.md` (proposed architecture/design), and
optionally `open_questions.md`.

### Round 1 — original four topics

| # | Topic | Folder | Scope |
|---|-------|--------|-------|
| 1 | **Agent-host integration** | [`agent_integration/`](./agent_integration/) | Claude Code / Codex / OpenCode / Isaac / Genie — **without** requiring an MCP server |
| 2 | **Databricks auth simplification** | [`databricks_auth/`](./databricks_auth/) | Workspace switching, interactive, token — across external/internal/Genie contexts |
| 3 | **Starboard optimization & reuse** | [`starboard_optimization/`](./starboard_optimization/) | Reuse, new data sources/endpoints, internal-skill integration, match/gap map |
| 4 | **Decomposition into consumable parts** | [`starboard_decomposition/`](./starboard_decomposition/) | Unbundle into agents/skills/plugins/libs/MCP tools |

### Round 2 — feedback-driven deep dives (2026-08-26)

Feedback pushed the study further on four sharper directions:

| # | Topic | Folder | Scope |
|---|-------|--------|-------|
| 5 | **Dep-ful progressive helpers** | [`progressive_helpers/`](./progressive_helpers/) | Repackage heavy capabilities as helper scripts (may install starboard deps) surfaced via progressive disclosure — a *middle tier* between the thin no-dep CLI and the heavy MCP server |
| 6 | **Harvest internal-tool IP** | [`internal_harvest/`](./internal_harvest/) | Harvest patterns/heuristics/prompts/context/methodology from dbr-doctor, LogFood, logs-summariser, Isaac `/review`, + others → apply to **public/customer-facing** data |
| 7 | **Native, store-free architecture** | [`native_simplification/`](./native_simplification/) | Remove external stores (sqlite/postgres/redis/pgvector/RAG DB); use agent-host-native memory/context + Databricks-native (UC) durable state |

## Status

| Topic | State | Deliverables |
|-------|-------|-------------|
| 1 — Agent integration | ✅ complete | opportunities, recommendation, technical, open_questions |
| 2 — Databricks auth | ✅ complete | opportunities, recommendation, technical, open_questions |
| 3 — Optimization & reuse | ✅ complete | opportunities, recommendation, technical, open_questions |
| 4 — Decomposition | ✅ complete | opportunities, recommendation, technical, open_questions |
| 5 — Progressive helpers | ✅ complete | opportunities, recommendation, technical, open_questions |
| 6 — Internal-tool harvest | ✅ complete | opportunities, recommendation, technical, open_questions |
| 7 — Native / store-free | ✅ complete | opportunities, recommendation, technical, open_questions |

> Round-2 cross-cutting synthesis is at the end of this file (§ Round 2 Synthesis).

All claims are cited to repo `file:line` or verified current docs. Confidence tags used where a
fact could not be fully verified (notably Isaac internals, sourced via Confluence/Glean).

## The single most important discovery

> **Isaac — Databricks' internal coding agent — is a CLI wrapper/router over Claude Code, Codex,
> OpenCode, and Cursor, and it has a plugin marketplace** (`isaac plugin add PLUGIN@MARKETPLACE`).
> So **one skills-only Claude Code plugin reaches every internal engineer with no MCP server**, and
> `databricks aitools install` reaches external customers. Combined with the fact that Starboard's
> **dual-mode skills + `starboard-helper` CLI already exist**, the no-MCP integration story is one
> packaging step away. _(Topic 1, [C] Confluence 2026-08-18)_

## Cross-Cutting Themes (four-topic reconciliation)

- **Auth is the keystone (Topic 2), and it's a subtraction.** The unified
  `resolve_workspace_client()` / `WorkspaceTarget` resolver — *stop forcing host+token, delegate to
  the SDK's credential chain (verified from `databricks-sdk 0.73.0` in `.venv`), make "target a
  workspace" a single `--profile` flag* — is the prerequisite the other three topics lean on:
  - the no-MCP CLI/skill path (Topic 1) needs frictionless per-workspace auth (open question I5:
    does Isaac inject Databricks OAuth onto the SDK chain the helper reads?);
  - new data-source reach (Topic 3) rides the same client for Genie/fleet/internal SSO;
  - the decomposed `starboard-databricks` I/O tier (Topic 4) is exactly where this resolver lives.
  Two subsystems (`skills helper`, `state/uc stores`) already use the bare-chain `WorkspaceClient()`
  correctly — the fix is making the rest consistent.

- **Topic 1 resolves Topic 4's packaging open-questions.** Topic 4 flagged uncertainty about exact
  `plugin.json` keys, fenced-YAML `SKILL.md` frontmatter (`allowed-tools`), and `marketplace.json`
  shape. **Topic 1 verified all of these against current Claude Code docs** (`technical.md §1`) —
  they now form one agreed packaging spec. Integration and decomposition are the same coin: Topic 4
  says *what* to unbundle; Topic 1 says *which host format* each unit ships in.

- **Three independent streams flagged the same #1 quick win — skill duplication + invalid
  frontmatter.** `skills/starboard/*/SKILL.md` (bare `name:` line, **no `---` fence** → may not
  parse) vs `packages/starboard-skills/skills/starboard/*/skill.md` (no frontmatter at all). Topics
  1, 3, and 4 all independently call this out as highest-ROI / lowest-risk. It unblocks the plugin
  (Topic 1), the canonical `skills/` tree (Topic 4), and removes drift (Topic 3 S1).

- **`starboard-helper` CLI is the universal substrate.** Topic 1 makes it the no-MCP path for all
  four hosts; Topic 4 folds it into an umbrella `starboard-cli`; Topic 3 wants it hardened (add
  `analyze`/`discovery`/`genie` verbs, stable JSON contract). One investment, many consumers.

- **Reuse ↔ Decomposition ↔ new capability align.** Topic 4's extraction candidates (spark-log
  parser, chart-renderer, discovery-query-packs, diagnostic primitives) are exactly Topic 3's reuse
  assets. Topic 3 extends the catalog with (a) nearly-free new system-table packs and (b) port-based
  reuse of internal tools (dbr-doctor, logs-summariser, LogFood, centralized-tables for fleet mode).

## Consolidated Recommendations (cross-topic priority)

### Phase 0 — Foundations that everything else needs (start now, all quick)
1. **Auth by subtraction (Topic 2, R1):** one `resolve_workspace_client()` helper; pass only set
   fields to SDK `Config`; drop forced-token validation; PAT stays as one strategy. **(S–M)**
2. **Collapse skill duplication + add fenced frontmatter (Topics 1/3/4 consensus):** one canonical
   `SKILL.md` tree, vendored (not copied) into wheel + plugin. **(S)**
3. **Harden `starboard-helper` CLI (Topics 1/3):** stable JSON contract, add `analyze`/`discovery`/
   `genie` verbs so 9 skills map 1:1 to CLI verbs. **(S–M)**

### Phase 1 — Ship the no-MCP integration + instant data wins
4. **Skills-only Claude Code plugin + `marketplace.json` (Topic 1, O1/O2):** reaches Claude Code
   **and** all Isaac users; smoke-test `isaac --claude` to confirm auth flows (I5). **(M / S)**
5. **Fix the 4 mapped-but-unimplemented query packs (Topic 3, N1–N3/N10 + S6):** Predictive
   Optimization, Data Quality Monitoring, Data Classification, Networking already route to a
   pack that never queries its system table — the cheapest, highest-confidence new-data wins. **(S)**
6. **Workspace targeting `--profile`/`STARBOARD_WORKSPACE` + `starboard auth login` (Topic 2, R2/R3):**
   one-flag workspace switch; browser SSO incl. internal Okta. **(M)**

### Phase 2 — Depth, structure, and reach
7. **Optional-MCP toggle in the same plugin (Topic 1, O3)** — raise the depth ceiling to the 7-agent
   stack without a second artifact. **(M)**
8. **Carve `starboard-kernel` + ship standalone `starboard-sparklog` & `starboard-charts` (Topic 4)** —
   dependency-light nucleus + two genuinely reusable products. **(M / L / S)**
9. **Discovery result caching (Topic 3, R4/S4)** — `system.billing.usage` is scanned 69×; cache hot
   scans for real warehouse-cost/latency wins. **(M)**
10. **Compute reliability + right-sizing pack (Topic 3, N5)** — instance_events/pools/node_types. **(M)**

### Phase 3 — Strategic bets (mostly internal-deployment)
11. **Port-based internal-tool reuse (Topic 3, I1–I4):** `DiagnosticBackendPort`→dbr-doctor,
    `LogRetrievalPort`→logs-summariser, LogFood telemetry packs, and a namespace-rewrite adapter →
    **fleet/multi-account mode** via centralized system tables (near-zero pack edits). **(M–L)**
12. **Genie integration (Topics 1/3):** consume via `genie ask` (NL→SQL source) first; later expose a
    curated Genie space. **(M / L)**
13. **Codex + OpenCode host coverage (Topic 1, O5/O6)** and **full decomposition marketplace with
    per-domain plugins (Topic 4)**. **(S–M / L)**
14. **Apps On-Behalf-Of-User auth (Topic 2, R6, deferred)** — per-user UC/Genie grants for
    multi-tenant App hosting. **(L)**

## Top open questions to resolve before building

- **I5 / XC1 (auth parity):** does Isaac inject Databricks OAuth such that bare `WorkspaceClient()`
  "just works", or is `databricks auth login` still required? Gates the no-MCP "just works" UX.
- **Isaac plugin format & onboarding (I1–I4):** byte-identical to Anthropic's plugin format? review
  gates (go/llmpolicy) for shipping a CLI/MCP internally?
- **Kernel dependency audit (Topic 4, Q6):** which analyzers truly need `databricks-sdk` types vs
  plain DTOs — determines whether a zero-SDK kernel is achievable.
- **Genie `serialized_space` schema (G3)** and **Preview/Beta system-table availability** (many
  gap tables are Preview — gate packs with `required=False` and degrade gracefully).
- **Internal-integration trust boundaries (Topic 3):** fleet mode crosses accounts; needs governance
  review. Internal backends must sit behind adapters so OSS builds keep working.

---

# Round 2 Synthesis (topics 5–7)

The three Round-2 streams converge on one coherent architecture: **native, file-based, server-free,
store-free** — depth delivered through progressive disclosure and bundled content, not a running
server or an external database.

## The unifying thesis: "ship the contents, as files, loaded on demand"

All three asks land the same way — as **bundled files the agent reads only when needed**:

- **Progressive helpers (5):** analytical capabilities as `python -m starboard_x.*` scripts a
  SKILL.md shells out to — code **executed, not loaded** into context.
- **Native/store-free (7):** the RAG vector DB replaced by **progressive-disclosure reference
  files + the existing query packs**; state moved to in-memory + Databricks-native UC tables.
- **Harvested IP (6):** internal methodology encoded as **YAML rule registries, versioned prompts,
  query packs, and reference files** — consulted from the internal tools *once at authoring time*,
  never at customer runtime.

Net: a default Starboard install needs **no external store and no long-lived server**, yet retains
deep, deterministic analysis and expert-grade heuristics — because depth lives in bundled files and
one-shot subprocesses, and resident context stays at ~1.5 KB per skill until a question fires.

## The backbone: a 3-tier capability model (stream 5)

| Tier | Artifact | Deps | Role | Context cost |
|------|----------|------|------|--------------|
| **0 — no-dep helper** | `starboard-helper` CLI | databricks-sdk only | **fetch** raw telemetry → JSON | near-zero |
| **1 — dep-ful progressive helper** | `starboard-x` slim wheel + `python -m`, per-capability extras | pydantic/polars (+ extras) | **analyze** deterministically (RCA, fingerprints, heuristics, charts) | near-zero until skill fires |
| **2 — MCP server** | `starboard-mcp` | full ~40-dep wheel | **reason** (7 LLM agents, routing, memory) | persistent |

Round-1 skills already branch dual-mode (MCP vs CLI); this adds a **third branch**: *else if
`starboard-x` installed → dep-ful helper; else → thin `starboard-helper`.* Verified insight: **"the
weight is in the wheel, not the code"** — the analytical modules import almost nothing (exit-code
triager, evidence extractor, RCA synthesizer are **zero-dep**), so tier 1 is repackaging, not
rewriting, and *is* the Tier-1 layer of the Round-1 decomposition catalog.

## Where the three meet — RAG-to-native-context

Streams 6 and 7 intersect precisely at the RAG replacement: the analytics agent's fixed, curated
system-table knowledge corpus (a vector DB today) becomes **progressive-disclosure reference files**
— and stream 6's harvested reference knowledge (dbr-doctor's variable glossary, LogFood's
schema-selection guide, perf-tuning decision trees) is exactly the content that populates those
files. One mechanism, fed by both streams, removes `sqlite-vec` + embeddings + the `.npz` bootstrap.

## Flagship new capability: "Workload Review" (stream 6)

Harvest Isaac **`/review`**'s CI-grade methodology — rule registry, severity + min-severity gate,
**validator council (verify-pass)**, agent/model council, bad/good/suggested-fix finding schema,
targeting-filter grammar, and the **Action-Rate quality loop** — and re-implement it to **review a
workspace's jobs/queries/warehouses/UC the way `/review` reviews code**. It's built on Starboard's
existing pattern registry (`patterns/registry.py` + `schema.py`) and 7 domain agents, and seeded by
the public `databricks-elt-review` skill's `severity × impact / effort` scorer + per-domain
checklists, plus LogFood's metric framings. This is the strongest differentiator surfaced anywhere
in the study.

## Consolidated Round-2 recommendations

**Quick wins (days–weeks, high fidelity, low risk):**
1. **Zero-store default (7, ranks 1–2):** flip cache/rate-limit to in-memory; move
   `redis`/`asyncpg`/`pgvector`/`aiosqlite`/`sqlite-vec` from unconditional deps to extras
   (`starboard[postgres|redis|memory|sqlite|vectorsearch]`). Closes Ask C for the default install —
   packaging only, Protocol preserved.
2. **Diagnostic 0-dep trio as the first progressive helper (5, rank 1):** `starboard-x.diagnostic`
   (exit-code triager + evidence extractor + RCA synthesizer) + one skill — proves the
   SKILL.md→`python -m`→JSON loop with the lightest install.
3. **LogFood metric framings → warehouse/finops/compute packs (6, #1):** utilization bands,
   auto-stop waste, query-load buckets, client-app mix, T7/T28/T91 windows — content into existing
   packs; `centralized_system_tables.*` mirrors public `system.*` so it ports near-losslessly.
4. **elt-review scorer + checklists → shared Finding schema + seed rules (6, #2)** — de-risks the
   Workload Review engine by giving it content before the engine exists.

**Strategic bets (weeks–months, differentiating):**
5. **Workload Review engine (6, #3)** — rule registry + severity gate + validator council + report,
   consuming the Phase-1 content as its first rule sets.
6. **RAG → reference files (7, rank 3)** — the marquee simplification; author per-domain reference
   files from the bootstrap corpus + query packs + harvested knowledge; rewrite
   `build_analytics_context` to domain-keyed file lookup; embeddings become `[vectorsearch]`-only.
7. **Native UC-table state adapter (7, rank 4)** — wire the **orphaned, ~80%-built `UCStorageAdapter`
   / `UCRepository`** as Protocol-compliant state/memory/user/feedback stores; durable state with no
   external DB and no new credentials (reuses the auth resolver's `WorkspaceClient`).
8. **Progressive helper depth pack + discovery `data_only` + sparklog (5, ranks 2–6)** and
   **log-triage (6, #4)** / **dbr-doctor evidence-tags + query-diff (6, #5)**.

## Verified corrections & governance (must-reads before building)

- **Correction (7):** the `database_backend="databricks"` path is **not** UC-native today — it
  extends `PostgresStateStore` over `asyncpg` to **Lakebase** (managed Postgres). The genuinely
  UC-native layer is the **orphaned `infra/storage/uc_adapter.py` + `repository.py`** (zero
  consumers) — that's the piece to promote for "Databricks-native state."
- **Governance red-lines for harvest (6) — non-negotiable before shipping externally:**
  - Never reference internal namespaces (`eng_*`, `centralized_system_tables`, `fin_live_gold`,
    `gtm_*`, the logfood workspace, ClickHouse) in shipped code/prompts/packs — **grep artifacts
    before release**. Ship only public `system.*` / customer log delivery / public REST.
  - Label all `$` as **list-price estimates**, never "finance-grade" (public `system.billing` is
    list-price × usage, not contract net-of-discount).
  - **Paraphrase** harvested prompts; the *pattern* is the asset, not the literal string.
  - Customer-facing capability is **single-workspace**, never fleet/cross-account.
  - `hmr_stack_hash` is internal-only; the public analog is log4j-stack fingerprinting built fresh.

## Round-2 open questions

- **UC-table state** latency/concurrency (Delta via `statement_execution` is seconds-latency,
  low-concurrency) — fit for low-write durable data; when is Lakebase/Postgres genuinely required?
- **RAG fidelity:** does deterministic per-domain file lookup match embedding retrieval for SQL
  accuracy on the (static, small) corpus? Escape hatch: Databricks Vector Search.
- **Workload Review feedback loop:** Action-Rate needs a synthesized signal (did the customer apply
  the fix? re-scan next run) since there's no PR/merge gate; validator council adds model cost.
- **Model council availability (6, [U]):** which model ids are available to a customer-facing
  deployment for the validator/ensemble pattern.
- **`tools/domain/diagnostic/__init__.py` eager imports** (5): trim for clean per-capability helper
  installs.
