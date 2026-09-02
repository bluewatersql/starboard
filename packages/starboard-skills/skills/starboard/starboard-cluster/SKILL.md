---
name: starboard-cluster
description: "Analyze Databricks clusters — inspect configuration, review events, diagnose failures, and recommend optimizations. Use when the user asks about cluster performance, autoscaling, node types, cluster failures, or compute sizing."
allowed-tools: Bash(starboard-helper:*), Read, Write
---

# Starboard: Cluster Analysis

Analyze Databricks clusters — inspect configuration, review events, diagnose
failures, and recommend optimizations.

## You are the analyst

**You** are the LLM for this skill. The skill hands you deterministic cluster
data; **you** read the configuration, events, and metrics and write the assessment
and recommendations yourself.

Do **not** call the `starboard` goal agent, an MCP `*_analysis` / `synthesize_*`
tool, a model-serving endpoint, or any other model. There is no second LLM in
this loop — the data step below uses plain CLI fetches (no LLM), and you do the
reasoning. Handing analysis to another model defeats the point of the skill and
breaks when that model's credentials differ from your session's.

## Step 1 — Confirm inputs

Before loading data, confirm the run parameters with the user — but **only ask
for what they haven't already given**. If their request already specifies a value
(e.g. "check cluster 0123-456789-abc"), use it and skip that question. If they
say "just go" / "use defaults", proceed with the defaults.

Ask for (with defaults):

- **Which clusters** — all running clusters, or a specific cluster ID / name?
  Default: **all running clusters**.
- **Events lookback window** — how many recent events to fetch per cluster
  (default: **50**).
- **Workspace / profile** — which `--profile` to target, if it's ambiguous
  (default: the ambient `DATABRICKS_*` env / default profile).

## Step 2 — Load the data (deterministic, no LLM)

Use `starboard-helper` to fetch cluster data. The commands are pre-approved by
this skill's `allowed-tools`, so they run without a permission prompt:

```bash
starboard-helper cluster list
starboard-helper cluster list --filter-by-state RUNNING
starboard-helper cluster fetch --cluster-id <CLUSTER_ID>
starboard-helper cluster events --cluster-id <CLUSTER_ID> --limit 50
starboard-helper cluster spark-context --cluster-id <CLUSTER_ID>
```

## Step 3 — Analyze the data yourself

Read the returned configuration and events:

- **Sizing** — is the node type and worker count appropriate for the workload?
- **Autoscaling** — is autoscale configured and within appropriate min/max bounds?
- **Events** — are there recurring error events (OOM, node lost, preemption)?
- **Spark config** — are there performance-relevant configs set (shuffle
  partitions, memory fractions)?
- **Lifespan** — are long-running clusters accumulating state, or should they be
  ephemeral?
- **Source** — are clusters created interactively (risk) vs. job-attached
  (preferred for production)?

### Right-sizing + cost impact

Using the fetched config (node type, worker count, autoscale bounds) plus any
utilization signals, classify each cluster's sizing direction and project the
list-price cost impact:

- **Over-provisioned** (low CPU/memory p95): recommend a smaller node SKU or
  fewer/lower autoscale-min workers; estimate the `reduction_pct` and the
  **list-price DBU $/month** saved.
- **Under-provisioned** (high CPU/memory p95, autoscale pinned at max):
  recommend raising the autoscale max or a larger SKU.
- **Balanced**: no action.

Project cost as a **list-price DBU estimate**:
`monthly_cost ≈ dbus_per_day × 30 × list_price_per_dbu` and
`monthly_savings ≈ monthly_cost × reduction_pct / 100`. Always label the figure a
*list-price DBU estimate* — it is not a contracted-rate cost.

## Step 4 — Produce the report

1. Cluster fleet overview
2. Right-sizing recommendations with list-price DBU $/month impact
3. Event-based failure diagnosis
4. Spark configuration tuning suggestions
5. Priority: critical / high / medium / low

### Offer to save the report

After presenting the findings, **offer** to save them as a Markdown report:

> "Want me to save this as a report? I'll write it to
> `./starboard-reports/cluster-<YYYY-MM-DD>.md`."

If the user accepts, create the `./starboard-reports/` directory if needed and
write the full report there (use today's date; if a file for today already
exists, add a `-2`, `-3`, … suffix). Confirm the path you wrote. Don't write
anything unless the user opts in.

## Exit codes

- 0: success
- 1: authentication error — check `DATABRICKS_HOST` and `DATABRICKS_TOKEN`
- 2: cluster not found — verify cluster ID
- 3: API error — check workspace connectivity
