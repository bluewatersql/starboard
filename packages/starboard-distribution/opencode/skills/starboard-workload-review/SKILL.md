---
name: starboard-workload-review
description: 'Review a Databricks workspace''s jobs, SQL queries, and warehouses — plus opt-in DLT pipelines, ML/model-serving, and Vector Search surfaces — the way a code review reviews code: a ranked, evidence-cited set of findings with severity, impact/effort scores, and remediation, over public system.* data only. Use when the user wants a workload review, an optimization/health assessment of jobs/queries/warehouses/pipelines/ML/vector-search, or prioritized findings with citations.'
compatibility: opencode
metadata:
  source: packages/starboard-skills/skills/starboard/starboard-workload-review/SKILL.md
---

# Starboard: Workload Review

Review a workspace's **jobs, SQL queries, and warehouses** and emit a ranked,
evidence-cited set of findings — the way Isaac `/review` reviews code — built
from harvested review methodology running on **public `system.*` data only**.
Each finding carries a severity, an impact/effort priority score, a paraphrased
remediation, and an **evidence citation** (the query-pack `query_id` + the row
that triggered it).

## Review domains

The default scope is **jobs + sql + warehouse**. Additional **opt-in** domains
extend the same rule engine over query packs that are already present — pass them
via `--domains`:

| Domain token | Covers | Example findings |
|---|---|---|
| `jobs` (default) | Job runs & reliability | high failure rate, wasted-DBU retries, runtime variance |
| `sql` (default) | Query performance | `SELECT *` wide projection, non-sargable partition filters |
| `warehouse` (default) | SQL warehouses | auto-stop disabled, persistently under-utilized |
| `uc` | Unity Catalog tables | missing table maintenance |
| `dlt` (alias `pipelines`) | DLT / Lakeflow pipelines | high update failure rate, stale pipelines, classic→serverless candidates |
| `ml` | ML & model serving | billed test/demo endpoints to clean up, noisy MLflow experiments |
| `vector-search` | Vector Search | idle (billed, unqueried) endpoints, top-DBU right-sizing targets |

The opt-in domains are **additive** — v1 defaults and their findings are
unchanged, and each new finding still cites its evidence `query_id` + row. All `$`
framing is a **list-price DBU estimate**, never a finance-grade figure.

## Dual-Mode Behavior

**Check which tools are available before proceeding:**

If `mcp__starboard__*` tools are available in your context, use them for full
agent orchestration (the agent stack runs the review and the validator council):

```
mcp__starboard__review  (or similar MCP tool)
```

If MCP tools are NOT available, run the bundled Tier-1 review script below.

## Tier 1 — bundled review (deterministic, no LLM)

If `${CLAUDE_SKILL_DIR}/scripts/run.sh` exists, run the deterministic Workload
Review end-to-end against the resolved workspace (query packs + rule scoring,
**no LLM**). It emits the stable JSON envelope
(`{ok, domain, command, data|error, meta}`) to stdout and runs out-of-context in
Python — the command is pre-approved, so no permission prompt appears:

```bash
# Default scope: jobs + sql + warehouse
${CLAUDE_SKILL_DIR}/scripts/run.sh

# Restrict domains and/or select a workspace profile
${CLAUDE_SKILL_DIR}/scripts/run.sh --domains warehouse,sql
${CLAUDE_SKILL_DIR}/scripts/run.sh --workspace my-profile --lookback-days 60

# Opt-in surfaces (additive to the jobs/sql/warehouse defaults)
${CLAUDE_SKILL_DIR}/scripts/run.sh --domains dlt,ml,vector-search
```

Read the JSON and synthesize the review:
- `data.findings` — ranked findings; each has `finding` (severity, score,
  category, summary, rationale, current_state, suggested_fix) and `evidence`
  (a list of `{query_id, row_index, row}` citations).
- `data.domain_reports` — per-domain coverage and whether a domain `degraded`
  (partial evidence).
- `data.cost_basis` — the public $ basis label; findings are DBU / utilization
  based (a **list-price estimate**, never a finance-grade figure).

Requires `pip install "starboard"` (the server package supplies the SDK-backed
pack execution). Present findings highest-priority first, and cite the
`query_id` + row for each.

## Offline scoring (pure, pre-fetched rows)

When you already have query-pack rows (e.g. from a prior discovery run) and want
to score them without touching the workspace, use the pure SDK-free helper:

```bash
python -m starboard_x.review score --rows rows.json --domains jobs,sql,warehouse
```

where `rows.json` maps each evidence `query_id` to a list of row objects
(e.g. `{"W-W02": [{"warehouse_id": "wh1", "auto_stop_waste_pct": 80.0}]}`).

## Tier 0 — assemble from `starboard-helper` (no bundled script)

If neither the MCP tools nor the bundled Tier-1 script are available, gather the
per-domain inputs with the zero-dep `starboard-helper` CLI and then score them
with the offline helper above:

```bash
starboard-helper job list
starboard-helper query list
starboard-helper warehouse list
```

Shape the returned rows into the `{query_id: [rows]}` map and run
`python -m starboard_x.review score`. This keeps the review available on the pure
fetch tier when the server package is not installed.

## Exit Codes
- 0: success
- 1: authentication error — check the workspace profile / DATABRICKS_HOST + DATABRICKS_TOKEN
- 2: resource not found
- 3: API error — check workspace connectivity
- 4: argument error — check `--domains` / `--rows`
