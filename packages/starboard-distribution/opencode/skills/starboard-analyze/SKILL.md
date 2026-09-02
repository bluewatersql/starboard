---
name: starboard-analyze
description: Run a comprehensive, cross-domain analysis of a Databricks workload — combining job, cluster, query, and cost data into a unified optimization report. Use when the user asks for an overall workload review, a full optimization report, or a combined health-and-cost assessment spanning multiple domains.
compatibility: opencode
metadata:
  source: packages/starboard-skills/skills/starboard/starboard-analyze/SKILL.md
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

## Step 1 — Load the data (deterministic, no LLM)

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

## Step 2 — Analyze the data yourself

Read the returned data and connect findings across domains:

- **Job → Cluster** — does job configuration match cluster sizing for the
  workload?
- **Run history → Events** — do cluster error events correlate with job failures?
- **Duration trends → Cost** — is increasing run duration driving cost growth?
- **Retry patterns → Failure modes** — are failures transient (retry works) or
  systematic?

## Step 3 — Produce the comprehensive report

1. **Executive summary** — overall health in 2–3 sentences
2. **Critical issues** — immediate action required
3. **Performance analysis** — bottlenecks and optimization opportunities
4. **Cost analysis** — waste and rightsizing opportunities
5. **Recommended actions** — ordered by impact, with specific implementation steps
6. **Estimated impact** — time/cost savings from top recommendations

`$` figures are **list-price DBU estimates** — label them as such.

## Exit codes

- 0: success
- 1: authentication error — check `DATABRICKS_HOST` and `DATABRICKS_TOKEN`
- 2: resource not found
- 3: API error — check workspace connectivity
