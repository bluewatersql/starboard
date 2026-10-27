---
name: starboard-finops
description: "Analyze Databricks cost and usage — load list-price DBU consumption from system.billing.usage, review budgets, and identify cost optimization opportunities. Use when the user asks about spend, billing, cost drivers, budgets, or FinOps and cost optimization."
allowed-tools: Bash(python -m starboard_x.discovery *), Bash(starboard-helper:*), Read, Write
---

# Starboard: FinOps Analysis

Analyze Databricks cost and usage — load DBU consumption from Unity Catalog
system tables, review budgets, and identify cost optimization opportunities.

## You are the analyst

**You** are the LLM for this skill. The skill hands you deterministic usage and
billing data; **you** read the rows and write the cost assessment and
recommendations yourself.

Do **not** call the `starboard` goal agent, an MCP `*_analysis` / `synthesize_*`
tool, a model-serving endpoint, or any other model. There is no second LLM in
this loop — the data step below runs plain Python / CLI fetches (no LLM), and you
do the reasoning. Handing analysis to another model defeats the point of the
skill and breaks when that model's credentials differ from your session's.

## Step 1 — Confirm inputs

Before loading data, confirm the run parameters with the user — but **only ask
for what they haven't already given**. If their request already specifies a value
(e.g. "show me billing for the last 90 days"), use it and skip that question. If
they say "just go" / "use defaults", proceed with the defaults.

Ask for (with defaults):

- **Lookback window** — how many days of billing history to include (default:
  **30**).
- **Workspace / profile** — which `--profile <name>` to use. Ask the user which profile
  reaches the workspace; never pick one yourself.

## Step 2 — Load the data (deterministic, no LLM)

### Workspace cost data (preferred — no account-admin required)

Cost/usage on the workspace-read-only path comes from `system.billing.usage`
(list-price **DBU quantities**, not dollars). Run the bundled helper — it
executes the billing query pack out-of-context in Python and, with `--out-dir`,
**streams the rows to disk** and prints only a compact manifest to stdout. This keeps a large
billing payload from being truncated in the tool result.

Inside an engagement run, beat 0 already set the run up: use its `$RUN_FOLDER` (or
`<run-dir>`). For a standalone cost review, set the run up first, before any query:

```bash
starboard-helper engagement preflight --task review --task-name ws-<workspace_id> \
  --account-key <account_key> --account-name "<account name>" --source-mode customer_workspace
starboard-helper engagement verify-identity --run-id <run_id> --profile <profile> \
  --expected-workspace-id <workspace_id>
starboard-helper engagement route --run-id <run_id>
```

Keep preflight's `run_id`. Always pass `--profile <name>` with the profile the user chose. Take
the workspace ID from the user or the workspace, never from a profile name. A verify-identity
mismatch exits non-zero and quarantines the run: stop and show `error`. A refusal exits 2 with `LOCAL_STORAGE_REFUSED` or `STORAGE_UNAVAILABLE`: the `engagement` envelope carries it as `errors[0].code` (show `errors[0].message` verbatim), any other helper starts its top-level `error` with it (show `error` verbatim). Stop. A preflight `STORAGE_UNAVAILABLE` returns `run_id: null` and creates nothing: re-run the same preflight once the storage adapter is installed (a local run never needs it).

Then act on preflight's `storage_decision`. The **portable** engine invocation runs on any host
(Claude Code, Codex, OpenCode, `databricks aitools`):

- **`drive_required`** (an install with the internal overlay), **`drive_default`** (an
  internal-only install) or **`drive_optional`** (a public install where the operator chose
  `--storage drive`): route returns `run_folder_id`
  (`$RUN_FOLDER`) and **nothing is written locally**. The rows stream into the run folder:

  ```bash
  python -m starboard_x.discovery run --data-only --packs billing --run-folder $RUN_FOLDER \
    --profile <profile>
  ```

  Then record the capture with
  `starboard-helper engagement commit --run-folder $RUN_FOLDER --stage capture`.
- **`local`** (a public install without `--storage drive`) or **`internal_only_local`**:
  `<run-dir>` is preflight's
  `data.local_run_dir`, and route writes `<run-dir>/analysis/run-authorization.json`:

  ```bash
  python -m starboard_x.discovery run --data-only --packs billing \
    --out-dir <run-dir>/finops --authorization <run-dir> --profile <profile>
  ```

Widen the window with `--lookback-days`, and pass the user's `--profile <name>`:

```bash
python -m starboard_x.discovery run --data-only --packs billing \
  --run-folder $RUN_FOLDER --lookback-days 90 --profile <profile>
python -m starboard_x.discovery run --data-only --packs billing \
  --out-dir <run-dir>/finops --authorization <run-dir> --lookback-days 90 --profile <profile>
```

Any non-zero exit: stop and report the `error`. Never retry without the run (`--run-folder` or
`--authorization`). A failed write prints `resume`: re-run with
`starboard-helper engagement preflight --resume-run-id <run_id>`.

Then read the billing rows **from disk**, not from stdout:

