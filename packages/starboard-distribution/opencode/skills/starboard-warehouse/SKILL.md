---
name: starboard-warehouse
description: Analyze Databricks SQL warehouses — inspect configuration, monitor state, and identify sizing and cost issues. Use when the user asks about SQL warehouse configuration, warehouse sizing, autostop, or warehouse cost and performance.
compatibility: opencode
metadata:
  source: packages/starboard-skills/skills/starboard/starboard-warehouse/SKILL.md
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

## Step 1 — Load the data (deterministic, no LLM)

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

## Step 2 — Analyze the data yourself

Read the returned configuration and metrics:

- **Sizing** — is `cluster_size` appropriate for the active session count?
- **Scaling** — is `max_num_clusters` unnecessarily high, driving cost?
- **Auto-stop** — is `auto_stop_mins` configured too high (idle cost)?
- **Type** — should classic warehouses be migrated to serverless for variable
  workloads?
- **Health** — are there any health warnings or errors?

## Step 3 — Produce the report

1. Summary of warehouse fleet health
2. Rightsizing recommendations per warehouse
3. Cost optimization opportunities (auto-stop, serverless migration)
4. Priority: critical / high / medium / low

`$` figures are **list-price DBU estimates** — label them as such.

## Exit codes

- 0: success
- 1: authentication error — check `DATABRICKS_HOST` and `DATABRICKS_TOKEN`
- 2: warehouse not found — verify warehouse ID
- 3: API error — check workspace connectivity
