---
name: starboard-diagnostic
description: 'Diagnose Databricks failures — triage exit codes, extract evidence from error logs, and synthesize a root cause. Use when the user mentions a job or query failure, an exit code, OOM, a stack trace, or asks "why did this fail". Triggers: error, failure, exit code 137/143, OOMKilled, stack trace, root cause.'
compatibility: opencode
metadata:
  source: packages/starboard-skills/skills/starboard/starboard-diagnostic/SKILL.md
---

# Starboard: Diagnostic Analysis

Diagnose Databricks job/query failures: decode exit codes into ranked hypotheses,
extract verbatim evidence windows from error logs, and synthesize a root cause.

> **Routing.** For a workspace health read (proactive, weekly, monthly or QBR) use
> [`starboard-health-review`](../starboard-health-review/SKILL.md); to troubleshoot one job, run,
> query or pipeline as a focused case use [`starboard-troubleshoot`](../starboard-troubleshoot/SKILL.md).
> Each is its own run (one task per run).

## You are the analyst

**You** are the LLM for this skill. The skill hands you deterministic failure
data; **you** read the hypotheses and evidence windows and write the root-cause
assessment and remediation yourself.

Do **not** call the `starboard` goal agent, an MCP `*_analysis` / `synthesize_*`
tool, a model-serving endpoint, or any other model. There is no second LLM in
this loop — the data step below runs pure Python (no LLM), and you do the
reasoning. Handing analysis to another model defeats the point of the skill and
breaks when that model's credentials differ from your session's.

## Step 1 — Confirm inputs and set up the run

Before loading data, confirm the failure context with the user — but **only ask
for what they haven't already given**. If their request already specifies a value
(e.g. "exit code 137 from run 98765"), use it and skip that question. If they
have no additional context, proceed with what you have.

Ask for (as applicable):

- **Failing run / job ID** — the run ID or job ID of the failed execution, if
  known.
- **Exit code** — the numeric exit code reported by the executor, if available.
- **Error log path** — path to an error log or stack trace file on disk, if
  available (passed via `--text <file>` to the helper).

### Set up the run (before any workspace read)

Do this first, before the first workspace read: identity is verified before any row, log or code is
acquired, so it cannot wait for the save step. Inside an engagement run, beat 0 already did it: use
that run's `$RUN_FOLDER` (or `<run-dir>`) and skip to Step 2. Otherwise set the run up with the
helper (never build a run dir or a Drive folder by hand):

```bash
starboard-helper engagement preflight --task <task> --task-name <case> \
  --account-key <account_key> --account-name "<account name>" --source-mode customer_workspace
starboard-helper engagement verify-identity --run-id <run_id> --profile <profile> \
  --expected-workspace-id <workspace_id>
starboard-helper engagement route --run-id <run_id>
```

Use `--task troubleshooting --task-name <kind>-<id>` (e.g. `job-123`, `query-01ef…`,
`cluster-0612-…`) for a report about one job, query, cluster or pipeline, and `--task review
--task-name ws-<workspace_id>` for a workspace-wide report. Keep preflight's `run_id`. Always pass
`--profile <name>` with the profile the user chose. `verify-identity` proves that profile reaches
the workspace you analyze: take `<workspace_id>` from the user or the workspace, never from a
profile name. A mismatch exits non-zero and quarantines the run: stop, show `error` and read
nothing.

Act on preflight's `storage_decision`:
- **`drive_required`** (an install with the internal overlay; a covered run), **`drive_default`**
  (an internal-only install) or **`drive_optional`** (a public install where the operator chose
  `--storage drive`): a Drive run. Route returns
  `run_folder_id` (`$RUN_FOLDER`) and **nothing is written locally**. Save a large fetch into the
  run with `--run-folder $RUN_FOLDER --out raw/<name>.json` (a local `--out` path is refused with
  `LOCAL_STORAGE_REFUSED`) and read it back with
  `starboard-helper engagement read --run-folder $RUN_FOLDER --path raw/<name>.json`. After the
  Step 2 fetches, record them with
  `starboard-helper engagement commit --run-folder $RUN_FOLDER --stage capture`.
