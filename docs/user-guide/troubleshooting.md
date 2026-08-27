---
title: User Troubleshooting Guide
description: Symptom-based troubleshooting for common issues when using Starboard.
last_reviewed: 2026-03-24
status: current
---

# Troubleshooting

> **Docs** > **User Guide** > **Troubleshooting**
> Reading time: 10 minutes

## What You'll Learn

- How to diagnose and fix common connection, agent, and report issues
- What each error message means and how to resolve it
- When and how to escalate to your administrator

---

## Install & Auth Issues

### `starboard: command not found`

**Symptom:** The shell can't find the `starboard` command after install.

**Cause:** The package isn't installed in the active environment, or the environment's
`bin` directory isn't on your `PATH`.

**Solution:**

1. Install into the current environment: `pip install starboard`.
2. Confirm it's available: `starboard --help`.
3. If you use a virtualenv, make sure it is activated in the shell you're running from.

---

### No Databricks auth resolved

**Symptom:** Starboard reports it cannot resolve Databricks credentials.

**Cause:** Starboard delegates to the Databricks SDK credential chain ("auth by
subtraction") and found no usable credentials.

**Solution:**

1. Run a guided login, or check what's currently resolved:
   ```bash
   starboard auth login --host https://your-workspace.cloud.databricks.com --profile my-ws
   starboard auth status          # prints host / auth_type / profile / user — never a token
   ```
2. Or provide credentials one of these ways:
   - A `~/.databrickscfg` profile: `--profile <name>` or `DATABRICKS_CONFIG_PROFILE`
   - Host + token: `DATABRICKS_HOST` + `DATABRICKS_TOKEN` (or `--host` / `--token`)
   - OAuth service principal: `DATABRICKS_CLIENT_ID` + `DATABRICKS_CLIENT_SECRET`

---

### Authentication failure (401 or 403)

**Symptom:** The agent responds with "permission denied" or "authentication failed" when trying to access Databricks resources.

**Cause:** Your Databricks credentials are expired or lack the required permissions.

**Solution:**

1. Verify the resolved identity:
   ```bash
   starboard auth status
   ```
2. If a token is expired, generate a new one from **Databricks Workspace** > **User Settings** > **Developer** > **Access tokens**, or re-run `starboard auth login`.
3. Ensure the identity has access to the resources you are analyzing (jobs, clusters, warehouses, Unity Catalog, and the public `system.*` tables used by `review` / `--discover`).

---

### LLM API key error

**Symptom:** Starboard fails to start or returns errors about missing API keys.

**Cause:** The `LLM_API_KEY` environment variable is not set or is invalid.

**Solution:**

1. Verify the key is set:
   ```bash
   echo $LLM_API_KEY
   ```
2. Confirm the key is valid by testing it with your LLM provider.
3. If using a `.env` file, ensure it is in the project root and contains:
   ```
   LLM_API_KEY=sk-your-key-here
   ```

---

## Agent Issues

### Wrong agent selected

**Symptom:** You asked about a query but the Job Agent answered, or you asked about costs but the Query Agent answered.

**Cause:** The Intent Router misclassified your request. This can happen when the question is ambiguous or uses terminology that spans multiple domains.

**Solution:**

1. Be more specific in your request. Include domain-specific keywords:
   - For queries: mention "query", "SQL", "statement ID", or "execution plan"
   - For jobs: mention "job", "job ID", "run", or "task"
   - For costs: mention "cost", "spend", "billing", "chargeback", or "budget"
   - For clusters: mention "cluster", "node", "worker", or "autoscaling"
   - For warehouses: mention "warehouse", "SQL warehouse", or "SLO"
   - For Unity Catalog: mention "table", "catalog", "schema", "lineage", or "governance"
   - For discovery: mention "workspace health", "health check", or "discovery"

2. If the wrong agent answered, simply clarify in a follow-up message:
   ```
   I was asking about the SQL query, not the job. Please analyze
   statement ID 01ef-abc123-def456.
   ```

---

### Agent not responding

**Symptom:** The agent appears to be thinking indefinitely with no tool calls or progress.

**Cause:** The agent may be waiting for an LLM response, or the LLM provider is experiencing high latency.

**Solution:**

1. Wait up to 2 minutes. Complex analyses can take time, especially on the first tool call.
2. Re-run with debug logging to see where it's stuck (and any rate-limit / HTTP 429 errors from the LLM provider):
   ```bash
   starboard --debug --goal "Your question"
   ```
3. If the issue persists, try again. Transient LLM provider issues usually resolve quickly.

---

### Agent timeout

**Symptom:** The response is cut short with a message about exceeding the token budget or step limit.

**Cause:** The analysis was too complex for the configured budget. The agent ran out of tokens or reached the maximum number of reasoning steps.

**Solution:**

1. Simplify your request. Instead of "analyze everything about job 12345," try "why did job 12345 fail in the last run?"
2. If using the CLI, increase the token budget:
   ```bash
   starboard --goal "Your question" --llm-max-tokens 150000
   ```
3. Break complex questions into multiple turns:
   ```
   Turn 1: "Analyze the cluster configuration for job 12345"
   Turn 2: "Now check the source code for anti-patterns"
   Turn 3: "What about the table partitioning strategy?"
   ```

---

### Agent asks too many clarifying questions

**Symptom:** The agent keeps asking for more information instead of proceeding with analysis.

**Cause:** Your request may be too vague, or the agent cannot find the resource you referenced.

**Solution:**

1. Provide specific identifiers in your initial request:
   - Job ID: `"Analyze job 12345"`
   - Statement ID: `"Optimize query 01ef-abc123-def456"`
   - Cluster ID: `"Check cluster 0123-456789-abcdef"`
2. Include the problem description: `"Job 12345 is failing with OOM errors"`
3. If the agent asks for a resource that does not exist, double-check the ID and permissions.

---

## Query Issues

### Statement ID not found

**Symptom:** The agent reports "statement not found" or "unable to resolve query."

**Cause:** The statement ID is invalid, expired, or from a different workspace.

**Solution:**

1. Verify the statement ID format. Databricks statement IDs look like `01ef-abc123-def456-7890`.
2. Confirm you are connected to the correct workspace (`DATABRICKS_HOST`).
3. Check that the query was run recently. Statement history has a retention period (typically 30 days in Databricks).
4. Try pasting the SQL directly instead of using a statement ID.

---

### Permission denied on tables

**Symptom:** The agent cannot read table metadata or schemas.

**Cause:** Your Databricks token does not have access to the referenced tables in Unity Catalog.

**Solution:**

1. Verify you have `SELECT` permission on the table:
   ```sql
   SHOW GRANTS ON TABLE catalog.schema.table_name
   ```
2. Ask your workspace administrator to grant the necessary permissions.
3. If using a service principal token, ensure it has been granted access to the required catalogs and schemas.

---

## Report Issues

### Incomplete report

**Symptom:** The report is missing sections or ends abruptly.

**Cause:** The agent ran out of tokens or encountered an error during analysis.

**Solution:**

1. Check the response for error messages at the end of the report.
2. Ask the agent to continue: `"Please complete the analysis you started."`
3. Increase the token budget if using the CLI (`--llm-max-tokens`).
4. If a specific tool failed, the agent may have skipped that section. Ask directly: `"Can you retry the cluster analysis?"`

---

### Recommendations seem generic

**Symptom:** The report gives advice that could apply to any workload, without specific details from your environment.

**Cause:** The agent may not have been able to access live data (offline mode), or the resource was not found.

**Solution:**

1. Confirm you are not in offline mode (`--mode offline` disables API-dependent tools). Use `--mode online` (the default) for live data.
2. Provide specific resource identifiers (job IDs, statement IDs, cluster IDs) so the agent can pull real data.
3. Check the "Tools Used" section of the report. If no tools were called, the agent likely could not connect to Databricks — verify with `starboard auth status`.

---

### Numbers look wrong

**Symptom:** Cost figures, row counts, or durations in the report do not match what you see in Databricks.

**Cause:** The agent queries system tables which may have a slight delay in data availability. Some metrics are approximate.

**Solution:**

1. Check the time range. The agent uses a default lookback window (often 30 days). Specify your preferred range: `"Show costs for the last 7 days only."`
2. System table data can lag by up to 24 hours in some Databricks configurations.
3. Remember that all `$` figures are **list-price DBU estimates**, not finance-grade billing numbers. For critical financial decisions, cross-reference with the Databricks billing console.

---

## Performance Issues

### Slow responses

**Symptom:** The agent takes more than 2 minutes for a simple question.

**Cause:** High latency from the LLM provider, large conversation history, or slow Databricks API responses.

**Solution:**

1. Start a new conversation. Long conversations accumulate context that increases response time.
2. Check LLM provider status for outages or degraded performance.
3. Try a simpler model if available (e.g., `gpt-4o-mini` for quick questions).

---

### Garbled or unreadable terminal output

**Symptom:** The output shows raw escape codes, or Rich formatting doesn't render well in your terminal or when piping to a file.

**Cause:** Some terminals and pipelines don't handle ANSI color / Rich formatting.

**Solution:**

1. Use plain text: `starboard --plain --goal "..."`.
2. Disable color: `starboard --no-color --goal "..."` (also respects the `NO_COLOR` env var).
3. For scripting, use `--json` to emit a structured envelope instead of formatted text.

---

## When to Contact Support

Escalate to your Starboard administrator if:

- `starboard auth status` succeeds but analyses consistently fail with permission errors
- The same analysis works for other users but not for you (possible permissions issue)
- Cost figures are consistently wrong after checking time ranges and data lag
- The agent repeatedly fails on the same request with no clear error message

**Information to provide:**

- The exact command or prompt you ran
- The error message (if any) — re-run with `--debug` to capture more detail
- The session name if you used `--session`
- The time the error occurred
- Your Databricks workspace URL

---

## Quick Reference: Error Messages

| Error Message | Likely Cause | Quick Fix |
|--------------|-------------|-----------|
| "No Databricks auth resolved" | No usable credentials | `starboard auth login` or set `DATABRICKS_HOST`/`DATABRICKS_TOKEN` |
| "LLM_API_KEY not set" | Missing LLM key | `export LLM_API_KEY="..."` |
| "Authentication failed" | Invalid or expired credentials | `starboard auth status`, then re-login |
| "Statement not found" | Invalid or expired statement ID | Verify the ID and workspace |
| "Permission denied" | Insufficient Databricks permissions | Request access from admin |
| "Token budget exhausted" | Analysis too complex | Simplify the question or raise `--llm-max-tokens` |
| "Rate limit exceeded" | Too many LLM API calls | Wait and retry |
| `pip install 'starboard[...]'` error | A chosen backend needs an extra | Install the named extra |

---

## Next Steps

- [CLI Reference](cli.md) -- Command-line options and flags
- [Interruptible Reasoning](interruptible-reasoning.md) -- Guide agents mid-analysis
- [Understanding Reports](understanding-reports.md) -- Interpret agent output
