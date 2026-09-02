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

## You are the analyst

**You** are the LLM for this skill. The skill hands you deterministic review
findings; **you** read the ranked findings and evidence citations and write the
workload review report yourself.

Do **not** call the `starboard` goal agent, an MCP `*_analysis` / `synthesize_*`
tool, a model-serving endpoint, or any other model. There is no second LLM in
this loop — the data step below runs deterministic Python (no LLM), and you do
the reasoning. Handing analysis to another model defeats the point of the skill
and breaks when that model's credentials differ from your session's.

## Step 1 — Load the data (deterministic Python, no LLM)

Run the bundled Workload Review script. It executes the full review end-to-end
against the resolved workspace — query packs + rule scoring, **no LLM** — and
emits the stable JSON envelope (`{ok, domain, command, data|error, meta}`) to
stdout. The command is pre-approved, so no permission prompt appears:

```bash
# Default scope: jobs + sql + warehouse
${CLAUDE_SKILL_DIR}/scripts/run.sh

# Restrict domains and/or select a workspace profile
${CLAUDE_SKILL_DIR}/scripts/run.sh --domains warehouse,sql
${CLAUDE_SKILL_DIR}/scripts/run.sh --workspace my-profile --lookback-days 60

# Opt-in surfaces (additive to the jobs/sql/warehouse defaults)
${CLAUDE_SKILL_DIR}/scripts/run.sh --domains dlt,ml,vector-search
```

Requires `pip install "starboard"` (the server package supplies the SDK-backed
pack execution).

### What comes back

- `data.findings` — ranked findings; each has `finding` (severity, score,
  category, summary, rationale, current_state, suggested_fix) and `evidence`
  (a list of `{query_id, row_index, row}` citations).
- `data.domain_reports` — per-domain coverage and whether a domain `degraded`
  (partial evidence).
- `data.cost_basis` — the public $ basis label; findings are DBU / utilization
  based (a **list-price estimate**, never a finance-grade figure).

### Offline scoring (pure, pre-fetched rows)

When you already have query-pack rows and want to score them without touching the
workspace, use the pure SDK-free helper:

```bash
python -m starboard_x.review score --rows rows.json --domains jobs,sql,warehouse
```

where `rows.json` maps each evidence `query_id` to a list of row objects
(e.g. `{"W-W02": [{"warehouse_id": "wh1", "auto_stop_waste_pct": 80.0}]}`).

### Fallback — assemble from starboard-helper

If the bundled script is unavailable, gather per-domain inputs with
`starboard-helper` and score them with the offline helper above:

```bash
starboard-helper job list
starboard-helper query history
starboard-helper warehouse list
```

Shape the returned rows into the `{query_id: [rows]}` map and run
`python -m starboard_x.review score`.

## Step 2 — Analyze the findings yourself

Read the ranked findings from `data.findings` and assess the workspace:

- **Severity and score** — which findings are critical / high / medium / low?
- **Evidence citations** — each finding cites `query_id` + row; confirm the data
  supports the finding.
- **Domain coverage** — note any `degraded` domains where evidence is partial.
- **Cost exposure** — surface list-price DBU estimates from findings; always label
  as *list-price estimates*.

## Step 3 — Produce the workload review

Present findings highest-priority first; cite the `query_id` + row for each:

1. **Executive summary** — overall workspace health in 2–3 sentences
2. **Ranked findings** — severity, score, category, summary, evidence citation,
   and suggested fix per finding
3. **Domain coverage** — which domains were reviewed and any degraded coverage
4. **Recommended actions** — top 3–5 remediations ordered by impact

`$` figures are **list-price DBU estimates** — label them as such.

## Exit codes

- 0: success
- 1: authentication error — check the workspace profile / `DATABRICKS_HOST` + `DATABRICKS_TOKEN`
- 2: resource not found
- 3: API error — check workspace connectivity
- 4: argument error — check `--domains` / `--rows`
