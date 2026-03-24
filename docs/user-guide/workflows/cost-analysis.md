# Workflow: Cost Analysis

This guide walks through end-to-end workflows for analyzing Databricks costs,
generating chargeback reports, and identifying optimization opportunities using the
Starboard AI agent.

---

## When to Use This Workflow

- You need to understand where your Databricks spend is going.
- You want to identify cost spikes or unexpected billing increases.
- You need to generate chargeback reports for internal teams.
- You want to right-size warehouses or clusters to reduce costs.
- You are preparing a FinOps review or budget forecast.

---

## Agents Involved

Cost analysis typically involves two specialist agents:

### FinOps Expert (Analytics Agent)

Handles cost trend analysis, billing breakdowns, budget forecasting, and usage-pattern
questions. Uses an **Agentic RAG** approach: it builds context from your Databricks
system tables, generates SQL queries, validates them, and executes them to produce
data-driven answers.

| Tool | Purpose |
|------|---------|
| `build_analytics_context` | Gather relevant schema and metadata from system tables. |
| `build_sql_query` | Generate SQL from your question plus RAG context. |
| `validate_sql_query` | Validate generated SQL (syntax + EXPLAIN). |
| `execute_sql_query` | Execute the SQL and return results. |

### Warehouse Expert

Handles SQL warehouse portfolio analysis, health scoring, SLO compliance, user
activity tracking, and chargeback generation.

| Tool | Purpose |
|------|---------|
| `get_warehouse_portfolio` | List all warehouses with utilization metrics. |
| `get_warehouse_fingerprint` | Deep analysis of a specific warehouse. |
| `get_warehouse_health` | Health scoring and SLO compliance checks. |
| `configure_warehouse_slo` | Set or update SLO targets for a warehouse. |
| `analyze_warehouse_topology` | Cross-warehouse analysis for consolidation. |
| `get_warehouse_user_activity` | Per-user activity breakdown. |
| `generate_warehouse_chargeback` | Single-warehouse chargeback report. |
| `generate_portfolio_chargeback` | Portfolio-wide chargeback report. |

!!! note "Automatic routing"
    You do not need to choose which agent to use. The Router automatically
    directs cost-related questions to the FinOps Expert and warehouse-specific
    questions to the Warehouse Expert. You can also ask follow-up questions
    that trigger a handoff between the two.

---

## Common Workflows

### 1. Cost Trend Analysis

**Goal:** Understand how Databricks costs have changed over a time period.

**Web UI:**
```
Analyze Databricks cost trends for the last 30 days. Break down by
compute type and identify the top cost drivers.
```

**CLI:**
```bash
starboard --goal "Show Databricks cost trends for the last 30 days, broken down by compute type"
```

#### What the Agent Does

1. **Builds analytics context** -- The FinOps Expert gathers metadata about your
   billing and usage system tables (e.g., `system.billing.usage`,
   `system.billing.list_prices`).

2. **Generates SQL** -- Based on your question and the available schema, the agent
   writes a SQL query against the system tables.

3. **Validates the query** -- Runs syntax checking and EXPLAIN to ensure correctness.

4. **Executes and analyzes** -- Runs the query, processes the results, and generates
   a report with visualizations.

#### Report Contents

The **Analytics Report** includes:

- **Cost Summary** -- Total spend, daily average, period-over-period change.
- **Breakdown by Category** -- Compute (jobs, SQL warehouses, notebooks),
  storage, data transfer.
- **Top Cost Drivers** -- The specific jobs, warehouses, or clusters consuming
  the most credits.
- **Trend Charts** -- Daily or weekly cost trends with trendlines.
- **Findings** -- Anomalies, spikes, or inefficiencies identified in the data.
- **Recommendations** -- Actionable steps to reduce costs.

---

### 2. Warehouse Cost Deep-Dive

**Goal:** Analyze a specific SQL warehouse's cost and utilization.

```
Analyze warehouse wh-prod-analytics. Show utilization, cost per query,
and whether it is right-sized.
```

#### What the Agent Does

