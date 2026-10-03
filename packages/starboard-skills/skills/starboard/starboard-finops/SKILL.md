---
name: starboard-finops
description: "Analyze Databricks cost and usage — load list-price DBU consumption from system.billing.usage, review budgets, and identify cost optimization opportunities. Use when the user asks about spend, billing, cost drivers, budgets, or FinOps and cost optimization."
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/run.sh *), Bash(starboard-helper:*), Read, Write
---

# Starboard: FinOps Analysis

Analyze Databricks cost and usage — load DBU consumption from Unity Catalog
system tables, review budgets, and identify cost optimization opportunities.

## You are the analyst

**You** are the LLM for this skill. The skill hands you deterministic usage and
billing data; **you** read the rows and write the cost assessment and
recommendations yourself.

Do **not** call the `starboard` goal agent, an MCP `*_analysis` / `synthesize_*`
tool, a model-serving endpoint, or any other model. There is no second LLM in
this loop — the data step below runs plain Python / CLI fetches (no LLM), and you
do the reasoning. Handing analysis to another model defeats the point of the
skill and breaks when that model's credentials differ from your session's.

## Step 1 — Confirm inputs

Before loading data, confirm the run parameters with the user — but **only ask
for what they haven't already given**. If their request already specifies a value
(e.g. "show me billing for the last 90 days"), use it and skip that question. If
they say "just go" / "use defaults", proceed with the defaults.

Ask for (with defaults):

- **Lookback window** — how many days of billing history to include (default:
  **30**).
- **Workspace / profile** — which `--profile` to target, if it's ambiguous
  (default: the ambient `DATABRICKS_*` env / default profile).

## Step 2 — Load the data (deterministic, no LLM)

### Workspace cost data (preferred — no account-admin required)

Cost/usage on the workspace-read-only path comes from `system.billing.usage`
(list-price **DBU quantities**, not dollars). Run the bundled helper — it
executes the billing query pack out-of-context in Python and, with `--out-dir`,
**streams the rows to disk** and prints only a compact manifest to stdout. This
keeps a large billing payload from being truncated in the tool result. The
**portable** engine invocation runs on any host (Claude Code, Codex, OpenCode,
`databricks aitools`):

```bash
python -m starboard_x.discovery run --data-only --packs billing \
  --out-dir starboard-reports/<workspace>-<date>/finops
```

Widen the window with `--lookback-days`, or target a profile with `--profile`:

```bash
python -m starboard_x.discovery run --data-only --packs billing \
  --out-dir starboard-reports/<workspace>-<date>/finops --lookback-days 90
python -m starboard_x.discovery run --data-only --packs billing \
  --out-dir starboard-reports/<workspace>-<date>/finops --profile my-profile
```

<!-- claude-only -->
Under Claude Code, the pre-approved convenience wrapper
`${CLAUDE_SKILL_DIR}/scripts/run.sh <args>` runs the identical command with no
permission prompt.
<!-- /claude-only -->

Then read the billing rows **from disk**, not from stdout:

1. **Read the manifest** printed to stdout (`data.manifest[]`) — the `billing`
   entry gives the query/row counts, a `limit_reached` flag (row cap hit), and the `path` to the
   raw file.
2. **Read the raw file** at that `path` (e.g.
   `starboard-reports/<workspace>-<date>/finops/raw/billing.json`): each
   `results[]` query carries the **actual rows** (`columns` + `rows`) — DBU
   consumption by `billing_origin_product` / `sku_name` and by month.
   > **Large or row-capped packs.** If the per-query entry shows `"limit_reached": true`
   > or the raw file is very large, prefer a **summarize-then-reason** pass — use
   > `jq` or Python to pull top-N-by-DBU and per-month aggregates rather than
   > loading the whole file into context.

`data.domain_analyses` here holds only deterministic `kind: "data_only_summary"` entries
(per-domain counts and row pointers; no grade or findings: proof no LLM ran). Requires
`pip install "starboard-kernel[discovery] @ git+https://github.com/bluewatersql/starboard.git#subdirectory=packages/starboard-core"`.

### Account-level billing (optional — requires account-admin credentials)

If you are authenticated with **account-admin** credentials (account console
host + `DATABRICKS_ACCOUNT_ID`), you can also pull account-scoped artifacts.
These use the Account API and return "Not Found" on a plain workspace token, so
they are optional:

```bash
starboard-helper finops usage --start-date YYYY-MM-DD --end-date YYYY-MM-DD --out usage.json
starboard-helper finops budgets
starboard-helper finops log-delivery
```

Account-level `usage` can span many rows — `--out FILE` writes the full envelope
to `FILE` and prints a compact summary (row count + path) to stdout; **read
`FILE`** rather than the truncated inline output. `--out` works on any verb and
may go before or after the subcommand.

## Step 3 — Analyze the data yourself

Read the returned usage/billing rows:

- **Cost drivers** — which products/SKUs (Jobs Compute, SQL Compute, All-Purpose)
  dominate DBU consumption?
- **Trends** — is consumption increasing month-over-month? Which workloads are
  growing?
- **Waste** — All-Purpose clusters with low utilization (idle cost), oversized
  compute.
- **Budget alerts** (if account data available) — are any budgets close to or
  exceeding thresholds?
- **Optimization levers** — spot instances, serverless SQL, ephemeral job clusters.

## Step 4 — Produce the report

1. Consumption summary by product/SKU and time period
2. Top cost drivers
3. Waste identification (idle resources, oversized clusters)
4. Specific optimization actions with estimated savings
5. Priority: critical / high / medium / low

`$` figures are **list-price DBU estimates** — label them as such.

### Offer to save the report

After presenting the findings, **offer** to save them as a Markdown report:

> "Want me to save this as a report? I'll write it to
> `./starboard-reports/<workspace>-<YYYY-MM-DD>/analysis/finops.md`."

If the user accepts, create the run directory `./starboard-reports/<workspace>-<YYYY-MM-DD>/analysis/` if needed, and add/update the run's `README.md` index (a one-line pointer to this report). Write the full report there (use today's date; if a file for today already exists, add a `-2`, `-3`, … suffix to the filename). Confirm the path you wrote. Don't write anything unless the user opts in.

## Exit codes (from the bundled helper)

- 0: success
- 1: authentication error — check `DATABRICKS_HOST` / `DATABRICKS_TOKEN` (or `--profile`)
- 2: resource not found
- 3: API error — check workspace connectivity
- 4: bad arguments (e.g. an unknown `--packs` value)
