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

> **Routing.** For a workspace health read (proactive, weekly, monthly or QBR) use
> [`starboard-health-review`](../starboard-health-review/SKILL.md); to troubleshoot one job, run,
> query or pipeline as a focused case use [`starboard-troubleshoot`](../starboard-troubleshoot/SKILL.md).
> Each is its own run (one task per run).

## You are the analyst

**You** are the LLM for this skill. The skill hands you deterministic query
history data; **you** read the rows and write the performance assessment and
recommendations yourself.

Do **not** call the `starboard` goal agent, an MCP `*_analysis` / `synthesize_*`
tool, a model-serving endpoint, or any other model. There is no second LLM in
this loop — the data step below uses plain CLI fetches (no LLM), and you do the
reasoning. Handing analysis to another model defeats the point of the skill and
breaks when that model's credentials differ from your session's.

## Step 1 — Confirm inputs and set up the run

Before loading data, confirm the run parameters with the user — but **only ask
for what they haven't already given**. If their request already specifies a value
(e.g. "slow queries over 30 s"), use it and skip that question. If they say
"just go" / "use defaults", proceed with the defaults.

Ask for (with defaults):

- **History lookback window** — how many recent queries to inspect (default:
  **25 most recent**).
- **Slow-query duration threshold** — minimum execution time to flag as slow
  (default: **10 000 ms**).
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
--task-name ws-<workspace_id>` for a workspace-wide report. To troubleshoot slow or failing
queries before you know the statement, run `--task troubleshooting` and name the run after the
scope you search: `--task-name queries-<workspace_id>` (the workspace's queries) or
`warehouse-<warehouse_id>` (one warehouse's queries). Find the statement inside the run
(`query slow` / `query history` saved with `--run-folder $RUN_FOLDER --out raw/<name>.json`), then
open the case on the statement you found, never on the warehouse:
`starboard-helper engagement case open --run-folder $RUN_FOLDER --clue query:<statement_id> --question "<the user's question>"`
([`starboard-troubleshoot`](../starboard-troubleshoot/SKILL.md) owns the case flow). Keep preflight's `run_id`. Always pass
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

Use `starboard-helper` to fetch query history. The commands are pre-approved by
this skill's `allowed-tools`, so they run without a permission prompt:

```bash
# For a specific query:
starboard-helper query fetch --profile <profile> --query-id <QUERY_ID>

# For recent history on a warehouse:
starboard-helper query history --profile <profile> --warehouse-id <WH_ID> --limit 25

# For slow queries (--lookback-days 7 keeps "recent" to the last week):
starboard-helper query slow --profile <profile> --lookback-days 7 --min-duration-ms 10000 --limit 25
```

`query slow` scans the newest 200 statements, which can reach back weeks. Pass `--lookback-days`
for "recent". Without it, quote `window.scanned_first_start`, `window.scanned_last_start` and
`window.scan_capped` from the output so the reader sees what was scanned.

`query fetch` returns one statement from query history with its metrics (durations, rows and
bytes read, spill), not its plan. User names are dropped and emails in the query text show as `<email>`.
A `query_text` of `<REDACTED>` comes from the Databricks API: this identity cannot view the text.
Do not work around it. Say that a text-based diagnosis (rewrites, join shape) is not possible, and
use the query profile metrics.

For the plan, ask the user to export the query profile JSON from the query history UI and read
it with:

```bash
python -m starboard_x.diagnostic profile --input drive:<file_id>
```

`--input` takes a Drive file (`drive:<id>`) or, on a public install, a local file; an overlay
install refuses a local file (exit 2). It returns the top operators by time, rows and bytes,
spill, scan stats and warnings (`truncated` when the profile was cut).

## Step 3 — Analyze the data yourself

Read the returned query records:

- **Duration** — is query duration above expected thresholds for query complexity?
- **Failures** — what error messages are present? Are they permission, syntax, or
  resource errors?
- **Patterns** — do slow queries share common tables, joins, or filter patterns?
- **Warehouse** — is the warehouse appropriately sized for the query workload?
- **Profile** — if you read one, which operators dominate time, and is there spill or a full
  scan?

## Step 4 — Produce the report

1. Summary of query health / performance
2. Root cause(s) of slowness or failures
3. Specific SQL optimization recommendations (indexes, partitioning, rewrite
   suggestions)
4. Warehouse sizing recommendations if applicable
5. Priority: critical / high / medium / low

### Offer to save the report

After presenting the findings, **offer** to save them as a Markdown report:

> "Want me to save this as a report? I'll write it to `analysis/query.md` in this run (its
> Drive run folder, or its run dir under `./starboard-reports/`)."

If the user accepts, write the report to `analysis/query.md` in the run and add a
`README.md` index with a one-line pointer to the report. Confirm where you wrote it. Don't write
anything unless the user opts in. Inside an engagement run the engagement's deliver beat publishes
it; skip the rest of this step.

- **Local run** (`local` / `internal_only_local`): write `<run-dir>/analysis/query.md` and
  `<run-dir>/README.md`. There is no Drive leg.
- **Drive run** (`drive_required` / `drive_default` / `drive_optional`): nothing is written
  locally. Put both files into the run
  folder with `engagement put` (the bytes come on stdin; an identical re-put is a no-op), then
  record them and check the run:

  ```bash
  starboard-helper engagement put --run-folder $RUN_FOLDER --path analysis/query.md <<'EOF'
  <the report Markdown>
  EOF
  starboard-helper engagement put --run-folder $RUN_FOLDER --path README.md <<'EOF'
  <the README index, with a one-line pointer to analysis/query.md>
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
- 2: query not found — verify query ID
- 3: API error — check workspace connectivity
- 7 on a `--run-folder` run whose `error` starts with `BLOCKED_ACCESS`, `STORAGE_INTEGRITY`, `NOT_FOUND`
  or `STORAGE_ERROR`: a storage / integrity / access failure — stop and report `error` verbatim
