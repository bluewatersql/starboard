---
name: starboard-job
description: Analyze Databricks jobs and workflows — fetch configuration, inspect run history, diagnose failures, and recommend optimizations. Use when the user asks about job failures, job or workflow performance, run history, or job scheduling.
compatibility: opencode
metadata:
  source: packages/starboard-skills/skills/starboard/starboard-job/SKILL.md
---

# Starboard: Job Analysis

Analyze Databricks jobs — fetch configuration, inspect run history, diagnose
failures, and recommend optimizations.

## You are the analyst

**You** are the LLM for this skill. The skill hands you deterministic job
configuration and run data; **you** read the history and write the health
assessment and recommendations yourself.

Do **not** call the `starboard` goal agent, an MCP `*_analysis` / `synthesize_*`
tool, a model-serving endpoint, or any other model. There is no second LLM in
this loop — the data step below uses plain CLI fetches (no LLM), and you do the
reasoning. Handing analysis to another model defeats the point of the skill and
breaks when that model's credentials differ from your session's.

## Step 1 — Load the data (deterministic, no LLM)

Use `starboard-helper` to fetch job configuration and run history. The commands
are pre-approved by this skill's `allowed-tools`, so they run without a permission
prompt:

```bash
starboard-helper job fetch --job-id <JOB_ID>
starboard-helper job runs --job-id <JOB_ID> --limit 10
starboard-helper job list --limit 25 --name-filter <FILTER>
```

Inspect job fetch: task types, cluster config, schedule, timeout settings, max
retries.
Inspect runs: run states (SUCCESS/FAILED/CANCELED), durations, failure patterns.

## Step 2 — Analyze the data yourself

Read the returned configuration and run history:

- **Failure patterns** — are failures consistent (config issue) or intermittent
  (resource issue)?
- **Performance** — are run durations increasing over time? Possible data skew or
  cluster undersizing.
- **Configuration** — is the cluster correctly sized? Are retries configured
  appropriately?
- **Cost** — is the cluster kept alive between runs unnecessarily?

## Step 3 — Produce the report

1. Summary of job health (healthy / degraded / failing)
2. Root cause(s) of failures if any
3. Specific, actionable recommendations
4. Priority: critical / high / medium / low

## Exit codes

- 0: success
- 1: authentication error — check `DATABRICKS_HOST` and `DATABRICKS_TOKEN`
- 2: job not found — verify job ID
- 3: API error — check workspace connectivity
