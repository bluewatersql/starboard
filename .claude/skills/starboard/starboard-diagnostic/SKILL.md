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

## You are the analyst

**You** are the LLM for this skill. The skill hands you deterministic failure
data; **you** read the hypotheses and evidence windows and write the root-cause
assessment and remediation yourself.

Do **not** call the `starboard` goal agent, an MCP `*_analysis` / `synthesize_*`
tool, a model-serving endpoint, or any other model. There is no second LLM in
this loop — the data step below runs pure Python (no LLM), and you do the
reasoning. Handing analysis to another model defeats the point of the skill and
breaks when that model's credentials differ from your session's.

## Step 1 — Load the data (deterministic Python, no LLM)

Run the bundled helper. It executes dep-light analyzers out-of-context in Python
and prints a single JSON envelope to stdout. The commands are pre-approved by this
skill's `allowed-tools`, so they run without a permission prompt:

- **Exit code:**  `${CLAUDE_SKILL_DIR}/scripts/run.sh triage-exit --exit-code <N>`
  (add `--context "<log text>"` or `--text <file>` to sharpen the hypothesis)
- **Error log:**  `${CLAUDE_SKILL_DIR}/scripts/run.sh extract-evidence --text <file>`
- **End-to-end:** `${CLAUDE_SKILL_DIR}/scripts/run.sh rca --text <file> [--exit-code <N>]`

### What comes back

The envelope is `{ok, domain, command, data|error, meta}`:

- `triage-exit` → `data.hypotheses` — ranked failure causes (OOM, cancellation,
  container limit, crash) with confidence and next steps.
- `extract-evidence` / `rca` → `data.evidence_windows` — fatal exception, cause
  chain, and OOM windows with stable citation IDs; `data.assessment` when `rca`
  is used.

For the exit-code table and evidence-window types, see [reference.md](reference.md).
For sample invocations and expected JSON, see [examples.md](examples.md).

### Fallback — raw fetch

If the bundled helper is unavailable, fetch failure context with `starboard-helper`
and reason over what it returns:

```bash
starboard-helper diagnostic run-state --run-id <RUN_ID>
starboard-helper diagnostic cluster-log --cluster-id <CLUSTER_ID> --limit 100
```

## Step 2 — Analyze the data yourself

Read the returned hypotheses and evidence windows:

- **Exit code** — match the code to ranked hypotheses; note confidence and any
  discriminating signals in the log context.
- **Evidence windows** — locate the fatal exception and cause chain; check for
  OOM patterns (GC overhead, container killed, executor lost).
- **Cross-signals** — correlate the exit-code hypothesis with evidence window
  types to narrow to a primary root cause.

## Step 3 — Produce the diagnostic report

1. **Overall assessment** — one sentence on the likely root cause
2. **Primary hypothesis** — cause, confidence level, supporting evidence (cite
   window IDs)
3. **Evidence summary** — verbatim key lines with citation IDs
4. **Prioritized remediation** — specific steps ordered by likelihood of resolving
   the failure

`$` figures are **list-price DBU estimates** — label them as such.

## Exit codes (from the bundled helper)

- `0` success
- `1` authentication error — check `DATABRICKS_HOST` / `DATABRICKS_TOKEN`
- `2` resource not found — verify the run ID or cluster ID
- `3` API error — check workspace connectivity
- `4` argument error — bad flags or a missing `--text` file
