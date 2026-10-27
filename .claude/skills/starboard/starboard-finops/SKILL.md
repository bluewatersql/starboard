---
name: starboard-finops
description: "Analyze Databricks cost and usage — fetch billable usage, review budgets, and identify cost optimization opportunities. Use when the user asks about spend, billing, cost drivers, budgets, or FinOps and cost optimization."
allowed-tools: Bash(starboard-helper:*), Read
---

# Starboard: FinOps Analysis

Analyze Databricks cost and usage — fetch billable usage, review budgets, and
identify cost optimization opportunities.

## You are the analyst

**You** are the LLM for this skill. The skill hands you deterministic usage and
billing data; **you** read the rows and write the cost assessment and
recommendations yourself.

Do **not** call the `starboard` goal agent, an MCP `*_analysis` / `synthesize_*`
tool, a model-serving endpoint, or any other model. There is no second LLM in
this loop — the data step below uses plain CLI fetches (no LLM), and you do the
reasoning. Handing analysis to another model defeats the point of the skill and
breaks when that model's credentials differ from your session's.

## Step 1 — Load the data (deterministic, no LLM)

Use `starboard-helper` to fetch cost and usage data. The commands are pre-approved
by this skill's `allowed-tools`, so they run without a permission prompt:

```bash
starboard-helper finops usage --start-date YYYY-MM-DD --end-date YYYY-MM-DD
starboard-helper finops budgets
starboard-helper finops log-delivery
```

## Step 2 — Analyze the data yourself

Read the returned usage and budget data:

- **Cost drivers** — which SKUs (Jobs Compute, SQL Compute, All-Purpose) dominate
  spend?
- **Trends** — is spend increasing month-over-month? Which workloads are growing?
- **Waste** — are there All-Purpose clusters with low utilization (idle cost)?
- **Budget alerts** — are any budgets close to or exceeding thresholds?
- **Optimization levers** — spot instances, serverless SQL, job cluster ephemeral
  patterns.

## Step 3 — Produce the report

1. Cost summary by SKU and time period
2. Top cost drivers
3. Waste identification (idle resources, oversized clusters)
4. Specific optimization actions with estimated savings
5. Priority: critical / high / medium / low

`$` figures are **list-price DBU estimates** — label them as such.

## Exit codes

- 0: success
- 1: authentication error — check `DATABRICKS_HOST`, `DATABRICKS_ACCOUNT_ID`, and
  `DATABRICKS_TOKEN`
- 2: resource not found
- 3: API error — note: billable usage requires account-level access
