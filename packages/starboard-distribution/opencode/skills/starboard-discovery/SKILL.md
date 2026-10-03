---
name: starboard-discovery
description: Discover and map a Databricks workspace — enumerate jobs, clusters, warehouses, and Unity Catalog assets to build a comprehensive inventory. Use when the user wants a workspace inventory, a health assessment, or to explore what exists in a workspace.
compatibility: opencode
metadata:
  source: packages/starboard-skills/skills/starboard/starboard-discovery/SKILL.md
---

# Starboard: Workspace Discovery

> **Run checklist:** an engagement run must satisfy the `starboard-engagement` skill's
> `references/run-checklist.md` (`starboard-helper run check <run-dir>` enforces it).

Discover and map a Databricks workspace — enumerate jobs, clusters, warehouses,
and Unity Catalog assets to build a comprehensive inventory.

## You are the analyst

**You** are the LLM for this skill. The skill hands you deterministic workspace
data; **you** read the rows and write the inventory, observations, and
recommendations yourself.

Do **not** call the `starboard` goal agent, an MCP `*_analysis` / `synthesize_*`
tool, a model-serving endpoint, or any other model. There is no second LLM in
this loop — the data steps below run pure Python (no LLM), and you do the
reasoning. Handing analysis to another model defeats the point of the skill and
breaks when that model's credentials differ from your session's.

## Invocation

> **Overlay routing.** If an internal overlay skill is installed or loaded in this
> session, **follow that skill's discovery invocation instead of the commands
> below** — it supersedes this portable default for that context. A bare numeric
> workspace id or account id with no matching `--profile` entry usually means the
> overlay's no-connect path applies; load the overlay skill first before choosing
> a discovery path.
>
> **What an overlay replaces — and what it doesn't.** An overlay's discovery
> invocation replaces **only Steps 1–2** (confirm inputs, plan) and **the discovery
> command** (the `run --only --out-dir` call in Step 4). **Steps 4–6 are still
> REQUIRED:** write `discovery/domains/<domain>.md` from the overlay's envelope
> (Step 4 analysis: the discovery command never writes these files — you do, one per
> domain, from that domain's `data.domain_analyses` entry and its pack rows), `discovery/analysis.md` with the graded report card plus
> `README.md` (Step 5), and present the findings (Step 6).

> **Stay out of source.** To run an engagement use the skills and each command's
> `--help`; do **not** read `packages/` source. Column names and copy-paste SQL are in
> the engagement skill's `references/verify-sql.md` (or the overlay's own verify
> reference when an overlay applies). If a column isn't documented there, record the
> gap instead of grepping pack source.

The commands below use the **portable** engine invocation — it runs on any host
(Claude Code, Codex, OpenCode, `databricks aitools`):

```bash
python -m starboard_x.discovery <args>
```

## Step 1 — Confirm inputs

> **No-connect (bare workspace id) path:** skip Steps 1–2. The internal overlay's Beat 0 fixes the inputs (30-day lookback, no profile, `--internal-workspace-id`); there is nothing to confirm.

Before loading data, confirm the run parameters with the user — but **only ask
for what they haven't already given**. If their request already specifies a value
(e.g. "discover the workspace for the last 90 days"), use it and skip that
question. If they say "just go" / "use defaults", proceed with the defaults.

Ask for (with defaults):

- **Lookback window** — how many days of history to scan (default: **30**).
- **Workspace / profile** — which `--profile` to target, if it's ambiguous
  (default: the ambient `DATABRICKS_*` env / default profile).
- **Scope** — the available domains are determined in Step 2 (the plan step
  always runs regardless); proceed with all recommended domains by default. If
  the user expresses a focus (e.g. "just jobs"), note it and let them confirm or
  trim the list after seeing the plan — do not skip Step 2.

## Step 2 — Plan (which domains to run)

Run the plan command to see what the workspace is using and which domains are
worth running. This executes only the audit pack — cheap, one query:

```bash
python -m starboard_x.discovery plan --lookback-days N [--profile NAME]
```

Read the returned JSON:

- `data.products` — detected products with DBU weight (highest first)
- `data.recommended` — impact-ordered domains to run, each with its packs and
  DBU signal; always includes `billing` and `governance`
- `data.always_recommended` — domains worth running regardless of product mix
  (e.g. `billing`, `governance`)
- `data.contextual` — conditionally useful domains (e.g. `migration` when
  classic compute or classic warehouses are detected)
