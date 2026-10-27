---
name: starboard-analyze
description: "Run a comprehensive, cross-domain analysis of a Databricks workload — combining job, cluster, query, and cost data into a unified optimization report. Use when the user asks for an overall workload review, a full optimization report, or a combined health-and-cost assessment spanning multiple domains."
allowed-tools: Bash(starboard-helper:*), Read, Write
---

# Starboard: Comprehensive Analysis

Run a comprehensive analysis of a Databricks workload — combining job, cluster,
query, and cost data into a unified optimization report.

> **Routing.** For a workspace health read (proactive, weekly, monthly or QBR) use
> [`starboard-health-review`](../starboard-health-review/SKILL.md); to troubleshoot one job, run,
> query or pipeline as a focused case use [`starboard-troubleshoot`](../starboard-troubleshoot/SKILL.md).
> Each is its own run (one task per run).

## You are the analyst

**You** are the LLM for this skill. The skill hands you deterministic data from
multiple domains; **you** synthesize the cross-domain findings and write the
unified report yourself.

Do **not** call the `starboard` goal agent, an MCP `*_analysis` / `synthesize_*`
tool, a model-serving endpoint, or any other model. There is no second LLM in
this loop — the data step below uses plain CLI fetches (no LLM), and you do the
reasoning. Handing analysis to another model defeats the point of the skill and
breaks when that model's credentials differ from your session's.

## Step 1 — Confirm inputs and set up the run

Before loading data, confirm the run parameters with the user — but **only ask
for what they haven't already given**. If their request already specifies a value
(e.g. "analyze the last 60 days"), use it and skip that question. If they say
"just go" / "use defaults", proceed with the defaults.

Ask for (with defaults):

- **Lookback window** — how many days of history to include (default: **30**).
- **Scope** — all domains, or focus on specific ones (jobs, clusters, queries,
  cost)? Default: **all**.
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

A refusal exits 2 with `LOCAL_STORAGE_REFUSED` or `STORAGE_UNAVAILABLE`: the `engagement` envelope carries it as `errors[0].code` (show `errors[0].message` verbatim), any other helper starts its top-level `error` with it (show `error` verbatim). Stop. A preflight `STORAGE_UNAVAILABLE` returns `run_id: null` and creates nothing: re-run the same preflight once the storage adapter is installed (a local run never needs it). Setup writes no report; the report is written only if the user
opts in (see the save step).

## Step 2 — Load the data (deterministic, no LLM)

Determine what to analyze from user input (job ID, cluster ID, warehouse ID, or a
named workload), then fetch data across all relevant domains. The commands are
pre-approved by this skill's `allowed-tools`, so they run without a permission
prompt:

```bash
# Gather data from all relevant domains
starboard-helper job fetch --profile <profile> --job-id <JOB_ID>
starboard-helper job runs --profile <profile> --job-id <JOB_ID> --limit 10
starboard-helper diagnostic run-state --profile <profile> --run-id <LATEST_RUN_ID>
starboard-helper cluster fetch --profile <profile> --cluster-id <CLUSTER_ID>
starboard-helper cluster events --profile <profile> --cluster-id <CLUSTER_ID> --limit 50
```

Run additional commands as the workload scope demands (warehouse, query, finops).

## Step 3 — Analyze the data yourself

Read the returned data and connect findings across domains:

- **Job → Cluster** — does job configuration match cluster sizing for the
  workload?
- **Run history → Events** — do cluster error events correlate with job failures?
- **Duration trends → Cost** — is increasing run duration driving cost growth?
- **Retry patterns → Failure modes** — are failures transient (retry works) or
  systematic?

## Step 4 — Produce the comprehensive report

1. **Executive summary** — overall health in 2–3 sentences
2. **Critical issues** — immediate action required
3. **Performance analysis** — bottlenecks and optimization opportunities
4. **Cost analysis** — waste and rightsizing opportunities
5. **Recommended actions** — ordered by impact, with specific implementation steps
6. **Estimated impact** — time/cost savings from top recommendations

`$` figures are **list-price DBU estimates** — label them as such.

### Offer to save the report

After presenting the findings, **offer** to save them as a Markdown report:

> "Want me to save this as a report? I'll write it to `analysis/analyze.md` in this run (its
> Drive run folder, or its run dir under `./starboard-reports/`)."

If the user accepts, write the report to `analysis/analyze.md` in the run and add a
`README.md` index with a one-line pointer to the report. Confirm where you wrote it. Don't write
anything unless the user opts in. Inside an engagement run the engagement's deliver beat publishes
it; skip the rest of this step.

- **Local run** (`local` / `internal_only_local`): write `<run-dir>/analysis/analyze.md` and
  `<run-dir>/README.md`. There is no Drive leg.
- **Drive run** (`drive_required` / `drive_default` / `drive_optional`): nothing is written
  locally. Put both files into the run
  folder with `engagement put` (the bytes come on stdin; an identical re-put is a no-op), then
  record them and check the run:

  ```bash
  starboard-helper engagement put --run-folder $RUN_FOLDER --path analysis/analyze.md <<'EOF'
  <the report Markdown>
  EOF
  starboard-helper engagement put --run-folder $RUN_FOLDER --path README.md <<'EOF'
  <the README index, with a one-line pointer to analysis/analyze.md>
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
- 2: resource not found
- 3: API error — check workspace connectivity
- 7 on a `--run-folder` run whose `error` starts with `BLOCKED_ACCESS`, `STORAGE_INTEGRITY`, `NOT_FOUND`
  or `STORAGE_ERROR`: a storage / integrity / access failure — stop and report `error` verbatim
