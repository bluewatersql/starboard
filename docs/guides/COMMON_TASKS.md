---
title: Common Tasks
description: Step-by-step recipes for running Databricks analyses with Starboard.
last_verified: 2026-08-27
status: current
---

# Common Tasks

Practical, copy-pasteable recipes for the most common things you'll do with Starboard
from the command line. Each assumes you've [installed](./GETTING_STARTED.md#install)
and [authenticated](./GETTING_STARTED.md#authenticate).

> Every command here is read-only against your workspace. Cost figures are **list-price
> DBU estimates**, labelled as such.

---

## Table of Contents

1. [Run a workload review](#run-a-workload-review)
2. [Ask a question in natural language](#ask-a-question-in-natural-language)
3. [Assess a whole workspace](#assess-a-whole-workspace)
4. [Optimize a slow query](#optimize-a-slow-query)
5. [Debug a failing job](#debug-a-failing-job)
6. [Investigate cost](#investigate-cost)
7. [Save and script results](#save-and-script-results)
8. [Use a multi-turn session](#use-a-multi-turn-session)
9. [Work offline](#work-offline)
10. [Run capabilities individually (middle tier)](#run-capabilities-individually-middle-tier)

---

## Run a workload review

Get a ranked, evidence-cited list of what to fix across jobs, SQL, and warehouses over
public `system.*` data:

```bash
starboard review                                 # default domains: jobs,sql,warehouse
starboard review --domains warehouse,sql         # narrow the scope
starboard review --lookback-days 60              # widen the evidence window
starboard review --validate --min-severity high  # gate + suppress low-signal findings
starboard review --json                          # machine-readable envelope
```

Track how many findings you've resolved between runs:

```bash
starboard review --snapshot-out today.json                 # first run
# ... make fixes ...
starboard review --since today.json                        # report the resolved-rate delta
```

See [Understanding Reports](../user-guide/understanding-reports.md) for how to read the
output.

---

## Ask a question in natural language

Turn a plain-English question into SQL over your workspace's public data:

```bash
starboard genie ask "which warehouses cost the most last month?"
starboard genie ask "how many jobs failed in the last 7 days?" --warehouse-id abc123
starboard genie ask "top 10 tables by size" --json
```

---

## Assess a whole workspace

Run a 30/60/90-day workspace health assessment with graded domain report cards:

```bash
starboard --discover
starboard --discover --lookback-days 90
starboard --discover --discovery-domains jobs warehouse
starboard --discover --data-only                 # skip LLM analysis, raw data only
```

See the [Workspace Discovery workflow](../user-guide/workflows/workspace-discovery.md).

---

## Optimize a slow query

```bash
# By statement ID
starboard --goal "Optimize query with statement_id 01ef-abc123-def456"

# From a .sql file
starboard --goal "Optimize this SQL" --input-file queries/slow_query.sql

# Static review without hitting the API
starboard --mode offline --input-file queries/complex_join.sql \
          --goal "Review this query for anti-patterns"
```

---

## Debug a failing job

```bash
starboard --goal "Why did job 12345 fail in its last run?"
starboard --goal "Analyze performance trends for job 12345"

# Focused cross-domain troubleshooting
starboard --mode diagnostic \
          --goal "Job 12345 fails intermittently — find the root cause"
```

---

## Investigate cost

Cost answers are **list-price DBU estimates** from public usage tables:

```bash
starboard genie ask "what drove the cost increase last month?"
starboard --goal "Break down DBU spend by warehouse over the last 30 days"
starboard review --domains warehouse            # includes cost-based warehouse findings
```

---

## Save and script results

```bash
# Save JSON + Markdown reports to a directory
starboard --goal "Analyze job 12345" --output-path ./reports/
# Writes ./reports/<timestamp>_<goal>.json and ./reports/<timestamp>_<goal>.md

# Emit a structured JSON envelope to stdout for scripting
starboard --goal "Analyze job 12345" --json > result.json
```

The subcommands and middle-tier commands share the JSON envelope
(`{ok, domain, command, data|error, meta}`) with exit codes: `0` ok · `1` auth ·
`2` not-found · `3` api-error · `4` arg-error.

---

## Use a multi-turn session

Reuse a session name to continue a conversation with full context:

```bash
starboard --goal "Analyze query 01ef-abc123" --session my-project
starboard --goal "Would liquid clustering help here?" --session my-project

# Or start an interactive chat
starboard --chat
```

---

## Work offline

`offline` mode disables API-dependent tools. It still analyzes the content you pass with
`--input-file` and gives best-practice guidance:

```bash
starboard --mode offline --input-file query.sql --goal "Review this SQL"
```

---

## Run capabilities individually (middle tier)

For lightweight, per-capability runs, use the `starboard_x` modules (installable via
`pip install starboard-core` plus any extras):

```bash
python -m starboard_x.review score --rows rows.json --domains jobs,sql,warehouse
python -m starboard_x.discovery --help
python -m starboard_x.warehouse --help
```

Available capabilities: `diagnostic`, `discovery`, `review`, `sparklog`, `uc`,
`warehouse`. All emit the shared JSON envelope.

---

## Next Steps

- [CLI Reference](../user-guide/cli.md) — every command, flag, and environment variable
- [Understanding Reports](../user-guide/understanding-reports.md) — read the findings
- [Skills](../SKILLS.md) — run these tasks from Claude Code / Cursor
- [FAQ](./FAQ.md) — quick answers
