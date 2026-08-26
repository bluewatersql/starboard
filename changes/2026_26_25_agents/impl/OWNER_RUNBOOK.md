# Owner Runbook — Human-Touch Gates

> The Starboard program (Phases 0–1 shipped; Phase 2 planned) is blocked in a few places on
> decisions/actions that only a human owner can take — external verification, internal onboarding,
> a live workspace, or a product call. Each gate below is self-contained: what it blocks, who owns
> it, the exact steps, how to verify, and **where to record the answer** so the automated work can
> resume. Nothing here requires reading code.
>
> Baseline: Phases 0–1 on `main`. Cross-refs point at `changes/2026_26_25_agents/`.

## Priority summary

| # | Gate | Blocks | Owner (role) | Effort | Priority |
|---|------|--------|--------------|--------|----------|
| G1 | Isaac-auth smoke test | The entire no-MCP "just works" UX (both audiences) | Any FE eng w/ Isaac | ~15 min | **Do first** |
| G2 | Preview-table pack validation | Relying on 4 A5 packs + D2 warehouse framings | Eng w/ a real workspace | ~1–2 h | High |
| G3 | Isaac plugin onboarding / `go/llmpolicy` | Internal distribution of the plugin | Eng-tools owner | days (review) | High |
| G4 | `databricks aitools` format confirmation | External-customer distribution path | `databricks aitools` owner | ~30 min ask | Medium |
| G5 | Model-council availability | Phase-3 Workload Review validator/ensemble | AI-platform owner | ~30 min ask | Phase 3 |
| G6 | Genie authorization prerequisites | Genie consume/expose (Phase 3) | Workspace admin | ~30 min | Phase 3 |
| G7 | Docs-location decision (`changes/` scratch) | Long-term repo hygiene | Repo owner | 5 min | Low |

---

## G1 — Isaac-auth smoke test  *(do this first — cheapest, de-risks the whole thesis)*

