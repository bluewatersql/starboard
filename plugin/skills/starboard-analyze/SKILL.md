---
name: starboard-analyze
description: "Run a comprehensive, cross-domain analysis of a Databricks workload — combining job, cluster, query, and cost data into a unified optimization report. Use when the user asks for an overall workload review, a full optimization report, or a combined health-and-cost assessment spanning multiple domains."
allowed-tools: Bash(starboard-helper:*), Read, Write
---

# Starboard: Comprehensive Analysis

Run a comprehensive analysis of a Databricks workload — combining job, cluster,
query, and cost data into a unified optimization report.

## You are the analyst

**You** are the LLM for this skill. The skill hands you deterministic data from
multiple domains; **you** synthesize the cross-domain findings and write the
unified report yourself.

Do **not** call the `starboard` goal agent, an MCP `*_analysis` / `synthesize_*`
tool, a model-serving endpoint, or any other model. There is no second LLM in
this loop — the data step below uses plain CLI fetches (no LLM), and you do the
reasoning. Handing analysis to another model defeats the point of the skill and
breaks when that model's credentials differ from your session's.

## Step 1 — Confirm inputs

Before loading data, confirm the run parameters with the user — but **only ask
for what they haven't already given**. If their request already specifies a value
(e.g. "analyze the last 60 days"), use it and skip that question. If they say
"just go" / "use defaults", proceed with the defaults.

Ask for (with defaults):

- **Lookback window** — how many days of history to include (default: **30**).
- **Scope** — all domains, or focus on specific ones (jobs, clusters, queries,
  cost)? Default: **all**.
- **Workspace / profile** — which `--profile` to target, if it's ambiguous
  (default: the ambient `DATABRICKS_*` env / default profile).

## Step 2 — Load the data (deterministic, no LLM)

Determine what to analyze from user input (job ID, cluster ID, warehouse ID, or a
named workload), then fetch data across all relevant domains. The commands are
pre-approved by this skill's `allowed-tools`, so they run without a permission
prompt:

```bash
# Gather data from all relevant domains
starboard-helper job fetch --job-id <JOB_ID>
starboard-helper job runs --job-id <JOB_ID> --limit 10
starboard-helper diagnostic run-state --run-id <LATEST_RUN_ID>
starboard-helper cluster fetch --cluster-id <CLUSTER_ID>
starboard-helper cluster events --cluster-id <CLUSTER_ID> --limit 50
```

Run additional commands as the workload scope demands (warehouse, query, finops).

## Step 3 — Analyze the data yourself

Read the returned data and connect findings across domains:

- **Job → Cluster** — does job configuration match cluster sizing for the
  workload?
- **Run history → Events** — do cluster error events correlate with job failures?
- **Duration trends → Cost** — is increasing run duration driving cost growth?
- **Retry patterns → Failure modes** — are failures transient (retry works) or
  systematic?

## Step 4 — Produce the comprehensive report

1. **Executive summary** — overall health in 2–3 sentences
2. **Critical issues** — immediate action required
3. **Performance analysis** — bottlenecks and optimization opportunities
4. **Cost analysis** — waste and rightsizing opportunities
5. **Recommended actions** — ordered by impact, with specific implementation steps
6. **Estimated impact** — time/cost savings from top recommendations

`$` figures are **list-price DBU estimates** — label them as such.

### Offer to save the report

After presenting the findings, **offer** to save them as a Markdown report:

> "Want me to save this as a report? I'll write it to
> `./starboard-reports/analyze-<YYYY-MM-DD>.md`."

If the user accepts, create the `./starboard-reports/` directory if needed and
write the full report there (use today's date; if a file for today already
exists, add a `-2`, `-3`, … suffix). Confirm the path you wrote. Don't write
anything unless the user opts in.

## Exit codes

- 0: success
- 1: authentication error — check `DATABRICKS_HOST` and `DATABRICKS_TOKEN`
- 2: resource not found
- 3: API error — check workspace connectivity
