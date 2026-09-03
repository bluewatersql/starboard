# Workflows

Recipes for common Starboard tasks. Every command here is **read-only** against your workspace.
Cost figures are **list-price DBU estimates**.

| Goal | Command |
|------|---------|
| Ranked findings across jobs, SQL, warehouses | `starboard review` |
| Workspace health scorecard | `starboard --discover` |
| NL goal — specific resource or question | `starboard --goal "..."` |
| Interactive multi-turn | `starboard --chat` or `--session <name>` |

---

## Workload Review

Get a deterministic, ranked, evidence-cited list of findings over public `system.*` data.

```bash
starboard review                              # default domains: jobs, sql, warehouse
starboard review --domains warehouse,sql      # narrow scope
starboard review --lookback-days 60           # widen evidence window
starboard review --min-severity high          # suppress low-signal findings
starboard review --json                       # machine-readable envelope
```

Track fix progress between runs:

```bash
starboard review --snapshot-out before.json  # save baseline
# ... make fixes ...
starboard review --since before.json         # show resolved-rate delta
```

**Output:** ranked findings with severity, priority score, suggested fix, and evidence citation.
See [Reports](./reports.md) for how to read findings.

---

## Workspace Discovery

30/60/90-day health assessment across billing, compute, governance, and jobs.

```bash
starboard --discover                                        # full, 30-day default
starboard --discover --lookback-days 90
starboard --discover --discovery-domains billing compute    # scope to specific domains
starboard --discover --data-only                            # raw query data, no LLM analysis
```

**Output:** domain report cards graded A–F, top ranked findings, executive summary, and output
files written to `discovery_output/report.md` + `report.json`. All resource consumption is in DBUs.

---

## Query Optimization

Analyze and optimize slow SQL queries using the Query agent.

```bash
# By statement ID (from the Databricks Query History UI)
starboard --goal "Optimize query with statement_id 01ef-abc123-def456"

# From a SQL file
starboard --goal "Optimize this SQL" --input-file queries/slow_query.sql

# Static review — no live API calls (pre-deployment check)
starboard --mode offline --input-file query.sql \
          --goal "Review this query for anti-patterns"
```

**Output:** advisor report with ranked findings (full table scan, data skew, stale stats, missing
partition pruning, etc.), a rewritten optimized query, and a prioritized implementation plan. Evidence
includes execution plan details and runtime metrics where available.

---

## Job Debugging

Investigate failing or slow Databricks jobs using the Job agent.

```bash
starboard --goal "Why did job 12345 fail in its last run?"
starboard --goal "Job 12345 used to complete in 20 minutes but now takes over an hour. What changed?"

# Cross-domain troubleshooting (unrestricted tool access)
starboard --mode diagnostic \
          --goal "Job 12345 fails intermittently — find the root cause"
```

**Output:** diagnostic report with root cause identified (OOM, data growth, code anti-pattern,
config issue), stack trace citations, and specific remediation steps with code examples. For
multi-task jobs, includes critical-path and bottleneck analysis across the task DAG.

---

## Cost Analysis / FinOps

Understand where Databricks spend is going. All figures are **list-price DBU estimates** from
public `system.billing.*` tables.

```bash
starboard --goal "What drove the cost increase last month?"
starboard --goal "Break down DBU spend by warehouse over the last 30 days"
starboard --goal "Which warehouses are underutilized?"
starboard --goal "Generate a chargeback report for all warehouses for February 2026"
starboard --goal "Forecast costs for next quarter based on the last 90 days"
starboard review --domains warehouse          # warehouse cost findings
```

**Output:** cost summary with top drivers, warehouse utilization breakdown, chargeback tables
(per user/team), and right-sizing recommendations with estimated monthly savings (list price).
Use `--output-path ./reports/` to save for month-over-month comparison.

---

## Cluster Optimization

Right-size clusters and identify idle or misconfigured compute using the Cluster agent.

```bash
starboard --goal "Optimize cluster 0123-456789-abcdef for cost and performance"
starboard --goal "Review all active clusters and find cost optimization opportunities"
starboard --goal "Cluster 0123-456789-abcdef has high memory pressure — what is causing it?"
```

**Output:** cluster health grade (A–F) with sub-scores for utilization, cost efficiency,
configuration, and stability. Common findings: oversizing, disabled auto-termination,
autoscaling range issues, suboptimal Spark config, shuffle spill. Recommendations ordered by impact.

---

## Warehouse Optimization

Analyze the SQL warehouse portfolio for cost, SLO compliance, and consolidation opportunities
using the Warehouse agent.

```bash
starboard --goal "Analyze the SQL warehouse portfolio and identify optimization opportunities"
starboard --goal "Deep analysis of warehouse abc123 — health, SLO compliance, and user activity"
starboard --goal "Are there SQL warehouses that could be consolidated?"
starboard --goal "Set p95 latency SLO of 10 seconds on the Production Analytics warehouse"
```

**Output:** portfolio summary table with health grades, utilization, and estimated monthly cost
(list price). Findings include oversized warehouses, low utilization, SLO breaches, and
consolidation candidates. Chargeback reports attribute cost per user and team.

---

## Table Governance (Unity Catalog)

Audit table access, lineage, schema drift, and policy coverage using the UC agent.

```bash
starboard --goal "Audit governance for table analytics.gold.customer_orders"
starboard --goal "Review policy coverage across the analytics.gold schema"
starboard --goal "Has the schema of analytics.gold.customer_orders changed recently?"
starboard --goal "Trace the lineage of analytics.gold.customer_orders"
```

Use fully qualified 3-part names (`catalog.schema.table`).

**Output:** UC analysis report with findings ranked by POLICY, SCHEMA, LINEAGE, or STORAGE
category. Includes effective grants, access-pattern vs. grant comparison, schema drift timeline,
and lineage chain. Remediation shown as ready-to-run SQL (`GRANT`, `REVOKE`, `ALTER TABLE SET MASK`,
`SET ROW FILTER`).

---

## Scripting and Output Options

```bash
# Save JSON + Markdown to a directory
starboard --goal "Analyze job 12345" --output-path ./reports/

# Structured JSON envelope to stdout
starboard --goal "Analyze job 12345" --json > result.json

# Continue a conversation across separate CLI invocations
starboard --goal "Analyze query 01ef-abc123" --session my-project
starboard --goal "Would liquid clustering help here?" --session my-project
```

JSON envelope shape: `{ok, domain, command, data|error, meta}`.
Exit codes: `0` ok · `1` auth · `2` not-found · `3` api-error · `4` arg-error.

---

## Middle-Tier Capabilities (`starboard_x`)

For dep-light, per-capability runs without the full agent stack (installable via
`pip install starboard-core`):

```bash
python -m starboard_x.review score --rows rows.json --domains jobs,sql,warehouse
python -m starboard_x.discovery --help
python -m starboard_x.warehouse --help
```

Available: `diagnostic`, `discovery`, `review`, `sparklog`, `uc`, `warehouse`.
All emit the shared JSON envelope.

---

## See Also

- [CLI reference](./cli.md) — all flags and environment variables
- [Reports](./reports.md) — how to read findings, severity, and evidence
- [Agents overview](../overview/agents.md) — which agent handles what
- [Skills](./skills.md) — run these workflows from Claude Code / Cursor