**What it blocks.** The core Phase-1 promise is that a skills-only install "just works" with no MCP
server and no manual credentials, because Isaac (and the Databricks SDK's unified auth chain) supply
Databricks auth ambiently. If Isaac does **not** inject auth onto the SDK chain that `starboard-helper`
/ `starboard-x` read, users must run `databricks auth login` first — a materially different UX we'd
document loudly. This is unverified (`agent_integration/open_questions.md` I5; `databricks_auth`).

**Prerequisites.** A machine with Isaac installed and Databricks access (VPN + Okta for internal FE
workspaces per `databricks_auth/opportunities.md`); `pip install "starboard-x[diagnostics]"` and the
`starboard-skills` package (for `starboard-helper`).

**Steps.**
1. In a shell with **no** `DATABRICKS_TOKEN`/`DATABRICKS_HOST` exported, launch `isaac --claude`.
2. Run a bare fetch through the helper: `starboard-helper job list --limit 5` (and `warehouse list`).
3. Run the dep-ful helper: `python -m starboard_x.diagnostic triage-exit --exit-code 137` (pure, needs no auth — sanity that the tier works) and then a helper verb that DOES hit Databricks.
4. Observe whether the Databricks calls authenticate with **no manual credential step**.

**Verify / interpret.**
- ✅ **Pass:** the helper returns real JSON (exit 0) with no auth prompt → Isaac auth reaches the SDK
  chain; the no-MCP "just works" claim holds.
- ⚠️ **Partial:** works only after `databricks auth login --host <ws>` once → document that one-time
  step as the setup; UX still good.
- ❌ **Fail (exit 1 auth):** Isaac auth is not on the SDK chain → we must ship an explicit
  `starboard auth login` (already planned as auth R3) and document it as required.

**Record the answer.** Add a short result note (pass/partial/fail + the command output) to
`changes/2026_26_25_agents/agent_integration/open_questions.md` under I5, and tell the assistant —
it gates whether the plugin README leads with "zero setup" or "one-time `auth login`".

**RESULT (2026-08-26, verified under `isaac --claude`): ⚠️ PARTIAL.** `starboard-helper` is installed
and works, but bare `WorkspaceClient()` finds **no default credentials** in the Isaac env
("Authentication error: default auth credentials") — **Isaac does NOT inject Databricks auth onto the
SDK default-credential chain** the helper reads. The resolver is correct; the chain simply has nothing
to resolve until the user sets up auth. Consequences (actioned):
- The no-MCP path is **"one-time `databricks auth login`"**, not zero-config. The plugin README + skills
  must document this setup step (do NOT claim "zero setup").
- **Pull forward the `starboard auth login` wrapper** (auth R3) so users get one guided command instead
  of raw `databricks auth login` + host.
- Internal FE workspaces (e.g. `e2-demo-field-eng`, Okta) → OAuth via `databricks auth login` is the
  right path (auto-refreshing); a `.databrickscfg` profile (`--profile` / `DATABRICKS_CONFIG_PROFILE`)
  also works. Both are honored by the resolver's precedence.

---

## G2 — Preview-table query-pack validation against a live workspace

**What it blocks.** Four Phase-0 packs (`predictive_optimization`, `data_quality`,
`data_classification`, `networking`) and the Phase-0/1 warehouse framings query **Preview** system
tables whose exact columns cannot be validated in CI (tests assert table names, not columns; no query
runs against a live schema). The Phase-0 review already caught and fixed three column bugs
(`phase0_review_findings.md` H1–H3); the packs are `required=False` so they degrade gracefully, but
they should be run against a real workspace before anyone relies on their output.

**Prerequisites.** Access to a workspace where these Preview system tables are enabled
(`system.storage.predictive_optimization_operations_history`,
`system.data_quality_monitoring.table_results`, `system.data_classification.results`,
`system.access.outbound_network`), plus `system.compute.warehouse_events`/`system.query.history` for
the warehouse framings. A running SQL warehouse.

**RESULT (2026-08-26, run against `e2-demo-field-eng`): ✅ PASS.** All four Preview-table packs
(predictive_optimization, data_quality, data_classification, networking) and the warehouse framings
(W-W01…W-W05, incl. the `system.query.history` `compute.warehouse_id`/`execution_duration_ms`/
`executed_by`/`client_application` columns) executed and returned data as expected — no
`UNRESOLVED_COLUMN`/`TABLE_NOT_FOUND`. Column-drift risk from the review (H1–H3) is closed for this
workspace. Follow-up still recommended: a CI schema-validation step (recorded column manifest or
`LIMIT 0` integration test) so future drift is caught automatically.

**Steps.**
1. For each pack, run its `sql_template` (fill `{lookback_days}`, e.g. 30) directly in the SQL editor
   or via `starboard-helper`.
2. Confirm every referenced column exists and the query returns sensible rows (or empty without error).
3. For `data_quality`, confirm the `status` domain values (`Healthy`/`Unhealthy`/`Unknown`) and that
   the `table_id`-keyed grouping is what you want (vs catalog/schema/table names, if those columns
   exist on your workspace).

**Verify / record.** For any column that errors (`UNRESOLVED_COLUMN`), note the correct name and
tell the assistant to patch the pack. Best long-term fix (recommended follow-up): add a CI
schema-validation step — a recorded column manifest per system table, or a `LIMIT 0`/`EXPLAIN`
integration test against a workspace — so column drift is caught automatically. Record findings in a
new `changes/2026_26_25_agents/reviews/preview_pack_validation.md`.

---

## G3 — Isaac plugin onboarding / `go/llmpolicy` review

**What it blocks.** Distributing the skills-only plugin to internal engineers via the Isaac/`vibe`
marketplace (`agent_integration/technical.md` §2; O2). The plugin manifest is built
(`plugin/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`) and is skills-only by
default (review fix #1).

**Prerequisites.** The plugin is self-contained (review fix #2 materialized `plugin/skills/` as real
files). Know your internal marketplace repo (e.g. FE `vibe` at `~/.vibe/marketplace/`) and its
onboarding process.

**Steps.**
1. Run the internal AI-tooling review (`go/llmpolicy`) for a plugin that ships skills + a helper CLI
   (and an opt-in MCP server template) — confirm data-handling is acceptable (the helper only reads
   the user's own workspace via their creds; no data leaves).
2. Onboard the plugin into the internal marketplace repo (snapshot/PR the plugin per that repo's
   convention); confirm install: `isaac plugin add starboard@<marketplace>` then
   `isaac -- plugin list | grep starboard`.
3. Smoke-test a skill end-to-end under Isaac (ties to G1).

**Record.** Note the marketplace name + install command in `plugin/README.md` and confirm to the
assistant; any review conditions become follow-up work items.

---

## G4 — `databricks aitools` format confirmation  *(external-customer distribution)*

**What it blocks.** The external-customer install path (B4). The exact `databricks aitools install`
command/manifest is **not publicly documented** — the questions are captured in
`docs/distribution/databricks-aitools.md` (decision D-1.6). The plugin is designed aitools-agnostic
(skills-only bundle, portable SKILL.md frontmatter), so adopting the confirmed format is a packaging
step, not a redesign.

**Steps.**
1. Ask the `databricks aitools` owner: (a) the exact install command + any manifest/config the
   installer consumes; (b) whether a third-party skills bundle can be distributed through it or only
   first-party; (c) required SKILL.md frontmatter conformance.
2. Read the "Confirmation needed — owner questions" section of `docs/distribution/databricks-aitools.md`
   and get each answered.

**Record.** Fill in the confirmed command/format in `docs/distribution/databricks-aitools.md`, mark
the UNCONFIRMED items resolved, and tell the assistant to wire any real manifest.

---

## G5 — Model-council availability  *(Phase 3 — Workload Review)*

**What it blocks.** The Phase-3 "Workload Review" flagship harvests Isaac `/review`'s
**validator-council + agent/model ensemble** (`internal_harvest/opportunities.md` Source 4). It needs
2+ model calls per finding.

**Steps / record.** Confirm with the AI-platform owner which model IDs are available to a
customer-facing Starboard deployment for the validator/ensemble (internal review uses
`system.ai.claude-*` ids that may not be externally available). Record in
`changes/2026_26_25_agents/internal_harvest/open_questions.md`. Not needed until Phase 3.

---

## G6 — Genie authorization prerequisites  *(Phase 3 — Genie integration)*

**What it blocks.** Consuming/exposing Genie (`agent_integration` O8/O9; `databricks_auth` technical
§5). Genie needs **authorization**, not new auth code.

**Steps / record.** Ensure the identity used has **CAN USE** on a Pro/Serverless SQL warehouse,
Databricks Assistant enabled, and **CAN RUN** on the target Genie space; for Apps On-Behalf-Of-User,
declare the **`genie`** scope in `app.yaml`. Confirm a curated Genie space exists (or plan one for
O9). Record in `databricks_auth/open_questions.md`. Phase 3.

---

## G7 — Docs-location decision  *(repo hygiene)*

**What it blocks.** Nothing functional. The whole envisioning study + plans live under `changes/`,
which is **gitignored scratch** — they were force-added to `main` to preserve them and to let worktree
agents read them. Decide: keep them force-tracked under `changes/`, or relocate under a tracked
`docs/` path (and update the internal links). Tell the assistant which; relocation is a mechanical
move + link fix.

---

## Sequencing recommendation

1. **G1 now** (15 min) — unblocks the no-MCP UX claim and the plugin README wording.
2. **G2** before anyone demos the four Preview packs or the warehouse framings.
3. **G3 + G4** in parallel when ready to distribute (internal + external).
4. **G5 + G6** are Phase-3 asks — line them up before starting the Workload Review / Genie work.
5. **G7** whenever convenient.

Once G1/G2 are answered, the assistant can proceed with Phase 2 implementation (see
`impl/PHASE_2.md`) without further human input until the distribution/Phase-3 gates.
