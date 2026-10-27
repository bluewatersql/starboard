---
name: starboard-troubleshoot
description: Troubleshoot one Databricks job, run, SQL query or pipeline as a focused case — open the case on the clue, gather only the targeted evidence (run output, code, logs, a pipeline's event log, a query profile, a settings diff), test hypotheses and write a case report with the cause confidence and the next step. Read-only; `$` figures are list-price DBU estimates. Use when the user asks why a specific job, run, query or pipeline failed or slowed down (or why their queries on a warehouse are slow, before the statement is known), or to investigate a health-review finding. For a workspace-wide health read use starboard-health-review instead.
compatibility: opencode
metadata:
  source: packages/starboard-skills/skills/starboard/starboard-troubleshoot/SKILL.md
---

# Starboard: Troubleshoot (the `troubleshooting` task)

This is a **thin entry skill** of the Starboard engagement workflow. **Load
[`starboard-engagement`](../starboard-engagement/SKILL.md) first**: it owns the run setup, the
**Cases** section, the exit codes and the guardrails. This skill runs one task,
`troubleshooting`, on one target, and writes one report, `deliverables/case-report.md`.

A troubleshooting run asks one question about one entity. It runs no workspace discovery, no
billing scan and no backlog, and it has no action-plan deliverable set.

**The internal overlay.** When the Starboard internal enrichment overlay is installed and the run is
`internal_only` or `hybrid`, consult it at the engagement's scope, verify and deliver beats (here:
Steps 2–3, Step 4 and Step 6). Its internal route and enrichment step (Beat 0) applies only on an `internal_only` or `hybrid` run,
as does its diagnostic-triage beat (Beat 1), sanitizing and `run check --internal` (Step 6). On a
`customer_workspace` run consult it for one thing only: the overlay makes the run `drive_required`
(without it, a public run is `local` unless the operator chose `--storage drive`). Nothing else in
it applies there, and `run check` lists the internal-only items under `skipped_not_internal`.

## You are the analyst

**You** are the LLM for this skill. The helpers fetch deterministic evidence; you form and test
the hypotheses and write the report. Do not call the `starboard` goal agent, an MCP
`*_analysis` / `synthesize_*` tool or any other model.

## Step 1 — Parse the clue

Turn what the operator gave you into one case opener:

| The operator gave | Opener |
|---|---|
| a job id or a job URL | `--clue job:<job_id>` |
| a run id or a run URL | `--clue run:<run_id>` |
| a SQL statement id | `--clue query:<statement_id>` |
| a pipeline id (or a pipeline URL) | `--clue pipeline:<pipeline_id>`; an update id is evidence (`pipeline events --update-id`), not the opener |
| a finding from a health review | `--finding-id <finding_id>` |
| a profile, log or event log the customer shared on Drive | `--drive-object drive:<file_id>` (Drive runs only) |
| only a scope: "my queries on warehouse X are slow", "a job keeps failing" | no opener yet: find the target inside the run first (below) |

