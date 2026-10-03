---
description: One-shot Databricks workspace triage — surveys jobs, warehouses, and recent failures, then reports health and prioritized fixes.
allowed-tools: Bash(starboard-helper:*), Read
---

# Starboard Triage

Triage the Databricks workspace for the user's request: $ARGUMENTS

Use the `starboard-helper` CLI (JSON to stdout; exit codes `0` ok · `1` auth · `2` not-found ·
`3` api-error · `4` arg-error). Never guess metrics — always call the CLI.

Steps:

1. Survey the fleet:
   ```bash
   starboard-helper job list --limit 100
   starboard-helper warehouse list
   ```
2. For any failing or suspicious job run, pull its state:
   ```bash
   starboard-helper diagnostic run-state --run-id <RUN_ID>
   ```
3. Summarize: overall health, the specific failures and their likely root causes, and a
   prioritized list of recommendations (critical / high / medium / low).

If richer analysis is needed, defer to the domain skills (`starboard-diagnostic`,
`starboard-finops`, `starboard-query`, …), which apply the same CLI-helper path.
