---
name: starboard-job
description: "Analyze Databricks jobs and workflows — fetch configuration, inspect run history, diagnose failures, and recommend optimizations. Use when the user asks about job failures, job or workflow performance, run history, or job scheduling."
allowed-tools: Bash(starboard-helper:*), Read, Write
---

# Starboard: Job Analysis

Analyze Databricks jobs — fetch configuration, inspect run history, diagnose
failures, and recommend optimizations.

> **Routing.** For a workspace health read (proactive, weekly, monthly or QBR) use
> [`starboard-health-review`](../starboard-health-review/SKILL.md); to troubleshoot one job, run,
> query or pipeline as a focused case use [`starboard-troubleshoot`](../starboard-troubleshoot/SKILL.md).
> Each is its own run (one task per run).

## You are the analyst

**You** are the LLM for this skill. The skill hands you deterministic job
configuration and run data; **you** read the history and write the health
assessment and recommendations yourself.

Do **not** call the `starboard` goal agent, an MCP `*_analysis` / `synthesize_*`
tool, a model-serving endpoint, or any other model. There is no second LLM in
this loop — the data step below uses plain CLI fetches (no LLM), and you do the
reasoning. Handing analysis to another model defeats the point of the skill and
breaks when that model's credentials differ from your session's.

## Step 1 — Confirm inputs and set up the run

Before loading data, confirm the run parameters with the user — but **only ask
for what they haven't already given**. If their request already specifies a value
(e.g. "analyze job 12345"), use it and skip that question. If they say
"just go" / "use defaults", proceed with the defaults.

Ask for (with defaults):

- **Which job(s)** — a specific job ID / name filter, or analyze all jobs?
  Default: **all jobs**.
- **Run-history lookback** — how many recent runs to inspect per job (default:
  **10**).
- **Workspace / profile** — which `--profile <name>` to use. Ask the user which profile
  reaches the workspace; never pick one yourself.

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
--task-name ws-<workspace_id>` for a workspace-wide report. To troubleshoot a failing job before
you know which one, run `--task troubleshooting --task-name jobs-<workspace_id>`, find the job
inside the run (`job list` / `job runs` saved with `--run-folder $RUN_FOLDER --out raw/<name>.json`),
then open the case on the job you found (`--clue job:<job_id>`), never on the workspace
([`starboard-troubleshoot`](../starboard-troubleshoot/SKILL.md) owns the case flow). Keep
preflight's `run_id`. Always pass
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

A refusal exits 2 with `LOCAL_STORAGE_REFUSED` or `STORAGE_UNAVAILABLE`: the `engagement` envelope carries it as `errors[0].code` (show `errors[0].message` verbatim), any other helper starts its top-level `error` with it (show `error` verbatim). Stop. A preflight `STORAGE_UNAVAILABLE` returns `run_id: null` and creates nothing: re-run the same preflight once the storage adapter is installed (a local run never needs it). Setup writes no report; the report is written only if the user
opts in (see the save step).

## Step 2 — Load the data (deterministic, no LLM)

Use `starboard-helper` to fetch job configuration and run history. The commands
are pre-approved by this skill's `allowed-tools`, so they run without a permission
prompt:

```bash
starboard-helper job fetch --profile <profile> --job-id <JOB_ID>
starboard-helper job runs --profile <profile> --job-id <JOB_ID> --limit 10
starboard-helper job list --profile <profile> --limit 25 --name-filter <FILTER>
```

Inspect job fetch: task types, cluster config, schedule, timeout settings, max
retries.
Inspect runs: run states (SUCCESS/FAILED/CANCELED), durations, failure patterns.

For a failed run, read its output and the code it ran:

```bash
starboard-helper job run-output --profile <profile> --run-id <RUN_ID> --task-key <TASK_KEY> --max-bytes 200000
starboard-helper job code --profile <profile> --job-id <JOB_ID> --task-key <TASK_KEY>
```

- `job run-output` returns the task's error, trace and log tail. On a multi-task run, omit
  `--task-key` first: it exits 4 and lists the task keys; pick the failed one (an unknown key
  exits 2).
- `job code` exports the task's notebook or file. A Git or remote source is not in the
  workspace: it exits 2 with `errors[0].code` `CODE_NOT_IN_WORKSPACE` (the message starts
  `code_not_in_workspace:`); say the code wasn't read.
- User names are dropped and emails show as `<email>`. Save each into the run with
  `--run-folder $RUN_FOLDER --out raw/job-run-output-<RUN_ID>.json` (or
  `raw/job-code-<JOB_ID>.json`).

For one job's failure rate over the window, take one row per run (a run counts as failed on
`FAILED`, `ERROR`, `TIMED_OUT` or `TIMEDOUT`; `CANCELLED` is separate):

```bash
starboard-helper verify run vt-job-run-states \
  --ws <workspace_id> --start <YYYY-MM-DD> --end <YYYY-MM-DD> --job-ids <JOB_ID> --limit 20000 \
  --suffix <JOB_ID> --warehouse-id <wh-id> --run-folder $RUN_FOLDER --out analysis/verify/