Ask for the one question the case answers ("why did it start failing?", "why is it slower since
the upgrade?") when the prompt doesn't give it. Ask which `--profile <name>` reaches the
workspace; never pick one yourself.

**No target id yet.** When the operator names a scope (a warehouse, the workspace's queries, its
jobs) but no statement, job or pipeline id, don't open a case on the scope. Name the run after
the scope you search (Step 2), find the target inside the run (Step 3), then open the case on the
target you found: `--clue query:<statement_id>` or `--clue job:<job_id>`. When the search finds
no single target, say so and ask the operator which one to investigate.

**A health-review finding with no `finding_id`.** No helper lists an account's findings outside
a run, so ask the operator for the `finding_id`. When they point at the health review's run
instead, read that run's findings and its plays, and confirm the one they mean, then open with
`--finding-id`:
`starboard-helper engagement read --run-folder <that run's run_folder_id> --path analysis/findings.json`
and `--path analysis/plays.json` (a local run: read `<that run's run-dir>/analysis/findings.json`
and `analysis/plays.json`). A play's `next_step_kind` is `investigate`, `act` or `acquire`; "the
finding whose play is `investigate`" is the `finding_ids[0]` of a play with
`next_step_kind: investigate` (`play_code` `job_reliability_investigation` or
`rule_finding_review`).

When that run has no findings (`findings.json` is `[]`) or none matches what the operator
described, say so, then ask for a clue instead (`job:<job_id>`, `query:<statement_id>`,
`pipeline:<pipeline_id>` or a warehouse id, which is a searched scope: Step 3) or stop. Never
invent a `finding_id` or open a case on a finding you didn't read. When "the top-ranked play"
picks the finding, it is the play with the lowest `effective_rank`: the host rank first, then
Starboard's computed order. `analyze` (the `top_plays[]` digest) and `play rank` emit the field;
`plays.json` stores `host_rank` and lists the plays in computed order, so order by `host_rank`
(ranked plays first), then by position. Never take the first row of a file unless it is the
lowest `effective_rank`.

## Step 2 — Choose the source, then set up the run

```bash
starboard-helper engagement source-options --task troubleshooting
```

When `data.choice_required` is true and the prompt doesn't say, ask once, using `data.question`
as written: it lists each option's storage and whether workspace auth is needed. Never choose
silently; an unattended run must already
carry `--source-mode`. When it is false, the run is `customer_workspace`.

When the operator picks a customer or hybrid leg but has no customer profile, never pick one:
start a new `internal_only` run (a run's source is fixed at preflight) and write under the
report's `## Unknowns`:

```
- customer workspace: not acquired (no customer profile)
```

```bash
starboard-helper engagement preflight --task troubleshooting --task-name <target>-<id> \
  --account-key <account_key> --account-name "<account name>" --source-mode <mode>
starboard-helper engagement verify-identity --run-id <run_id> --profile <profile> \
  --expected-workspace-id <workspace_id>
starboard-helper engagement route --run-id <run_id>
```

- Account key (**the account key rule** of `starboard-engagement`): at preflight use the key
  the operator gave; else the WORKSPACE ID. Never use the account name as the key
  (`account_key_looks_like_name:` warns). `verify-identity` runs after preflight, so the key
  never changes mid-run. `ACCOUNT_NAME_TAKEN` (exit 2) means the `--account-name` belongs to
  another key: re-run `engagement preflight` with `--account-key` set to the key the message names if it is the same
  account, else choose a different name; never merge.
- Name the run after the target: `--task-name job-<id>`, `query-<id>` or `pipeline-<id>`. A
  case opened with `--finding-id` is named after the finding's entity (its `entity_kind` and
  `entity_id`: `job-<entity_id>`, `query-<entity_id>`, `pipeline-<entity_id>`,
  `warehouse-<entity_id>`, or `ws-<entity_id>` for `entity_kind` `workspace`), so it shares the case root of the same target's other cases; with
  only the id and no finding record, `--task-name finding-<finding_id>`. With no
  target id, name it after the searched scope: `--task-name queries-<workspace_id>` (the
  workspace's queries), `warehouse-<warehouse_id>` (one warehouse's queries) or
  `jobs-<workspace_id>` (its jobs). A workspace-scoped finding (`entity_kind` `workspace`, such as a
  health review's spend finding) uses `--task-name ws-<workspace_id>`; `workspace-<id>` is refused
  with a hint to use `ws-<id>`. Keep preflight's `run_id`. Pass `--storage drive|local` only when the operator named a store.
  Pass `--unattended` only when the prompt says the run is scheduled or unattended, or says not to
  ask anything. A prompt that pre-supplies answers but says neither is attended: take the answers
  from it and leave the flag off. "Non-interactive" or "nobody will answer" next to an operator script is attended too: the script is the operator.
- `verify-identity` runs on a customer or hybrid leg only. A mismatch exits non-zero and
  quarantines the run: stop, show `error` and read nothing.
- An `internal_only` run (internal overlay only) skips `verify-identity` and passes the
  workspace at preflight:
  `starboard-helper engagement preflight --task troubleshooting --task-name <target>-<id> --account-key <account_key> --account-name "<account name>" --source-mode internal_only --internal-workspace-id <workspace_id>`.

Act on preflight's `storage_decision`:
- **`drive_required`**, **`drive_default`** or **`drive_optional`** (a public install where the
  operator chose `--storage drive`): route returns `run_folder_id` (`$RUN_FOLDER`).
  Every writer takes `--run-folder $RUN_FOLDER` with run-relative paths and **nothing is written
  locally**. Show any `fallback_warning` (the chosen folder wasn't writable, so the run went to
  the `My Drive` account route). Let stderr go to the terminal and never redirect stdout or stderr
  anywhere, or `tee` them: not to a file, not under `/tmp`, and not to `/dev/null`.
- **`local`** or **`internal_only_local`**: `data.local_run_dir` is
  `<run-dir>` and its parent is the case root (`<case-root>`). Route writes
  `<run-dir>/analysis/run-authorization.json`. A `--drive-object` opener needs a Drive run.

A refusal exits 2 with `LOCAL_STORAGE_REFUSED` or `STORAGE_UNAVAILABLE`: the `engagement` envelope
carries it as `errors[0].code` (show `errors[0].message` verbatim), any other helper starts its
top-level `error` with it (show `error` verbatim). Stop. A preflight `STORAGE_UNAVAILABLE` returns
`run_id: null` and creates nothing: re-run the same preflight once the storage adapter is
installed (a local run never needs it). Record `run_id`, `task`, `task_name`, `storage_decision`,
the run link (or the local run dir) and every warning under README `## Storage`.

## Step 3 — Open the case

With no target id, find the target first and save the search into the run:

```bash
starboard-helper query slow --warehouse-id <warehouse_id> --profile <profile> --run-folder $RUN_FOLDER --out raw/query-slow-<warehouse_id>.json
starboard-helper query history --warehouse-id <warehouse_id> --status FAILED --limit 100 --profile <profile> --run-folder $RUN_FOLDER --out raw/query-history-<warehouse_id>.json
starboard-helper job list --limit 100 --profile <profile> --run-folder $RUN_FOLDER --out raw/job-list-<workspace_id>.json
starboard-helper job runs --job-id <job_id> --limit 10 --profile <profile> --run-folder $RUN_FOLDER --out raw/job-runs-<job_id>.json
```

Drop `--warehouse-id` for a `queries-<workspace_id>` run. `job list --name-filter <text>` keeps
the jobs whose name matches. `query slow` scans the 200 most
recent statements and returns the 25 slowest (`--limit`) that ran at least 10000 ms
(`--min-duration-ms`); `--lookback-days <n>` keeps only those started in the last `n` days. When asked for a threshold
or lookback, the operator's answer wins: pass `--lookback-days` only when they give a number of
days ("defaults" means no flag), and "recent" alone is not a number; the rows are at `$.data.slow_queries`, and the output echoes `scanned` and `window`; each
row has `query_id`, `status`, `duration` (ms), `warehouse_id` and `start_time_iso`. On a Drive
run the stdout carries only a file reference: read the rows back with `starboard-helper engagement read
--run-folder $RUN_FOLDER --path <the --out file> --jsonpath '$.data.slow_queries'`. Without
`--lookback-days` the scan can reach back weeks: quote `window.scanned_first_start`,
`window.scanned_last_start` and `window.scan_capped` in the report.  To leave out a busy
warehouse (a workspace-wide search drowned by one warehouse's statements), add
`--exclude-warehouse-id <id>` (repeatable): `scanned` then counts only the statements that are
not excluded (still up to 200, across up to 25 pages), and the output adds
`excluded_warehouse_ids`, `excluded` and `pages`. The same id in `--warehouse-id` and
`--exclude-warehouse-id` is an argument error (exit 4). A `WORKSPACE_TIMEOUT` (exit 3,
retryable) is retried once as is; if it fails again, narrow the search (`--warehouse-id`, a
shorter `--lookback-days`) or record it under `## Unknowns`. Only when the whole search finds no
row, retry once with a lower `--min-duration-ms` (say 1000) or read the `query history` line,
then say what you searched and ask the operator for the statement id; never open a case on the
scope. Read the
saved file back, pick the statement (or job) that matches the operator's symptom, then open the
case on it:

```bash
starboard-helper engagement case open --run-folder $RUN_FOLDER --clue job:<job_id> --question "<the operator's question>"
starboard-helper engagement case open --run-folder $RUN_FOLDER --clue query:<statement_id> --question "<the operator's question>"
starboard-helper engagement case open --run-folder $RUN_FOLDER --clue pipeline:<pipeline_id> --question "<the operator's question>"
starboard-helper engagement case open --run-folder $RUN_FOLDER --finding-id <finding_id> --question "<the operator's question>"
starboard-helper engagement case open --run-folder $RUN_FOLDER --drive-object drive:<file_id> --question "<the operator's question>"
starboard-helper engagement case show --run-folder $RUN_FOLDER --case-id <case_id>
```

Use the one opener that fits. Local run:
`starboard-helper engagement case open --run-dir <run-dir> --workspace-root <case-root> --clue job:<job_id> --question "<the operator's question>"`
(`--workspace-root` is exactly the run dir's parent). Run `case show` right after
`case open`. A `--finding-id` case may name a finding from another run of the account (a
`health_check` run); it links to this run only after the first `case revise`.

When you found the target with a search, cite the saved search file (`raw/query-slow-….json`,
`raw/job-list-….json`) with `--evidence` in the first `case revise`.

## Step 4 — Gather the targeted evidence

Fetch only what the question needs, and save each fetch into the run:

```bash
starboard-helper job fetch --job-id <job_id> --profile <profile> --run-folder $RUN_FOLDER --out raw/job-<job_id>.json
starboard-helper job runs --job-id <job_id> --limit 10 --profile <profile> --run-folder $RUN_FOLDER --out raw/job-runs-<job_id>.json
starboard-helper job run-output --run-id <run_id> --task-key <task_key> --max-bytes 200000 --profile <profile> --run-folder $RUN_FOLDER --out raw/job-run-output-<run_id>.json
starboard-helper job code --job-id <job_id> --task-key <task_key> --profile <profile> --run-folder $RUN_FOLDER --out raw/job-code-<job_id>.json
starboard-helper query fetch --query-id <statement_id> --profile <profile> --run-folder $RUN_FOLDER --out raw/query-<statement_id>.json
starboard-helper warehouse fetch --warehouse-id <warehouse_id> --profile <profile> --run-folder $RUN_FOLDER --out raw/warehouse-<warehouse_id>.json
starboard-helper pipeline fetch --pipeline-id <pipeline_id> --profile <profile> --run-folder $RUN_FOLDER --out raw/pipeline-<pipeline_id>.json
starboard-helper pipeline updates --pipeline-id <pipeline_id> --limit 10 --profile <profile> --run-folder $RUN_FOLDER --out raw/pipeline-updates-<pipeline_id>.json
starboard-helper pipeline events --pipeline-id <pipeline_id> --update-id <update_id> --level WARN --profile <profile> --run-folder $RUN_FOLDER --out raw/pipeline-events-<update_id>.json
starboard-helper serving fetch --endpoint-id <endpoint_id> --profile <profile> --run-folder $RUN_FOLDER --out raw/serving-<endpoint_id>.json
starboard-helper uc table --full-name <catalog>.<schema>.<table> --profile <profile> --run-folder $RUN_FOLDER --out raw/uc-table-<table>.json
starboard-helper uc tables --catalog <catalog> --schema <schema> --profile <profile> --run-folder $RUN_FOLDER --out raw/uc-tables-<schema>.json
starboard-helper diagnostic driver-log --cluster-id <cluster_id> --stream log4j --profile <profile> --run-folder $RUN_FOLDER --out raw/driver-log-<cluster_id>.json
starboard-helper diagnostic cluster-log --cluster-id <cluster_id> --limit 200 --profile <profile> --run-folder $RUN_FOLDER --out raw/cluster-log-<cluster_id>.json
```

These fetches read the customer workspace (a customer or hybrid leg), each as the run's
workspace profile: pass `--profile <profile>` (the one `verify-identity` checked; another profile
is refused with `PROFILE_MISMATCH`). `pipeline events`
reads the event log with its error exceptions and stack heads; `--level WARN` keeps warnings and
errors, and `--update-id` keeps one update's events (take the id from `pipeline updates`).
`scanned` counts the pipeline's events read before the `--update-id` match (pipeline-wide, not
that update's), and `scan_capped: true` means the scan stopped at its cap before the limit was
filled. An empty list for an old update usually means its events aged out of the pipeline's event-log
retention, not that the update was clean: record it under `## Unknowns` and use the most recent
failed update instead. When the most recent update's list is empty too, read the configured event
log from `$.data.spec.event_log` in `raw/pipeline-<pipeline_id>.json` and check that table with
`uc table`: a missing table exits 2 ("not found or not visible to this identity": absent or no
privilege, not proof that it was dropped). Any fetch that fails with not found (exit 2, this
one included, and `warehouse fetch`) still writes the `ok: false` envelope to `--out`.
Cite that file with `case revise --evidence <path>`. Then keep `--cause-confidence hypothesis` and write
the reason (no readable error event) under `## Unknowns`.

- `uc table` checks that one table exists and returns its metadata; `uc tables` lists a schema.
  Use them when the cause turns on a table, schema or event-log table existing.

- `job code` reads a notebook or Python-file task's source only; a wheel, JAR, Git or other
  packaged task exits 2 with `errors[0].code` `CODE_NOT_IN_WORKSPACE` (the `error` message starts
  `code_not_in_workspace:`; the job exists): record it under `## Unknowns`, never guess the code.
- `job run-output` reports the run's error at `$.data.error` (read it with
  `engagement read --jsonpath '$.data.error'`). Its other fields are `run_id`, `task_run_id`,
  `task_key`, `state`, `error_trace`, `logs`, `logs_truncated`, `notebook_output`, `truncated`
  and `max_bytes`; there is no `metadata`.
- `serving fetch` reads a model serving endpoint's current config: per served entity
  `scale_to_zero_enabled`, `workload_type`, `workload_size` and the provisioned concurrency or
  throughput, plus the traffic routes and any `pending_config`. Pass the id billing carries as
  `usage_metadata.endpoint_id` (the `workload_id` of a `vt-step-change` `endpoint` row), or
  `--endpoint-name <name>`. No system table has scale to zero, so a serving cost finding reads
  it here. Environment variable values and provider credentials are never returned (only the
  variable names). A deleted endpoint exits 2: record its config under `## Unknowns` and use
  `vt-endpoint-config-history`. The id lookup lists only the endpoints this identity can
  view, so an endpoint without View permission also exits 2 ("not found among the endpoints
  this identity can view"): try `--endpoint-name` once; a permission error there exits 3 and
  writes no `--out` file, so cite the exit-2 file and use `vt-endpoint-config-history`.
- `diagnostic driver-log` and `cluster-log` read a classic cluster's logs. A serverless task has
  no cluster id and no driver log: use `job run-output` (and a query profile) instead.
- `query fetch` (the statement and its metrics) and `warehouse fetch` (the warehouse's size,
  scaling and type) cover a query case. When the target warehouse was deleted, `warehouse fetch`
  exits 2: record its configuration under `## Unknowns` and use `vt-warehouse-queue` or
  `vt-warehouse-drivers` with `--warehouse-ids <target_warehouse_id>`, which read system tables.
  These verify templates read query history, which covers at most the 7 days ending `--end`
  (`query fetch` reads one statement by id and takes no window): for one statement
  set `--end` to the day after its start and `--start` up to 6 days before (`qh_window_clamped`
  in the summary, and a stderr warning, say when a longer window was cut).
  A `query_text` of `<REDACTED>` comes from the Databricks API (this identity cannot view the
  text): do not work around it. Mark a text-based diagnosis as not possible under `## Unknowns` and
  use the query profile metrics. A query's full profile is not an API fetch: ask the
  operator to download it (the query profile's JSON export) and share it on Drive, then read it
  with `python -m starboard_x.diagnostic profile --input drive:<file_id>` below (a local run: a
  local file). With no query profile (the operator can't export one), statement metrics such as
  compile or queue time can support a hypothesis about where the time goes, but not the cause:
  keep `--cause-confidence hypothesis` on the finding and write the missing profile under
  `## Unknowns`.

On a Drive run never save helper stdout with Write: every fetch goes into the run with
`--run-folder $RUN_FOLDER --out raw/<name>.json` (a local `--out` path is refused with
`LOCAL_STORAGE_REFUSED`), and you read it back with
`starboard-helper engagement read --run-folder $RUN_FOLDER --path raw/<name>.json`. On a local run
the same fetches take `--out <run-dir>/raw/<name>.json` and no `--run-folder`. Record the fetches
with `starboard-helper engagement commit --run-folder $RUN_FOLDER --stage capture`. Evidence
fetched after a `case revise` needs its own `--stage capture` commit before the next analysis commit.
A `verify run` file (`analysis/verify/`) is analysis-stage evidence and needs no capture commit:
every commit records all of the run's files, so the next `--stage analysis` commit binds it.

These read evidence that is already in the run or on Drive and print a summary; they take no
`--out`, so cite their input file as the evidence:

```bash
python -m starboard_x.diagnostic profile --input drive:<file_id>
python -m starboard_x.sparklog parse --input drive:<file_id>
python -m starboard_x.diff settings --a raw/job-<id>-before.json --b raw/job-<id>-after.json --run-folder $RUN_FOLDER
python -m starboard_x.diff metrics --a raw/query-<id>-before.json --b raw/query-<id>-after.json --run-folder $RUN_FOLDER
```

The focused skills ([`starboard-job`](../starboard-job/SKILL.md),
[`starboard-query`](../starboard-query/SKILL.md),
[`starboard-diagnostic`](../starboard-diagnostic/SKILL.md)) document each verb. On a public local
run `--input` takes a local file. A `verify run` slice for this target is optional; use the
engagement's verify templates (`vt-job-run-states` with `--job-ids <job_id>`,
`vt-pipeline-updates` with `--pipeline-ids <pipeline_id>`,
`vt-endpoint-daily` and `vt-endpoint-config-history` with `--endpoint-ids <endpoint_id>`,
`vt-warehouse-queue` or
`vt-warehouse-drivers` with `--warehouse-ids <target_warehouse_id>`; for a workspace spend
finding `vt-step-change` with `--split-date <step date>` and `vt-daily-totals`; for a governance or
attribution finding `vt-product-totals`, plus a read-only `query sql` for the split the template
lacks) rather than
hand-written SQL, which [verify.md](../starboard-engagement/references/verify.md) allows only when
no template fits (on a Drive run there is no local `.sql` file: hold the statement in a shell
variable, `SQL=$(cat <<'EOF' … EOF)`, and save it with `query sql … --sql "$SQL" --run-folder
$RUN_FOLDER --out analysis/verify/<file>.json`, which also writes `analysis/verify/<file>.sql`; pass `--timeout <seconds>` on an aggregation over a long window, as
the default waits about 50 s). `verify run` reads the engagement's bundled `verify-sql.md` by
default, so pass no `--templates` on the public path. User
names are dropped and emails show as `<email>`.

A public `verify run` needs `--warehouse-id` of an **existing** SQL warehouse. List them, then
ask the operator which one verify may use to RUN the query (`--warehouse-id`; a template's target
warehouse is `--warehouse-ids`):

```bash
starboard-helper warehouse list --profile <profile> --run-folder $RUN_FOLDER --out raw/warehouses.json
starboard-helper verify run vt-job-run-states --warehouse-id <warehouse_id> --ws <workspace_id> --start <YYYY-MM-DD> --end <YYYY-MM-DD> --job-ids <job_id> --limit 20000 --suffix <job_id> --profile <profile> --run-folder $RUN_FOLDER --out analysis/verify/
starboard-helper verify run vt-warehouse-queue --warehouse-id <warehouse_id> --warehouse-ids <target_warehouse_id> --ws <workspace_id> --start <YYYY-MM-DD> --end <YYYY-MM-DD> --limit 1000 --suffix <target_warehouse_id> --profile <profile> --run-folder $RUN_FOLDER --out analysis/verify/
starboard-helper verify run vt-pipeline-updates --warehouse-id <warehouse_id> --ws <workspace_id> --start <YYYY-MM-DD> --end <YYYY-MM-DD> --pipeline-ids <pipeline_id> --limit 100 --suffix <pipeline_id> --profile <profile> --run-folder $RUN_FOLDER --out analysis/verify/
starboard-helper verify run vt-endpoint-daily --warehouse-id <warehouse_id> --ws <workspace_id> --start <YYYY-MM-DD> --end <YYYY-MM-DD> --endpoint-ids <endpoint_id> --limit 1000 --suffix <endpoint_id> --profile <profile> --run-folder $RUN_FOLDER --out analysis/verify/
starboard-helper verify run vt-endpoint-config-history --warehouse-id <warehouse_id> --ws <workspace_id> --endpoint-ids <endpoint_id> --limit 1000 --suffix <endpoint_id> --profile <profile> --run-folder $RUN_FOLDER --out analysis/verify/
```

For a serving finding, `vt-endpoint-daily` gives one row per endpoint, day and product: a day
with no row had no billed usage (on an endpoint with `scale_to_zero_enabled: true`, scaled to
zero all day). `usage_metadata.endpoint_id` is shared by serving, AI Gateway, Vector Search,
Lakebase and agent products, and one endpoint can bill under both `MODEL_SERVING` and
`AI_GATEWAY`: sum a day's rows for the endpoint's total and cite the split.
`vt-endpoint-config-history` lists the served entities per config version (concurrency, compute
type, throughput), so a config change can be dated against the step date; the current scale to
zero setting comes from `serving fetch`.

`vt-pipeline-updates` gives one row per pipeline (from system tables); `pipeline updates` (the
API) can list fewer updates for the same pipeline, so report both counts with their source and
take the history from the verify file. `first_update_start`, `last_update_start`,
`first_update_end` and `last_update_end` bound the window's updates, so "since when" is one call
with an early enough `--start`. Always pass `--limit`; a template whose own SQL ends in
`LIMIT n` returns `limit_reached: false` with `top_n: n` (a ranked top-N by design), otherwise
`limit_reached: true` means rows are missing.

(local run: `--out <run-dir>/analysis/verify/` and no `--run-folder`.) With no answer, skip the slice and record it under `## Unknowns`
(`- verify slice: skipped (no warehouse chosen)`). When the warehouse the operator named is not
in `warehouse list` or `verify run` says it `was not found`, ask once for another from the list;
with no usable answer, skip the slice the same way (`- verify slice: skipped (warehouse <id> not
found)`). Never issue a create, start or resize for a
warehouse. Running a statement on the warehouse the operator named may auto-resume it if it is
stopped: that is allowed.

## Step 5 — Revise the case and record the next step

```bash
starboard-helper engagement case revise --run-folder $RUN_FOLDER --case-id <case_id> --evidence raw/job-run-output-<run_id>.json --hypothesis "<statement>" --hypothesis-status supported --cause-confidence supported
starboard-helper engagement action propose --run-folder $RUN_FOLDER --case-id <case_id> --next-step "<the change>" --owner-role <role> --owner-label "<who owns it>" --verify-method "<how the outcome is checked>"
starboard-helper engagement action accept --run-folder $RUN_FOLDER --action-id <action_id> --note "<what the operator owns>"
starboard-helper engagement action execute --run-folder $RUN_FOLDER --action-id <action_id> --executed-at <YYYY-MM-DD>
starboard-helper engagement commit --run-folder $RUN_FOLDER --stage analysis
```

- One `case revise` per evidence step. A hypothesis is `untested`, `supported` or `refuted`;
  mark it `supported` only when a cited file shows it. The finding's `cause_confidence` starts
  `unassessed` (never passed); `--cause-confidence hypothesis` records a cause under test, and
  `supported` needs a `supported` hypothesis that cites evidence; omit the flag to keep the
  current value. `--question` and `--hypothesis` are at most 500 characters, with no emails or
  credentials (refused, exit 2).
- The case's `finding_id` and `finding_key` are the ones `case open` printed, for good: no
  revision re-keys them (two standalone cases on one job share one `case:job` finding). A
  `case revise` that cites a `job run-output` with `--evidence` reports its `error_signature`,
  `<category>/<exception>[:<code>]` (e.g. `unknown/restexception:not_found`; null without one).
- `--verify <path>` accepts only a job run-state verify result (`vt-job-run-states`). Cite any
  other verify file (a warehouse or query verify, a pipeline-updates verify) with
  `--evidence <path>` instead:
  `starboard-helper engagement case revise --run-folder $RUN_FOLDER --case-id <case_id> --evidence analysis/verify/<vt-id>-<suffix>.json --hypothesis-id h1 --hypothesis-status supported`.
- The evidence this step registers (`--evidence`, `--verify`) always joins the targeted
  hypothesis's cited list, so "add the new file and keep the old" is one call. A reword
  (`--hypothesis "<new text>"`) or status-only step with no new evidence keeps the stored evidence
  and status. `--hypothesis-evidence <evidence_id>` (repeatable; each must already be evidence of
  this run, as an earlier `case revise` printed it in `evidence_ids`, else exit 2) REPLACES the
  stored IDs with exactly those, and the step's own evidence is still added. Re-test a hypothesis in
  place with `--hypothesis-id <id>` (`h1`, `h2`, … from `case show`; it keeps its position in
  `hypotheses[]`); without it a new one is added. Changing only the status needs no `--hypothesis` text: `--hypothesis-id h1
  --hypothesis-status refuted` reuses the stored statement. `case open`, `revise` and `show` list the
  case's `hypotheses` (`[{hypothesis_id, statement, status, evidence_ids}]`); `case show` also
  returns `evidence_paths` (each evidence ID with its run-relative path) and `evidence_from_run`:
  evidence carried from the finding's other runs has a null path in `evidence_paths`, which is
  normal, and `evidence_from_run` names the run that cited it.
- Once the cause is recorded, propose the next step with `action propose` (`--owner-role` is one
  of `job_owner`, `pipeline_owner`, `warehouse_owner`, `platform_admin`, `operator`,
  `account_team`). Proposing is yours; it prints the `action_id` and links it to the case's
  finding, and the same next step on the same case names the same action. With no change to
  propose, write `no action: <reason>` in the report instead.
- Move an action past `proposed` only on the operator's word (`accept`, `reject`, `execute`,
  `withdraw`); `execute` needs a prior `accept`. Repeating a verb on an action already in that
  state returns `already: "<state>"` (idempotent, nothing written), so a retry is safe.
- Commit (`--stage analysis`) after every `case revise` and `action …`. On a local run the same
  verbs take `--run-dir <run-dir> --workspace-root <case-root>`.

## Step 6 — Write the case report, check the run, deliver

Write `deliverables/case-report.md` from
[`templates/case-report.md`](../starboard-engagement/templates/case-report.md): the symptom, the
evidence (each file cited), the cause with its `cause_confidence`, the next step (the action id)
and an `Unknowns` section. Name every `case_id`. `$` figures are **list-price DBU estimates**,
labelled as such. Write "about" for an approximate figure, never `~`: the report is delivered to a
Doc unchanged, and a Doc turns `~` into strikethrough or a literal `\~`. The README's `## Recur` reads `not applicable: troubleshooting run`, and its
`## Delivery` section is in place before `run check` (run check item 1 needs a real artifact line
there; the delivery below replaces it with each outcome):

```markdown
## Delivery

- deliverables/case-report.md
```

```bash
starboard-helper engagement put --run-folder $RUN_FOLDER --path deliverables/case-report.md <<'EOF'
<the case report Markdown>
EOF
starboard-helper engagement put --run-folder $RUN_FOLDER --path README.md <<'EOF'
<the README: ## Storage, the Delivery section above, and ## Recur: not applicable: troubleshooting run>
EOF
starboard-helper engagement commit --run-folder $RUN_FOLDER --stage analysis
starboard-helper run check --run-folder $RUN_FOLDER --out analysis/run-check.json
starboard-helper engagement commit --run-folder $RUN_FOLDER --stage check
```

Local run: write `<run-dir>/deliverables/case-report.md` and `<run-dir>/README.md`, then
`starboard-helper run check <run-dir> --out <run-dir>/analysis/run-check.json`. `run check`
warnings are at `data.warnings`, not the envelope's top level.

Internal enrichment (an `internal_only` or `hybrid` run with the internal overlay installed):
before the analysis commit, sanitize every `deliverables/` text file into its `.clean` sibling
per the overlay's *Beat 4*, and add `--internal` to `run check`:
`starboard-helper run check --run-folder $RUN_FOLDER --internal --out analysis/run-check.json`
(local: `starboard-helper run check <run-dir> --internal --out <run-dir>/analysis/run-check.json`).
Without `--internal`, items 12 and 16 (the `.clean` siblings and their sanitizer check) are
not checked: `run check` lists them under `skipped_not_internal`, never under `passed`. Deliver only the `.clean` files. The overlay's *Health reviews and troubleshooting on
the internal-only leg* has the commands.

`run check` uses the `troubleshooting` profile (`data.profile`) and lists the rest under
`skipped_by_profile`. `case_linked` needs each case's finding in this run (after `case revise`);
`focused_report` needs the case report to name each `case_id` and carry an `Unknowns` heading.
Fix every failure until it exits 0. `run check` rewrites `analysis/run-check.json`, so every
repeated `run check` needs another `--stage check` commit.

When the case shows a wider problem, offer (never start) a health review with
[`starboard-health-review`](../starboard-health-review/SKILL.md): a new run, one task per run.
Make the offer after `run check` and before the README re-put below, so the operator's answer
goes into that same put.

Deliver with [`starboard-deliver`](../starboard-deliver/SKILL.md). On a Drive run it starts by
registering the report, which every publication step needs. Register it only after the
`--stage check` commit: until a commit binds the report file, `engagement report` exits
`UNCOMMITTED_ARTIFACT`.
`starboard-helper engagement report --run-folder $RUN_FOLDER --report-id case-report --audience internal --path deliverables/case-report.md`
(the `.clean` file on an internal-enrichment run). Then replace the
`- deliverables/case-report.md` line with the delivery outcomes (the receipt or URL, or
`not delivered: <reason>`) and re-commit the check stage; that is the last `--stage check`
commit, and it needs no new `run check` unless a fix needs it. When the operator wants no delivery
beyond the run itself, the line is
`- deliverables/case-report.md: run folder only (<the run link or local run dir>), not delivered elsewhere`.

```bash
starboard-helper engagement put --run-folder $RUN_FOLDER --path README.md <<'EOF'
<the whole README, with the ## Delivery lines filled in>
EOF
starboard-helper engagement commit --run-folder $RUN_FOLDER --stage check
```

## Exit codes

`starboard-helper engagement …` (preflight, route, `case`, `action`, `put`, `commit`) uses the
engagement codes in [`starboard-engagement`](../starboard-engagement/SKILL.md): 2 is a refusal
or a bad opener (`USAGE`), 3 auth, 4 storage access or an unknown `case_id` / finding, 5 an
identity mismatch, 6 a workspace API error, 8 `STORAGE_TRANSIENT` (Drive failed transiently;
with exit 8 or `errors[0].retryable: true`, retry the same command once, and if it fails again
stop and record it under `## Unknowns`). The fetch verbs (`job`, `query`, `pipeline`,
`diagnostic`) and `run check` use the generic codes:

- 0: success
- 1: authentication error, or `run check` found a failure
- 2: the job, run, query, pipeline, warehouse, cluster, serving endpoint or table doesn't exist (`job fetch` /
  `runs`, `pipeline fetch` / `updates` / `events`, `query fetch`, `warehouse` / `cluster` /
  `serving` fetch,
  the `uc` reads), `CODE_NOT_IN_WORKSPACE` (`job code`; the job exists), a `PROFILE_MISMATCH`, or
  a storage refusal (`LOCAL_STORAGE_REFUSED`, `STORAGE_UNAVAILABLE`)
- 3: API error — check workspace connectivity; `WORKSPACE_TIMEOUT` (retryable) is the workspace
  call running out of its retry budget: retry once, then narrow the call or record it under
  `## Unknowns`
- 4: argument error — a missing or bad flag
- 7 on a `--run-folder` run whose `error` starts with `BLOCKED_ACCESS`, `STORAGE_INTEGRITY`, `NOT_FOUND`
  or `STORAGE_ERROR`: a storage / integrity / access failure — stop and report `error` verbatim
- 8: `STORAGE_TRANSIENT` (retryable): retry the same command once

A failure with a machine code also carries `errors: [{code, message, retryable}]` (`error`
stays the message).
