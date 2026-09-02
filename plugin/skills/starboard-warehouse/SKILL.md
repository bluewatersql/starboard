---
name: starboard-warehouse
description: "Analyze Databricks SQL warehouses — inspect configuration, monitor state, and identify sizing and cost issues. Use when the user asks about SQL warehouse configuration, warehouse sizing, autostop, or warehouse cost and performance."
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/run.sh *), Bash(starboard-helper:*), Read, Write
---

# Starboard: Warehouse Analysis

Analyze Databricks SQL warehouses — inspect configuration, monitor state, identify
sizing and cost issues.

## You are the analyst

**You** are the LLM for this skill. The skill hands you deterministic warehouse
data; **you** read the configuration, health, and metrics and write the assessment
and recommendations yourself.

Do **not** call the `starboard` goal agent, an MCP `*_analysis` / `synthesize_*`
tool, a model-serving endpoint, or any other model. There is no second LLM in
this loop — the data step below runs pure Python (no LLM), and you do the
reasoning. Handing analysis to another model defeats the point of the skill and
breaks when that model's credentials differ from your session's.

## Step 1 — Confirm inputs

Before loading data, confirm the run parameters with the user — but **only ask
for what they haven't already given**. If their request already specifies a value
(e.g. "check warehouse abc123"), use it and skip that question. If they say
"just go" / "use defaults", proceed with the defaults.

Ask for (with defaults):

- **Which warehouse(s)** — all warehouses, or a specific warehouse ID / name?
  Default: **all**.
- **Analysis window** — how many days of query history to analyze (default:
  **7**).
- **Workspace / profile** — which `--profile` to target, if it's ambiguous
  (default: the ambient `DATABRICKS_*` env / default profile).

## Step 2 — Load the data (deterministic, no LLM)

### Score a query-history file (bundled helper)

If you already have a warehouse **query-history JSON** on disk (e.g. from
`starboard-helper` or `system.query.history`), score it locally with the pure
fingerprint + health analyzer — no network required. It emits the stable JSON
envelope to stdout and is pre-approved (no permission prompt):

```bash
${CLAUDE_SKILL_DIR}/scripts/run.sh analyze --history <history.json> [--warehouse-id <ID>]
```

The history is either a JSON list of query records or an object
`{"records": [...], "warehouse_id": ..., "warehouse_name": ...}`. Read the
returned `data.fingerprint` + `data.health` (score, status, risk factors,
recommendations), then proceed to Step 2. Requires
`pip install "starboard-kernel[warehouse]"`.

### Fetch live warehouse data (starboard-helper)

To inspect live warehouse configuration and state, use `starboard-helper`:

```bash
starboard-helper warehouse list
starboard-helper warehouse fetch --warehouse-id <WH_ID>
starboard-helper warehouse metrics --warehouse-id <WH_ID>
```

## Step 3 — Analyze the data yourself

Read the returned configuration and metrics:

- **Sizing** — is `cluster_size` appropriate for the active session count?
- **Scaling** — is `max_num_clusters` unnecessarily high, driving cost?
- **Auto-stop** — is `auto_stop_mins` configured too high (idle cost)?
- **Type** — should classic warehouses be migrated to serverless for variable
  workloads?
- **Health** — are there any health warnings or errors?

## Step 4 — Produce the report

1. Summary of warehouse fleet health
2. Rightsizing recommendations per warehouse
3. Cost optimization opportunities (auto-stop, serverless migration)
4. Priority: critical / high / medium / low

`$` figures are **list-price DBU estimates** — label them as such.

### Offer to save the report

After presenting the findings, **offer** to save them as a Markdown report:

> "Want me to save this as a report? I'll write it to
> `./starboard-reports/warehouse-<YYYY-MM-DD>.md`."

If the user accepts, create the `./starboard-reports/` directory if needed and
write the full report there (use today's date; if a file for today already
exists, add a `-2`, `-3`, … suffix). Confirm the path you wrote. Don't write
anything unless the user opts in.

## Exit codes

- 0: success
- 1: authentication error — check `DATABRICKS_HOST` and `DATABRICKS_TOKEN`
- 2: warehouse not found — verify warehouse ID
- 3: API error — check workspace connectivity