```

(local run: `--out <run-dir>/analysis/verify/` and no `--run-folder`). `limit_reached: true`
means rows are missing, so the counts are a lower bound: narrow the window and re-run.

Inside an engagement run (a `troubleshooting` run), route a job failure to a case: open it on the
job, revise it with the saved run output, then commit
(see [`starboard-engagement`](../starboard-engagement/SKILL.md) **Cases**):

```bash
starboard-helper engagement case open --run-folder $RUN_FOLDER --clue job:<JOB_ID> --question "<why did it fail?>"
starboard-helper engagement case revise --run-folder $RUN_FOLDER --case-id <case_id> --evidence raw/job-run-output-<RUN_ID>.json --hypothesis "<statement>" --hypothesis-status supported
starboard-helper engagement commit --run-folder $RUN_FOLDER --stage analysis
```

Use `--finding-id <finding_id>` in place of `--clue` when the failure is a health finding.

## Step 3 — Analyze the data yourself

Read the returned configuration and run history:

- **Failure patterns** — are failures consistent (config issue) or intermittent
  (resource issue)?
- **Performance** — are run durations increasing over time? Possible data skew or
  cluster undersizing.
- **Configuration** — is the cluster correctly sized? Are retries configured
  appropriately?
- **Cost** — is the cluster kept alive between runs unnecessarily?

## Step 4 — Produce the report

1. Summary of job health (healthy / degraded / failing)
2. Root cause(s) of failures if any, citing the run output or code you read
3. Specific, actionable recommendations
4. Priority: critical / high / medium / low

### Offer to save the report

After presenting the findings, **offer** to save them as a Markdown report:

> "Want me to save this as a report? I'll write it to `analysis/job.md` in this run (its
> Drive run folder, or its run dir under `./starboard-reports/`)."

If the user accepts, write the report to `analysis/job.md` in the run and add a
`README.md` index with a one-line pointer to the report. Confirm where you wrote it. Don't write
anything unless the user opts in. Inside an engagement run the engagement's deliver beat publishes
it; skip the rest of this step.

- **Local run** (`local` / `internal_only_local`): write `<run-dir>/analysis/job.md` and
  `<run-dir>/README.md`. There is no Drive leg.
- **Drive run** (`drive_required` / `drive_default` / `drive_optional`): nothing is written
  locally. Put both files into the run
  folder with `engagement put` (the bytes come on stdin; an identical re-put is a no-op), then
  record them and check the run:

  ```bash
  starboard-helper engagement put --run-folder $RUN_FOLDER --path analysis/job.md <<'EOF'
  <the report Markdown>
  EOF
  starboard-helper engagement put --run-folder $RUN_FOLDER --path README.md <<'EOF'
  <the README index, with a one-line pointer to analysis/job.md>
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

## Exit codes

- 0: success
- 1: authentication error — check `DATABRICKS_HOST` and `DATABRICKS_TOKEN`
- 2: job not found — verify job ID
- 3: API error — check workspace connectivity
- 7 on a `--run-folder` run whose `error` starts with `BLOCKED_ACCESS`, `STORAGE_INTEGRITY`, `NOT_FOUND`
  or `STORAGE_ERROR`: a storage / integrity / access failure — stop and report `error` verbatim
