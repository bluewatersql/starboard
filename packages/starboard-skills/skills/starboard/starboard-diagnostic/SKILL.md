---
name: starboard-diagnostic
description: >
  Diagnose Databricks failures — triage exit codes, extract evidence from error
  logs, and synthesize a root cause. Use when the user mentions a job or query
  failure, an exit code, OOM, a stack trace, or asks "why did this fail".
  Triggers: error, failure, exit code 137/143, OOMKilled, stack trace, root cause.
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/run.sh *), Bash(starboard-helper:*), Read
---

# Starboard: Diagnostic Analysis

Diagnose Databricks job/query failures: decode exit codes into ranked hypotheses,
extract verbatim evidence windows from error logs, and synthesize a root cause.

## Path selection (three branches)

Pick the highest tier available in your context, then stop:

1. **Tier 2 — MCP agent.** If `mcp__starboard__diagnostic_agent` is available,
   call it. The full server stack handles orchestration, analysis, and
   recommendations; return its response directly.
2. **Tier 1 — bundled helper (this skill's default).** Else, if
   `${CLAUDE_SKILL_DIR}/scripts/run.sh` exists, use it (see below). The dep-light
   analyzers run out-of-context in Python and emit compact JSON to stdout.
3. **Tier 0 — raw fetch.** Else, fall back to `starboard-helper` to fetch failure
   context, then reason over it yourself:
   ```bash
   starboard-helper diagnostic run-state --run-id <RUN_ID>
   starboard-helper diagnostic cluster-log --cluster-id <CLUSTER_ID> --limit 100
   ```

## Tier-1 usage

All commands emit the stable JSON envelope
(`{ok, domain, command, data|error, meta}`) to stdout. Run them via the bundled
script — it is pre-approved, so no permission prompt appears:

- **Exit code:**   `${CLAUDE_SKILL_DIR}/scripts/run.sh triage-exit --exit-code <N>`
  (add `--context "<log text>"` or `--text <file>` to sharpen the hypothesis)
- **Error log:**   `${CLAUDE_SKILL_DIR}/scripts/run.sh extract-evidence --text <file>`
- **End-to-end:**  `${CLAUDE_SKILL_DIR}/scripts/run.sh rca --text <file> [--exit-code <N>]`

### Workflow

1. If the failure has an exit code, start with `triage-exit` to get ranked
   hypotheses (OOM, cancellation, container limit, crash) with next steps.
2. If you have an error log or stack trace on disk, run `extract-evidence` (or go
   straight to `rca`) to pull the fatal exception, cause chain, and OOM windows
   with stable citation IDs.
3. Read the JSON and produce a report: overall assessment, the primary hypothesis
   with confidence, supporting evidence (cite window IDs), and prioritized
   remediation steps.

For the exit-code table and evidence-window types, see [reference.md](reference.md).
For sample invocations and expected JSON, see [examples.md](examples.md).

## Exit codes (all tiers)

- `0` success
- `1` authentication error — check `DATABRICKS_HOST` / `DATABRICKS_TOKEN`
- `2` resource not found — verify the run ID or cluster ID
- `3` API error — check workspace connectivity
- `4` argument error — bad flags or a missing `--text` file
