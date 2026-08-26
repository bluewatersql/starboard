# Dep-ful Progressive Helpers — Recommendation

> Ranked recommendation for **which capabilities to ship as dep-ful progressive-disclosure helpers
> first**, sequencing, what stays thin, and what must remain the server. Evidence in
> `opportunities.md`; layout/manifests in `technical.md`.

---

## 1. Headline

Build **`starboard-x`**, a slim distributable that re-exposes existing analytical capabilities as
`python -m starboard_x.<domain>` modules with **per-capability extras**, and surface each through an
**Agent-Skills SKILL.md that shells out** to it. This is the missing **middle tier**: it delivers
the *real* Starboard analyzers (deterministic RCA, discovery heuristics, fingerprints, charts)
without a long-lived server and at **near-zero resident context cost** — only ~1.5KB of skill
description sits in context until a matching question fires (verified: docs cap description at 1,536
chars).

Because the analytical code imports almost no heavy deps (opportunities §1), this is **repackaging,
not rewriting**. It also *is* the Tier-1 layer of the decomposition catalog
(`starboard_decomposition/recommendation.md:83-108`) — build it once, consume it via skills.

**Why the middle tier at all** (vs the two poles):
- vs **Tier 0** `starboard-helper`: fetch-only JSON can't fingerprint a warehouse, triage an exit
  code, score discovery findings, or render a chart. Depth requires deps.
- vs **Tier 2** MCP server: the server pulls ~40 deps (`starboard/pyproject.toml:8-82`), holds tool
  schemas in context permanently, and needs a lifecycle. Most single-domain analysis needs none of that.

---

## 2. Ship order (value ÷ weight × independence)

Each step is independently shippable and proves the pattern before the next.

| Rank | Ship | Caps | Deps installed | Why now | LOE |
|---|---|---|---|---|---|
| **1** | **Diagnostic 0-dep trio** as `starboard-x.diagnostic` + one `starboard-diagnostic` skill | C1, C2, C6 | none (stdlib+structlog+pydantic) | Proves the whole SKILL.md→`python -m`→JSON loop with the lightest possible install; highest value/weight | **S** |
| **2** | **Diagnostic depth pack**: profile/skew/pattern + end-to-end `rca` verb | C3, C4, C5, C7 | +pyyaml | Turns the trio into a real local RCA pipeline; C5 ships 8 curated YAML rule packs as data | **M** |
| **3** | **chart-renderer** as `starboard-x.charts` (own `[charts]` extra) | C16 | +altair, vl-convert-python | Instant visual payoff; zero Databricks coupling; validates the extras-gating pattern for a heavy binary dep | **S** |
| **4** | **warehouse + uc pure analyzers** | C10, C13 | +polars | Light pure analyzers; establish the "pure analyzer helper, then add I/O verb later" pattern | **S–M** |
| **5** | **discovery `data_only`** as `starboard-x.discovery` | C8 | +polars, databricks-sql-connector, databricks-sdk | The flagship: 17 system-table packs + heuristics, deterministic, no LLM; broadest coverage | **L** |
| **6** | **spark-log-parser** as `starboard-x.sparklog` (cloud loaders behind `[aws]`/`[azure]`/`[gcp]`) | C9 | +polars, numpy, stream-unzip (+cloud extras) | Highest external reuse; self-contained hexagon; heaviest pure unit so gate loaders | **L** |
| **7** | **I/O services**: warehouse-portfolio (chargeback), query-workload, uc lineage/storage/governance, cluster | C11, C12, C14, C15 | +databricks-sql-connector, sdk, sqlglot | Genuine killer features (chargeback, lineage) but drag SDK+auth; ship after the pure tier and after the auth decision (`databricks_auth/`) lands | **L** |

**Phase 1 = ranks 1–4** (a quarter): light installs, no server, proves the tier with diagnostics +
charts + pure analyzers. **Phase 2 = ranks 5–7**: the heavier data-backed helpers.

---

## 3. What stays thin (Tier 0 — do NOT promote)

Keep these on the zero-dep `starboard-helper` (`packages/starboard-skills/`). They are pure SDK
passthrough with no analytical depth, so deps would buy nothing:

- `job list` / `run-state`, `warehouse list`, `cluster list` / `node-types` / `spark-versions`,
  `uc catalogs`, `query slow` (raw history) — see `starboard_skills/helpers/*.py`.

A skill should call Tier 0 to *fetch*, then Tier 1 to *analyze* the fetched JSON — e.g.
`starboard-helper warehouse history …` → `starboard_x.warehouse analyze --history -`.

---

## 4. What must stay the server (Tier 2 — cannot be a helper)

These need an LLM, a persistent tool registry, and a lifecycle no one-shot `python -m` can offer:

- **7 LLM domain agents** + `*_agent` tools (`mcp/agent_bridge.py:48-93`).
- **IntentRouter + `MultiAgentConversationManager`** cross-domain routing/handoff (`agents/conversation/`).
- **RAG-backed Analytics SQL generation** (`infra/rag/`) — though the decomposition/native-store work
  (Round-2 asks C/D) may replace the vector DB with progressive-disclosure reference files, which
  would let even this move down a tier later.
- Any **multi-turn / long-running** flow needing progress notifications, conversation memory, or
  durable state.

The skill's existing **dual-mode branch** already expresses this: *if `mcp__starboard__*` tools are
present, use the server; else shell out.* The middle tier slots in as a **third branch**: *else if
`starboard-x` is installed, run the dep-ful helper; else fall back to `starboard-helper`.*

---

## 5. Packaging principle (see technical.md §3 for the pyproject)

- **`pip install starboard-x`** = base only (pydantic + the 0-dep diagnostics). Nothing heavy.
- **`pip install "starboard-x[diagnostics]"`** adds pyyaml; `[charts]` adds altair+vl-convert;
  `[discovery]`/`[warehouse]`/`[uc]` add polars+databricks-sql-connector; `[sparklog]` adds
  polars+numpy+stream-unzip, with cloud loaders behind `[sparklog-aws]` etc.
- A skill's install note pins **only the extra it needs** — so a diagnostics user never installs
  altair, and a chart user never installs a SQL connector. This is what makes the middle tier
  *lighter than the server* while still deep.

---

## 6. Success criteria

1. `pip install "starboard-x[diagnostics]"` pulls **no** fastapi/redis/postgres/mcp — verifiable
   against `starboard/pyproject.toml:8-82` (the mega-list) being absent.
2. `python -m starboard_x.diagnostic triage-exit --exit-code 137` returns ranked hypotheses as JSON,
   standalone, and the `starboard-diagnostic` skill invokes it **without a permission prompt** via
   `allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/run.sh *)`.
3. Resident context for an idle session with all 8 skills installed is bounded by 8 × ≤1.5KB
   descriptions — no tool schemas, no analyzer source.
4. One capability implementation backs all three surfaces: Tier-0 fetch feeds it, the Tier-1 skill
   shells to it, and (unchanged) the Tier-2 server still imports the same module.