1. **Read the manifest** printed to stdout (`data.manifest[]`) — the `billing`
   entry gives the query/row counts, a `limit_reached` flag (row cap hit), and the `path` to the
   raw file.
2. **Read the raw file** at that `path`: on a Drive run,
   `starboard-helper engagement read --run-folder $RUN_FOLDER --path raw/billing.json`; on a local
   run, `<run-dir>/finops/raw/billing.json`. Each
   `results[]` query carries the **actual rows** (`columns` + `rows`) — DBU
   consumption by `billing_origin_product` / `sku_name` and by month.
   > **Large or row-capped packs.** If the per-query entry shows `"limit_reached": true`
   > or the raw file is very large, prefer a **summarize-then-reason** pass — use
   > `jq` or Python to pull top-N-by-DBU and per-month aggregates rather than
   > loading the whole file into context.

`data.domain_analyses` here holds only deterministic `kind: "data_only_summary"` entries
(per-domain counts and row pointers; no grade or findings: proof no LLM ran). Requires
`pip install "starboard-kernel[discovery] @ git+https://github.com/bluewatersql/starboard.git#subdirectory=packages/starboard-core"`.

### Account-level billing (optional — requires account-admin credentials)

`finops usage` runs `system.billing.usage` SQL on a warehouse you name, as the
workspace `--profile <profile>` (on a `--run-folder` run it defaults to the run's verified
profile; another profile is refused with `PROFILE_MISMATCH`). `finops budgets` and
`finops log-delivery` use the Account API: their `--profile` is an **account-admin**
profile (accounts-console host + `account_id`), never the run's workspace profile, and
they return "Not Found" on a plain workspace token, so they are optional:

```bash
starboard-helper finops usage --profile <profile> --warehouse-id <WH_ID> --start-date YYYY-MM-DD --end-date YYYY-MM-DD --out <run-dir>/raw/usage.json
starboard-helper finops budgets --profile <account-profile>
starboard-helper finops log-delivery --profile <account-profile>
```

Account-level `usage` can span many rows — `--out FILE` writes the full envelope
to `FILE` and prints a compact summary (row count + path) to stdout; **read
`FILE`** rather than the truncated inline output. `--out` works on any verb and
may go before or after the subcommand. On a Drive run, write it into the run instead:
`--run-folder $RUN_FOLDER --out raw/usage.json`, then read it with `engagement read`.

## Step 3 — Analyze the data yourself

Read the returned usage/billing rows:

- **Cost drivers** — which products/SKUs (Jobs Compute, SQL Compute, All-Purpose)
  dominate DBU consumption?
- **Trends** — is consumption increasing month-over-month? Which workloads are
  growing?
- **Waste** — All-Purpose clusters with low utilization (idle cost), oversized
  compute.
- **Budget alerts** (if account data available) — are any budgets close to or
  exceeding thresholds?
- **Optimization levers** — spot instances, serverless SQL, ephemeral job clusters.

## Step 4 — Produce the report

1. Consumption summary by product/SKU and time period
2. Top cost drivers
3. Waste identification (idle resources, oversized clusters)
4. Specific optimization actions with estimated savings
5. Priority: critical / high / medium / low

`$` figures are **list-price DBU estimates** — label them as such.

### Offer to save the report

After presenting the findings, **offer** to save them as a Markdown report:

> "Want me to save this as a report? I'll write it to `analysis/finops.md` in this run (its
> Drive run folder, or its run dir under `./starboard-reports/`)."

If the user accepts, write the report to `analysis/finops.md` in the run the setup above
created, and add a `README.md` index with a one-line pointer to the report. Confirm where you
wrote it. Don't write anything unless the user opts in. Inside an engagement run the engagement's
deliver beat publishes it; skip the rest of this step.

- **Local run** (`local` / `internal_only_local`): write `<run-dir>/analysis/finops.md` and
  `<run-dir>/README.md`. There is no Drive leg.
- **Drive run** (`drive_required` / `drive_default` / `drive_optional`): nothing is written
  locally. Put both files into the run
  folder with `engagement put` (the bytes come on stdin; an identical re-put is a no-op), then
  record them and check the run:

  ```bash
  starboard-helper engagement put --run-folder $RUN_FOLDER --path analysis/finops.md <<'EOF'
  <the report Markdown>
  EOF
  starboard-helper engagement put --run-folder $RUN_FOLDER --path README.md <<'EOF'
  <the README index, with a one-line pointer to analysis/finops.md>
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

- 0: success
- 1: authentication error — check `DATABRICKS_HOST` / `DATABRICKS_TOKEN` (or `--profile`)
- 2: resource not found
- 3: API error — check workspace connectivity
- 4: bad arguments (e.g. an unknown `--packs` value)
- 7 on a `--run-folder` run whose `error` starts with `BLOCKED_ACCESS`, `STORAGE_INTEGRITY`, `NOT_FOUND`
  or `STORAGE_ERROR`: a storage / integrity / access failure — stop and report `error` verbatim