- **`local`** (a public install without `--storage drive`) or **`internal_only_local`**:
  `data.local_run_dir` is `<run-dir>`;
  route writes `<run-dir>/analysis/run-authorization.json`, and `--out` paths are local.

A refusal exits 2 with `LOCAL_STORAGE_REFUSED` or `STORAGE_UNAVAILABLE`: the `engagement` envelope carries it as `errors[0].code` (show `errors[0].message` verbatim), any other helper starts its top-level `error` with it (show `error` verbatim). Stop. A preflight `STORAGE_UNAVAILABLE` returns `run_id: null` and creates nothing: re-run the same preflight once the storage adapter is installed (a local run never needs it). Analyzing a local log or exit code reads no workspace; the setup is for the raw-fetch fallback below and for saving. Setup writes no report; the report is written only if the user
opts in (see the save step).

## Step 2 — Load the data (deterministic Python, no LLM)

Run the bundled helper. It executes dep-light analyzers out-of-context in Python
and prints a single JSON envelope to stdout. The **portable** engine invocation
runs on any host (Claude Code, Codex, OpenCode, `databricks aitools`):

- **Exit code:**  `python -m starboard_x.diagnostic triage-exit --exit-code <N>`
  (add `--context "<log text>"` or `--text <file>` to sharpen the hypothesis)
