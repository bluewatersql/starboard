# Starboard Diagnostic — Reference

Level-3 reference for the `starboard-diagnostic` skill. Loaded on demand.

## CLI surface

`${CLAUDE_SKILL_DIR}/scripts/run.sh` execs `python -m starboard_x.diagnostic`.

| Verb | Required | Optional | Purpose |
|------|----------|----------|---------|
| `triage-exit` | `--exit-code N` | `--context TEXT`, `--text FILE` | Rank exit-code hypotheses |
| `extract-evidence` | `--text FILE` | — | Extract evidence windows from a log |
| `rca` | `--text FILE` | `--exit-code N` | Triage + evidence + synthesis |

Every invocation prints the stable envelope to stdout:

```json
{"ok": true, "domain": "diagnostic", "command": "...",
 "data": {...}, "error": null,
 "meta": {"format": "json", "contract_version": "1.0"}}
```

## Process exit codes (Phase-0 contract)

| Code | Meaning | Typical cause |
|------|---------|---------------|
| 0 | ok | success |
| 1 | auth | could not authenticate / build a client |
| 2 | not-found | requested resource does not exist |
| 3 | api-error | Databricks API / unexpected runtime error |
| 4 | arg-error | bad CLI arguments or a missing `--text` file |

## Exit-code hypotheses (`triage-exit`)

Unix signal exit codes are decoded as `128 + N`:

| Exit code | Signal | Default hypothesis |
|-----------|--------|--------------------|
| 137 | SIGKILL (9) | `oom` (often OOM-killed; also container limit) |
| 143 | SIGTERM (15) | `cancellation` (graceful termination) |
| 139 | SIGSEGV (11) | `crash` (segfault) |
| 134 | SIGABRT (6) | `crash` (abort) |

Hypothesis types: `oom`, `cancellation`, `container_limit`, `crash`, `unknown`.
Each hypothesis carries a `confidence` (0.0–1.0), `supporting_evidence`,
`contradicting_evidence`, and `next_steps`. Passing `--context`/`--text` lets
proof signals in the log (e.g. `OOMKilled`, `OutOfMemoryError`, `cancelled`)
boost or contradict a hypothesis.

## Evidence-window types (`extract-evidence`)

Each window has a stable `window_id` (`ev_<hash>`) for citation, a
`line_start`/`line_end` range, verbatim `content`, and a `confidence`:

| Type | Matches |
|------|---------|
| `fatal_exception` | `Exception`/`Error`/`Failure`, `java.lang.*Exception/*Error` |
| `cause_chain` | `Caused by:` chains |
| `exit_code` | `exited with code N` |
| `oom` | `OutOfMemoryError`, `OOMKilled`, `oom-killer` |
| `spark_error` | `SparkException`, `FetchFailedException`, `ExecutorLostFailure` |
| `sql_error` | `AnalysisException`, `TABLE_OR_VIEW_NOT_FOUND`, `PERMISSION_DENIED` |
| `error_message` | `[ERROR]`, `ERROR:` |
| `warning` | `[WARN]` |

## `rca` payload

```
data.triage      -> triage-exit result (null when --exit-code omitted)
data.evidence    -> extract-evidence result (windows + summary)
data.synthesis   -> {primary_symptom, root_causes[], confidence,
                     evidence_chain[], recommended_actions[]}
```

The stdlib-only tier has no pattern registry (that lives behind the
`starboard-core[diagnostics]` extra / the Tier-2 agent), so `synthesis` reflects
exit-code + evidence signals only; pattern-aware synthesis needs a higher tier.