- `data.lookback_days` — confirmed lookback in use

Present an **impact-first menu** of the domains you plan to run, ordered by DBU
weight (highest first). Always-recommended domains (`billing`, `governance`)
appear regardless of weight. Include a contextual domain (e.g. `migration`) only
if `plan` flagged it under `contextual` or if the user asks for it.

**Proceed on "just go"** with all `recommended` domains (including
`always_recommended`). The user can trim the list or add a contextual domain
before you continue. A focused domain set is fine — you do not need every domain
for a useful report.

## Step 3 — Create the run directory

Create the engagement run directory **directly** (do not delegate to a subagent):

```
starboard-reports/<workspace>-<YYYY-MM-DD>/
  discovery/
```

Derive `<workspace>` from the workspace hostname (e.g. `e2-demo-field-eng`; use
`workspace` as the fallback). Use today's date for `<YYYY-MM-DD>`.

Save the plan envelope immediately to `discovery/plan.json` — this is your
provenance record of what was chosen and why. Use the `Write` tool (which creates
parent directories automatically):

```
Write → starboard-reports/<workspace>-<date>/discovery/plan.json
```

## Step 4 — Run each domain incrementally

For each selected domain, run exactly its packs with `--only` and stream results
to disk with `--out-dir`. Do **not** run all domains in a single call — the
per-domain loop keeps individual payloads small and lets you persist analysis as
you go.

```bash
python -m starboard_x.discovery run \
  --only <pack> [<pack2> ...] \
  --out-dir starboard-reports/<workspace>-<date>/discovery \
  --lookback-days N \
  [--profile NAME]
```

`--lookback-days N` must be the same lookback window confirmed in Step 1 — use
it consistently on every domain run so all results share the same time window.

`--only` runs exactly those packs: no audit phase, no always-run injection. Use
the domain→packs mapping from `data.recommended` in the plan envelope to know
which packs feed each domain (e.g. `vector_search` may map to both
`vector_search` and `serverless_attribution` packs).

After each domain run:

1. **Read the manifest** from stdout (`data.manifest[]` — queries, row counts,
   truncation status, paths to raw files).
2. **Read the raw pack files** named in the manifest:
   ```
   Read → starboard-reports/<workspace>-<date>/discovery/raw/<pack>.json
   ```
   A raw pack file is **one pack, flat**: `{"domain", "pack", "results": [ … ]}` (top-level
   `results[]`, no `data` key). The combined `discovery.json` envelope nests the same result
   objects at `data.packs[].results[]`; script against the shape of the file you opened.
   > **Large files / row-capped packs.** For feature-dense workspaces, a `raw/<pack>.json` can
   > be very large and one or more queries may have hit the row cap (`"limit_reached": true` in
   > the per-query envelope). When a pack is large or capped, prefer a compact
   > **summarize-then-reason** pass: use `jq` or Python to extract salient rows or aggregates
   > per query (e.g. counts, top-N by cost, group-by summaries) and load only that condensed
   > view rather than reading the whole file into context. `limit_reached: true` means the
   > workspace total **exceeds** what the row cap emitted — trust the manifest counts plus a
   > targeted aggregate, not a naive full read. (`truncated` is a separate signal meaning the
   > serializer dropped rows from an oversized stdout payload — different from a row cap.)
3. **Analyze the rows** — examine query results for that domain: counts,
   patterns, cost signals, failure modes, configuration anti-patterns.