```
-> Get Warehouse Fingerprint
-> Get Warehouse Health
-> Get Warehouse User Activity
```

#### Report Contents

The **Warehouse Report** includes:

- **Portfolio Overview** -- Where this warehouse fits in the fleet.
- **Health Gauge** -- Overall health score based on utilization, queue times,
  and error rates.
- **Utilization Metrics** -- Peak vs. off-peak usage, idle time percentage.
- **Cost per Query** -- Average and P95 cost per query.
- **User Activity Table** -- Which users and teams are driving usage.
- **Right-Sizing Recommendation** -- Whether the warehouse should be scaled up,
  down, or reconfigured (e.g., auto-stop timeout, cluster size).

---

### 3. Chargeback Reports

**Goal:** Generate internal chargeback reports attributing costs to teams or
business units.

#### Single Warehouse Chargeback

```
Generate a chargeback report for warehouse wh-prod-analytics for February 2026.
```

**CLI:**
```bash
starboard --goal "Generate chargeback report for warehouse wh-prod-analytics for February 2026" \
          --output-path ./reports/
```

#### Portfolio-Wide Chargeback

```
Generate a chargeback report across all SQL warehouses for the last month,
grouped by team.
```

#### Report Contents

Chargeback reports include:

- **Per-User Breakdown** -- Credits consumed by each user.
- **Per-Team Breakdown** -- Aggregated by team or business unit (based on user
  group mappings).
- **Query Counts** -- Number of queries per user/team.
- **Cost Allocation** -- Proportional cost attribution based on actual usage.
- **Exportable Format** -- Reports can be downloaded as JSON or Markdown for
  integration with billing systems.

---

### 4. Cross-Warehouse Optimization

**Goal:** Identify consolidation opportunities across the warehouse fleet.

```
Analyze topology across all SQL warehouses. Are there consolidation
opportunities to reduce costs?
```

#### What the Agent Does

```
-> Get Warehouse Portfolio
-> Analyze Warehouse Topology
```

#### Report Contents

- **Fleet Overview** -- All warehouses with size, type, and utilization.
- **Topology Cards** -- Visual summary of each warehouse's workload profile.
- **Consolidation Candidates** -- Warehouses with overlapping workloads or low
  utilization that could be merged.
- **Right-Sizing Grid** -- Recommendations for each warehouse (keep, resize,
  merge, decommission).

---

### 5. Budget Forecasting

**Goal:** Predict future Databricks costs based on current trends.

```
Based on the last 90 days of billing data, forecast Databricks costs
for the next quarter. Highlight any categories with accelerating growth.
```

The FinOps Expert analyzes historical billing data, identifies growth trends, and
projects future costs with confidence intervals.

---

### 6. Anomaly Investigation

**Goal:** Investigate an unexpected cost spike.

```
We saw a 3x cost spike on February 15. What caused it?
```

The agent queries billing data for that date, identifies which resources drove the
spike (specific jobs, warehouses, or ad-hoc queries), and provides a root-cause
explanation.

---

## Example Conversation

---

**You:**
> Analyze Databricks cost trends for the last 30 days. Which warehouses are
> costing the most, and are any of them underutilized?

**FinOps Expert** (thinking for 15s):
> *-> Build Analytics Context*
> *-> Build SQL Query*
> *-> Validate SQL Query*
> *-> Execute SQL Query*

