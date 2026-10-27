---
name: starboard-cluster
description: "Analyze Databricks clusters — inspect configuration, review events, diagnose failures, and recommend optimizations. Use when the user asks about cluster performance, autoscaling, node types, cluster failures, or compute sizing."
allowed-tools: Bash(starboard-helper:*), Read, Write
---

# Starboard: Cluster Analysis

Analyze Databricks clusters — inspect configuration, review events, diagnose
failures, and recommend optimizations.

## You are the analyst

**You** are the LLM for this skill. The skill hands you deterministic cluster
data; **you** read the configuration, events, and metrics and write the assessment
and recommendations yourself.

Do **not** call the `starboard` goal agent, an MCP `*_analysis` / `synthesize_*`
tool, a model-serving endpoint, or any other model. There is no second LLM in
this loop — the data step below uses plain CLI fetches (no LLM), and you do the
reasoning. Handing analysis to another model defeats the point of the skill and
breaks when that model's credentials differ from your session's.

## Step 1 — Confirm inputs and set up the run

Before loading data, confirm the run parameters with the user — but **only ask
for what they haven't already given**. If their request already specifies a value
(e.g. "check cluster 0123-456789-abc"), use it and skip that question. If they
say "just go" / "use defaults", proceed with the defaults.

Ask for (with defaults):

- **Which clusters** — all running clusters, or a specific cluster ID / name?
  Default: **all running clusters**.
- **Events lookback window** — how many recent events to fetch per cluster
  (default: **50**).
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

Use `starboard-helper` to fetch cluster data. The commands are pre-approved by
this skill's `allowed-tools`, so they run without a permission prompt:

```bash
starboard-helper cluster list --profile <profile>
starboard-helper cluster list --profile <profile> --filter-by-state RUNNING
starboard-helper cluster fetch --profile <profile> --cluster-id <CLUSTER_ID>
starboard-helper cluster events --profile <profile> --cluster-id <CLUSTER_ID> --limit 50 --out events.json
starboard-helper cluster spark-context --profile <profile> --cluster-id <CLUSTER_ID> --out spark-context.json
```

`events` and `spark-context` can be large — add `--out FILE` (as above) to write
the full result to `FILE` and print a compact summary to stdout, then **read
`FILE`** instead of the truncated inline output. `--out` works on any verb and
may go before or after the subcommand.

## Step 3 — Analyze the data yourself

Read the returned configuration and events:

- **Sizing** — is the node type and worker count appropriate for the workload?
- **Autoscaling** — is autoscale configured and within appropriate min/max bounds?
- **Events** — are there recurring error events (OOM, node lost, preemption)?
- **Spark config** — are there performance-relevant configs set (shuffle
  partitions, memory fractions)?
- **Lifespan** — are long-running clusters accumulating state, or should they be
  ephemeral?
- **Source** — are clusters created interactively (risk) vs. job-attached
  (preferred for production)?

### Right-sizing + cost impact

Using the fetched config (node type, worker count, autoscale bounds) plus any
utilization signals, classify each cluster's sizing direction and project the
list-price cost impact:

- **Over-provisioned** (low CPU/memory p95): recommend a smaller node SKU or
  fewer/lower autoscale-min workers; estimate the `reduction_pct` and the
  **list-price DBU $/month** saved.
- **Under-provisioned** (high CPU/memory p95, autoscale pinned at max):
  recommend raising the autoscale max or a larger SKU.
- **Balanced**: no action.

Project cost as a **list-price DBU estimate**:
`monthly_cost ≈ dbus_per_day × 30 × list_price_per_dbu` and
`monthly_savings ≈ monthly_cost × reduction_pct / 100`. Always label the figure a
*list-price DBU estimate* — it is not a contracted-rate cost.

## Step 4 — Produce the report

1. Cluster fleet overview
2. Right-sizing recommendations with list-price DBU $/month impact
3. Event-based failure diagnosis
4. Spark configuration tuning suggestions
5. Priority: critical / high / medium / low

### Offer to save the report

After presenting the findings, **offer** to save them as a Markdown report:

> "Want me to save this as a report? I'll write it to `analysis/cluster.md` in this run (its
> Drive run folder, or its run dir under `./starboard-reports/`)."

If the user accepts, write the report to `analysis/cluster.md` in the run and add a
`README.md` index with a one-line pointer to the report. Confirm where you wrote it. Don't write
anything unless the user opts in. Inside an engagement run the engagement's deliver beat publishes
it; skip the rest of this step.

- **Local run** (`local` / `internal_only_local`): write `<run-dir>/analysis/cluster.md` and
  `<run-dir>/README.md`. There is no Drive leg.
- **Drive run** (`drive_required` / `drive_default` / `drive_optional`): nothing is written
  locally. Put both files into the run
  folder with `engagement put` (the bytes come on stdin; an identical re-put is a no-op), then
  record them and check the run:

  ```bash
  starboard-helper engagement put --run-folder $RUN_FOLDER --path analysis/cluster.md <<'EOF'
  <the report Markdown>
  EOF
  starboard-helper engagement put --run-folder $RUN_FOLDER --path README.md <<'EOF'
  <the README index, with a one-line pointer to analysis/cluster.md>
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
- 2: cluster not found — verify cluster ID
- 3: API error — check workspace connectivity
- 7 on a `--run-folder` run whose `error` starts with `BLOCKED_ACCESS`, `STORAGE_INTEGRITY`, `NOT_FOUND`
  or `STORAGE_ERROR`: a storage / integrity / access failure — stop and report `error` verbatim