4. **Write the domain analysis immediately** — do not hold all domains in
   context before writing. The discovery command does not write these files; this step does.
   **Where the write-up starts on `--data-only`:** `data.domain_analyses` holds one
   deterministic entry per domain with `kind: "data_only_summary"`: its `packs`, the
   succeeded / skipped / failed counts, `query_row_counts`, `nonempty_query_ids`,
   `limit_reached_ids`, and pointers to the rows (`data_paths` into the envelope, `raw_paths`
   = `raw/<pack>.json` under `--out-dir`). It has **no grade, findings or judgement**: use it
   as the checklist of which queries returned rows and which were capped or skipped, then
   write the analysis from the rows in `raw/<pack>.json`. (When the full LLM pipeline ran, the
   entries are graded analyses instead; start each file from that domain's entry.)
   ```
   Write → starboard-reports/<workspace>-<date>/discovery/domains/<domain>.md
   ```

Each `domains/<domain>.md` should follow the shape:

- **Summary** — one-paragraph domain overview and key findings
- **Observations** — notable patterns (e.g. job cluster attachment types,
  warehouse sizing gaps, governance coverage)
- **Findings** — specific issues with evidence (query name, row values) and
  remediation guidance
- **Recommended actions** — prioritized, actionable steps

`$` figures are **list-price DBU estimates** — label them as such.

> **W-W01 `utilization_ratio`.** Busy query-time ÷ wall-clock time. A value > 1 means queries
> overlapped (concurrency), **not** that the warehouse is saturated: 2.7 with 0.02% queued is a
> busy, healthy warehouse. Read saturation from `queued_query_pct` / `avg_capacity_wait_secs`.

> **Coverage caveat.** Skipped queries (audit, lineage, instance events, statement text where the
> source doesn't carry them) are acceptable and don't fail the run, but name them in
> `analysis.md` and the README; never write as if coverage were complete.

> **Window semantics.** Pack windows written `>= CURRENT_DATE - N` span **N+1 calendar days**
> including the partial current day. Label such figures "last N days (incl. today)", or re-query
> with `< CURRENT_DATE` when an exact N-full-day figure matters (e.g. a headline 30-day total).

> **Vector Search accuracy.** When analyzing the `vector_search` domain, lead with the
> **sprawl summary** (pack query P-VS06) and reconcile totals against
> `system.billing.usage` / `serverless_attribution` — do **not** lead with the row-capped
> per-endpoint list (P-VS01). The per-endpoint list can appear ~10× too small when rows are
> capped, which can invite a wrong "SKU-attribution artifact" conclusion. The real story
> is usually endpoint sprawl — many always-on endpoints sitting at the idle DBU floor —
> which shows clearly in billing aggregates even when the per-endpoint list is capped.

Persist each domain file before moving on. This keeps your working context
bounded regardless of how many domains you run.

## Step 5 — Unified rollup

After all domains are analyzed, write two summary files.

### `discovery/analysis.md` — unified rollup

```
Write → starboard-reports/<workspace>-<date>/discovery/analysis.md
```

Contents:
1. **Executive summary** — 3–5 sentences on the workspace's overall health, cost
   posture, and top concerns.
2. **Domain report card** — a table: Domain · Grade (A–F or Good/Fair/Poor) ·
   Headline finding.
3. **Top priorities** — ranked list (1–5+) of the highest-value actions across
   all domains, with domain, evidence citation, and list-price DBU impact where
   known.

### `README.md` — start-here index

```
Write → starboard-reports/<workspace>-<date>/README.md
```

Contents:
- Workspace name, date, lookback window
- Headline numbers (total jobs, warehouses, DBU spend detected)
- "Start here" pointer: `discovery/analysis.md` for the executive view
- Domain index: list of `discovery/domains/<domain>.md` files with one-line
  summaries

## Step 6 — Present findings

Present key findings on-screen, **highest-value first**. Cite the written files:

- Top 3–5 priorities from `analysis.md`
- Where the full report lives (`starboard-reports/<workspace>-<date>/`)
- Offer to discuss any domain in depth or run additional domains

`$` figures are **list-price DBU estimates** — label them as such.

## Fallback — `starboard-helper` raw fetch

If the bundled helper is unavailable (e.g. `starboard-kernel` not installed),
enumerate resources directly with `starboard-helper` and reason over what it
returns:

```bash
starboard-helper job list --limit 100
starboard-helper cluster list
starboard-helper warehouse list
starboard-helper uc catalogs
```

In fallback mode, write the same output layout as above (omitting `plan.json` and
the `raw/` files, which require the bundled helper).

## Single-shot mode (alternative)

For callers who want the old one-blob behavior, or for a quick informal check:

```bash
python -m starboard_x.discovery run --data-only [--packs DOMAIN ...]
```

This returns the full envelope (all packs, all rows) to stdout. For large
workspaces this can produce a multi-megabyte payload that may truncate under
stdout capture. The incremental `--only --out-dir` flow (Steps 2–5) is preferred
for production use.

## Exit codes (from the bundled helper)

- 0: success
- 1: authentication error — check `DATABRICKS_HOST` / `DATABRICKS_TOKEN` (or `--profile`)
- 2: resource not found
- 3: API error — check workspace connectivity
- 4: bad arguments (e.g. unknown pack name with `--only`; mutually exclusive `--only`/`--packs`)