- **Error log:**  `python -m starboard_x.diagnostic extract-evidence --text <file>`
- **End-to-end:** `python -m starboard_x.diagnostic rca --text <file> [--exit-code <N>]`

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
starboard-helper diagnostic run-state --profile <profile> --run-id <RUN_ID>
starboard-helper diagnostic cluster-log --profile <profile> --cluster-id <CLUSTER_ID> --limit 100
```

### Workspace evidence (after setup)

Read the failure itself before you diagnose it. Every read is identity-scrubbed: user names are
dropped and emails show as `<email>`. Save each into the run with
`--run-folder $RUN_FOLDER --out raw/<name>.json` (e.g. `raw/job-run-output-<RUN_ID>.json`):

```bash
starboard-helper job run-output --profile <profile> --run-id <RUN_ID> --task-key <TASK_KEY>
starboard-helper job code --profile <profile> --job-id <JOB_ID> --task-key <TASK_KEY>
starboard-helper query fetch --profile <profile> --query-id <QUERY_ID>
starboard-helper diagnostic driver-log --profile <profile> --cluster-id <CLUSTER_ID> --stream log4j --tail-bytes 200000
```

- `job run-output`: on a multi-task run, omit `--task-key` first; it exits 4 and lists the keys.
  Feed the error text to `extract-evidence` / `rca` above.
- `job code`: exits 2 with `errors[0].code` `CODE_NOT_IN_WORKSPACE` for a Git or remote source; say so.
- `diagnostic driver-log` reads delivered cluster logs (Volumes or DBFS). It exits 2 with
  `cluster_log_delivery_off` when the cluster has no log delivery, or
  `cluster_log_destination_unsupported` for another store: name that gap, don't guess.

Files the user exported (Drive `drive:<id>`, or a local file on a public install; an overlay
install refuses a local file, exit 2):

```bash
python -m starboard_x.diagnostic profile --input drive:<file_id>
python -m starboard_x.sparklog parse --input drive:<file_id>
```

`profile` summarizes a query-profile JSON (top operators, spill, scans); `sparklog parse`
summarizes a Spark event log (add `--full` for the whole application). To compare two saved
documents, e.g. a job's settings before and after it started failing, or two query fetches:

```bash
python -m starboard_x.diff settings --a raw/job-<id>-before.json --b raw/job-<id>-after.json --run-folder $RUN_FOLDER
python -m starboard_x.diff metrics --a raw/query-<id>-a.json --b raw/query-<id>-b.json --run-folder $RUN_FOLDER
```

`settings` lists the paths added, removed and changed; `metrics` gives each numeric delta and its
unit. Without `--run-folder`, `--a` / `--b` are `drive:<id>` or local files.

### Inside an engagement run: record a case

When the diagnosis belongs to an engagement run folder (a `troubleshooting` run), record the
question and the evidence as a case
(see [`starboard-engagement`](../starboard-engagement/SKILL.md) **Cases**):

```bash
starboard-helper engagement case open --run-folder $RUN_FOLDER --clue job:<JOB_ID> --question "<why did it fail?>"
starboard-helper engagement case revise --run-folder $RUN_FOLDER --case-id <case_id> --evidence raw/job-run-output-<RUN_ID>.json --hypothesis "<statement>" --hypothesis-status supported
starboard-helper engagement action propose --run-folder $RUN_FOLDER --case-id <case_id> --next-step "<the change>" --owner-role <role> --verify-method "<how the outcome is checked>"
```

Use `--finding-id <finding_id>` in place of `--clue` when the question is about a health finding.
Once the cause is recorded, `action propose` records the next step as a `pending` action on the
case's finding; only the operator accepts or executes it.

## Step 3 — Analyze the data yourself

Read the returned hypotheses and evidence windows:

- **Exit code** — match the code to ranked hypotheses; note confidence and any
  discriminating signals in the log context.
- **Evidence windows** — locate the fatal exception and cause chain; check for
  OOM patterns (GC overhead, container killed, executor lost).
- **Cross-signals** — correlate the exit-code hypothesis with evidence window
  types to narrow to a primary root cause.

## Step 4 — Produce the diagnostic report

1. **Overall assessment** — one sentence on the likely root cause
2. **Primary hypothesis** — cause, confidence level, supporting evidence (cite
   window IDs)
3. **Evidence summary** — verbatim key lines with citation IDs
4. **Prioritized remediation** — specific steps ordered by likelihood of resolving
   the failure

`$` figures are **list-price DBU estimates** — label them as such.

### Offer to save the report

After presenting the findings, **offer** to save them as a Markdown report:

> "Want me to save this as a report? I'll write it to `analysis/diagnostic.md` in this run (its
> Drive run folder, or its run dir under `./starboard-reports/`)."

If the user accepts, write the report to `analysis/diagnostic.md` in the run; set it up now if an offline analysis skipped it and add a
`README.md` index with a one-line pointer to the report. Confirm where you wrote it. Don't write
anything unless the user opts in. Inside an engagement run the engagement's deliver beat publishes
it; skip the rest of this step.

- **Local run** (`local` / `internal_only_local`): write `<run-dir>/analysis/diagnostic.md` and
  `<run-dir>/README.md`. There is no Drive leg.
- **Drive run** (`drive_required` / `drive_default` / `drive_optional`): nothing is written
  locally. Put both files into the run
  folder with `engagement put` (the bytes come on stdin; an identical re-put is a no-op), then
  record them and check the run:

  ```bash
  starboard-helper engagement put --run-folder $RUN_FOLDER --path analysis/diagnostic.md <<'EOF'
  <the report Markdown>
  EOF
  starboard-helper engagement put --run-folder $RUN_FOLDER --path README.md <<'EOF'
  <the README index, with a one-line pointer to analysis/diagnostic.md>
  EOF
  starboard-helper engagement commit --run-folder $RUN_FOLDER --stage analysis
  starboard-helper engagement status --run-folder $RUN_FOLDER
  ```

  Share route's `run_link` and repeat any `fallback_warning` (the chosen folder wasn't writable,
  so the run went to the `My Drive` account route). The report is not delivered anywhere else
  until it goes through the engagement's report → approve → deliver | receipt chain
  ([`starboard-deliver`](../starboard-deliver/SKILL.md)); only a verified receipt counts as
  delivered. If the folder's sharing changed since route, the helper stops with `blocked_access`:
  restore the folder's previous sharing and re-run, or start a new run with preflight.

## Exit codes (from the bundled helper)

- `0` success
- `1` authentication error — check `DATABRICKS_HOST` / `DATABRICKS_TOKEN`
- `2` resource not found — verify the run ID or cluster ID
- `3` API error — check workspace connectivity
- `4` argument error — bad flags or a missing `--text` file
- `7` on a `--run-folder` run whose `error` starts with `BLOCKED_ACCESS`, `STORAGE_INTEGRITY`, `NOT_FOUND`
  or `STORAGE_ERROR`: a storage / integrity / access failure — stop and report `error` verbatim
