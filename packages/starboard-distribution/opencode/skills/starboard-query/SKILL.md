---
name: starboard-query
description: Analyze Databricks SQL query performance — fetch query history, find slow or failed queries, diagnose, and recommend optimizations. Use when the user asks about query performance, slow queries, warehouse query load, or SQL failures.
compatibility: opencode
metadata:
  source: packages/starboard-skills/skills/starboard/starboard-query/SKILL.md
---

# Starboard: Query Analysis

Analyze Databricks SQL queries — fetch query history, identify slow queries,
diagnose failures, and recommend optimizations.

## You are the analyst

**You** are the LLM for this skill. The skill hands you deterministic query
history data; **you** read the rows and write the performance assessment and
recommendations yourself.

Do **not** call the `starboard` goal agent, an MCP `*_analysis` / `synthesize_*`
tool, a model-serving endpoint, or any other model. There is no second LLM in
this loop — the data step below uses plain CLI fetches (no LLM), and you do the
reasoning. Handing analysis to another model defeats the point of the skill and
breaks when that model's credentials differ from your session's.

## Step 1 — Confirm inputs

Before loading data, confirm the run parameters with the user — but **only ask
for what they haven't already given**. If their request already specifies a value
(e.g. "slow queries over 30 s"), use it and skip that question. If they say
"just go" / "use defaults", proceed with the defaults.

Ask for (with defaults):

- **History lookback window** — how many recent queries to inspect (default:
  **25 most recent**).
- **Slow-query duration threshold** — minimum execution time to flag as slow
  (default: **10 000 ms**).
- **Workspace / profile** — which `--profile` to target, if it's ambiguous
  (default: the ambient `DATABRICKS_*` env / default profile).

## Step 2 — Load the data (deterministic, no LLM)

Use `starboard-helper` to fetch query history. The commands are pre-approved by
this skill's `allowed-tools`, so they run without a permission prompt:

```bash
# For a specific query:
starboard-helper query fetch --query-id <QUERY_ID>

# For recent history on a warehouse:
starboard-helper query history --warehouse-id <WH_ID> --limit 25

# For slow queries:
starboard-helper query slow --min-duration-ms 10000 --limit 25
```

## Step 3 — Analyze the data yourself

Read the returned query records:

- **Duration** — is query duration above expected thresholds for query complexity?
- **Failures** — what error messages are present? Are they permission, syntax, or
  resource errors?
- **Patterns** — do slow queries share common tables, joins, or filter patterns?
- **Warehouse** — is the warehouse appropriately sized for the query workload?

## Step 4 — Produce the report

1. Summary of query health / performance
2. Root cause(s) of slowness or failures
3. Specific SQL optimization recommendations (indexes, partitioning, rewrite
   suggestions)
4. Warehouse sizing recommendations if applicable
5. Priority: critical / high / medium / low

### Offer to save the report

After presenting the findings, **offer** to save them as a Markdown report:

> "Want me to save this as a report? I'll write it to
> `./starboard-reports/query-<YYYY-MM-DD>.md`."

If the user accepts, create the `./starboard-reports/` directory if needed and
write the full report there (use today's date; if a file for today already
exists, add a `-2`, `-3`, … suffix). Confirm the path you wrote. Don't write
anything unless the user opts in.

## Exit codes

- 0: success
- 1: authentication error — check `DATABRICKS_HOST` and `DATABRICKS_TOKEN`
- 2: query not found — verify query ID
- 3: API error — check workspace connectivity