**FinOps Expert:**
> ## Cost Analysis Report (Feb 1 -- Mar 1, 2026)
>
> ### Cost Summary
> | Metric | Value |
> |--------|-------|
> | Total spend | $47,230 |
> | Daily average | $1,574 |
> | vs. previous 30 days | +12.3% |
>
> ### Top 5 Cost Drivers
> | Resource | Type | Credits | % of Total |
> |----------|------|---------|------------|
> | wh-prod-analytics | SQL Warehouse | 12,450 | 26.4% |
> | wh-prod-etl | SQL Warehouse | 8,920 | 18.9% |
> | etl-daily-cluster | All-Purpose | 7,100 | 15.0% |
> | wh-dev-sandbox | SQL Warehouse | 4,800 | 10.2% |
> | ml-training-cluster | All-Purpose | 3,200 | 6.8% |
>
> ### Findings
>
> **1. Dev Sandbox Warehouse Running 24/7 (Impact: High)**
> `wh-dev-sandbox` consumed $4,800 in credits but has only 15% utilization
> during business hours and near-zero usage nights/weekends. The auto-stop
> timeout is set to 120 minutes.
>
> **Recommendation:** Reduce auto-stop timeout to 10 minutes. Estimated
> savings: $2,400/month (50% reduction).
>
> **2. ETL Warehouse Over-Provisioned (Impact: Medium)**
> `wh-prod-etl` is a 2X-Large warehouse but peak concurrency never exceeds
> what a Large warehouse could handle.
>
> **Recommendation:** Downsize to Large. Estimated savings: $3,500/month.

**What would you like to do next?**

1. Generate a chargeback report for the top 3 warehouses -- **Continue**
2. Deep-dive into wh-dev-sandbox utilization patterns -- **Expert** (Warehouse)
3. Forecast costs for Q2 based on current trends -- **Continue**

---

**You:**
> Deep-dive into wh-dev-sandbox utilization patterns.

**Warehouse Expert** (thinking for 10s):
> *-> Get Warehouse Fingerprint*
> *-> Get Warehouse Health*
> *-> Get Warehouse User Activity*

**Warehouse Expert:**
> ## Warehouse Analysis: wh-dev-sandbox
>
> ### Health Score: 42/100 (Poor)
>
> | Metric | Value | Assessment |
> |--------|-------|------------|
> | Avg utilization | 15% | Very Low |
> | Peak utilization | 38% | Low |
> | Auto-stop timeout | 120 min | Too High |
> | Idle hours/day | 18.5 | Excessive |
> | Avg query latency | 1.2s | Good |
>
> ### User Activity
> | User | Queries/Day | Credits/Month | Peak Hours |
> |------|-------------|---------------|------------|
> | alice@company.com | 45 | $1,800 | 9am-5pm |
> | bob@company.com | 22 | $1,200 | 10am-3pm |
> | ci-pipeline | 8 | $1,800 | 2am-4am |
>
> ### Recommendations
> 1. Reduce auto-stop to 10 minutes (saves $2,400/month).
> 2. Move ci-pipeline queries to wh-prod-etl (already running at 2am).
> 3. Consider a Small warehouse for dev use (current: Medium).

---

## Follow-Up Questions

After any cost analysis, you can ask:

```
Show me the daily cost trend as a chart.
```

```
Which users are driving the most cost on wh-prod-analytics?
```

```
Compare this month's costs to the same period last year.
```

```
What would we save if we moved all dev workloads to serverless?
```

```
Generate a CSV-ready chargeback report for the finance team.
```

---

## Tips

!!! tip "Specify time ranges"
    Always include a time range in your cost questions ("last 30 days",
    "February 2026", "Q4 2025"). This helps the agent generate precise queries
    against the billing system tables.

!!! tip "Use chargeback for team accountability"
    Chargeback reports with per-user breakdowns are powerful tools for driving
    cost awareness. Generate them monthly and share with team leads.

!!! tip "Combine with warehouse analysis"
    The most actionable cost reductions come from combining FinOps trend data
    with warehouse-level deep-dives. Start with "where is the money going?"
    (FinOps Expert), then drill into specific warehouses (Warehouse Expert).

!!! tip "Save reports for comparison"
    Use `--output-path` in the CLI to save reports, then compare month-over-month:
    ```bash
    starboard --goal "Cost analysis for February 2026" \
              --output-path ./reports/2026-02/

    starboard --goal "Cost analysis for March 2026" \
              --output-path ./reports/2026-03/
    ```

!!! note "System tables required"
    Cost analysis requires access to Databricks system tables
    (`system.billing.usage`, `system.billing.list_prices`, etc.). If these
    tables are not enabled in your workspace, contact your Databricks admin
    to enable them. The agent will inform you if it cannot access the required
    data.
