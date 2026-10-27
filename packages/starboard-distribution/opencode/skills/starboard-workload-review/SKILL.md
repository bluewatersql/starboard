---
name: starboard-workload-review
description: 'Review a Databricks workspace''s jobs, SQL queries, and warehouses — plus opt-in DLT pipelines, ML/model-serving, and Vector Search surfaces — the way a code review reviews code: a ranked, evidence-cited set of findings with severity, impact/effort scores, and remediation, over public system.* data only. Use when the user wants a workload review, an optimization/health assessment of jobs/queries/warehouses/pipelines/ML/vector-search, or prioritized findings with citations.'
compatibility: opencode
metadata:
  source: packages/starboard-skills/skills/starboard/starboard-workload-review/SKILL.md
---

# Starboard: Workload Review

Review a workspace's **jobs, SQL queries, and warehouses** and emit a ranked,
evidence-cited set of findings — the way the host's code-review pass reviews
code — built from harvested review methodology running on **public `system.*`
data only**.
Each finding carries a severity, an impact/effort priority score, a paraphrased
remediation, and an **evidence citation** (the query-pack `query_id` + the row
that triggered it).

> **Routing.** For a workspace health read (proactive, weekly, monthly or QBR) use
> [`starboard-health-review`](../starboard-health-review/SKILL.md); to troubleshoot one job, run,
> query or pipeline as a focused case use [`starboard-troubleshoot`](../starboard-troubleshoot/SKILL.md).
> Each is its own run (one task per run).

## Review domains

The default scope is **jobs + sql + warehouse**. Additional **opt-in** domains
extend the same rule engine over query packs that are already present — pass them
via `--domains`:

| Domain token | Covers | Example findings |
|---|---|---|
| `jobs` (default) | Job runs & reliability | high failure rate, wasted-DBU retries, runtime variance |
| `sql` (default) | Query performance | `SELECT *` wide projection, non-sargable partition filters |
| `warehouse` (default) | SQL warehouses | auto-stop disabled, persistently under-utilized |
| `uc` | Unity Catalog tables | missing table maintenance |
| `dlt` (alias `pipelines`) | DLT / Lakeflow pipelines | high update failure rate, stale pipelines, classic→serverless candidates |
| `ml` | ML & model serving | billed test/demo endpoints to clean up, noisy MLflow experiments |
| `vector-search` | Vector Search | idle (billed, unqueried) endpoints, top-DBU right-sizing targets |

The opt-in domains are **additive** — v1 defaults and their findings are
unchanged, and each new finding still cites its evidence `query_id` + row. All `$`
framing is a **list-price DBU estimate**, never a finance-grade figure.

## You are the analyst

**You** are the LLM for this skill. The skill hands you deterministic review
findings; **you** read the ranked findings and evidence citations and write the
workload review report yourself.

Do **not** call the `starboard` goal agent, an MCP `*_analysis` / `synthesize_*`
tool, a model-serving endpoint, or any other model. There is no second LLM in
this loop — the data step below runs deterministic Python (no LLM), and you do
the reasoning. Handing analysis to another model defeats the point of the skill
and breaks when that model's credentials differ from your session's.

## Step 1 — Confirm inputs and set up the run

Before loading data, confirm the run parameters with the user — but **only ask
for what they haven't already given**. If their request already specifies a value
(e.g. "review jobs for the last 60 days"), use it and skip that question. If they
say "just go" / "use defaults", proceed with the defaults.

Ask for (with defaults):

- **Lookback window** — how many days of history to include (default: **30**).
- **Domains** — jobs, sql, and warehouse are on by default; add `dlt`, `ml`, or
  `vector-search` if the user mentions pipelines, ML, or Vector Search. Default:
  **all default domains** (`jobs,sql,warehouse`).
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

## Step 2 — Load the data (deterministic Python, no LLM)

Run the bundled Workload Review script. It executes the full review end-to-end
against the resolved workspace — query packs + rule scoring, **no LLM** — and
emits the stable JSON envelope (`{ok, domain, command, data|error, meta}`). The **portable**
invocation runs on any host (Claude Code, Codex, OpenCode, `databricks aitools`). Always pass the
user's `--profile <name>`.

**Drive run** (`drive_required` / `drive_default` / `drive_optional`): a review into a run folder reads a discovery run in that
folder; a live customer review cannot write to a run folder and is refused. So capture the rows
with discovery first, then review them. The review writes `analysis/review.json`,
`analysis/review.md` and `findings-manifest.json` into the run folder and prints only a bounded
summary; nothing is written locally (a local `--out` is refused):

```bash
# 1. Capture the rows into the run folder (pass the user's --profile <name>)
starboard --discover --profile <profile> --lookback-days 30 --data-only --json \
  --out-dir discovery --run-folder $RUN_FOLDER
starboard-helper engagement commit --run-folder $RUN_FOLDER --stage capture

# 2. Review the saved rows (offline; scope and lookback come from the discovery run)
starboard review --json --run-folder $RUN_FOLDER --from-discovery discovery
```

To widen the window, pass a larger `--lookback-days` to the discovery call.

Read the result with
`starboard-helper engagement read --run-folder $RUN_FOLDER --path analysis/review.json`.

**Local run** (`local` / `internal_only_local`): write the envelope to files in `<run-dir>`:

```bash
starboard review --json --profile <profile> --out <run-dir>/analysis/review.json \
  --manifest-out <run-dir>/findings-manifest.json
starboard review --json --profile <profile> --domains warehouse,sql --lookback-days 60 \
  --out <run-dir>/analysis/review.json

# After a discovery run (--out-dir <run-dir>/discovery): review its saved rows
starboard review --json --from-discovery <run-dir>/discovery \
  --out <run-dir>/analysis/review.json --manifest-out <run-dir>/findings-manifest.json
```

To save the envelope, use `--out <path>`, never `> review.json 2>&1` (that mixes the banner and
logs into the JSON).

**When a discovery run exists, use `--from-discovery`** (after discovery has finished —
never concurrently). It evaluates the same rules on the discovery results already on disk
(`raw/<pack>.json`, fallback `discovery.json`): fully offline — no queries, no workspace
connection, no auth — with the workspace scope and lookback inherited from the discovery
output, so the review agrees with discovery. A query skipped in discovery (including one that
timed out after the automatic retries) degrades its domain: the review and the manifest carry
`degraded`, `unavailable_queries` and `unavailable_domains`, and a later `--since` / recur marks
those domains "not comparable". `data.evidence_source` records the provenance (path, lookback,
`unavailable` reasons, `limit_reached_query_ids`) and each finding carries
`evidence_limit_reached`. `--manifest-out` / `--since` behave the same. A standalone review with no discovery run keeps
the commands above.

`unavailable_queries` lists only the skipped queries that a review rule reads. The manifest also
carries `discovery_skipped` (every query discovery skipped) and `coverage_note` (which of those no
rule uses). An empty `unavailable_queries` with a non-empty `discovery_skipped` means "the skipped
queries feed no review rule", not full coverage: quote `coverage_note`. `review.json` carries the same
fields under `.data` (the JSON envelope), so read `.data.coverage_note`, not `.coverage_note`.

**Rules that match catalog ids.** Four review rules raise the same signals as the action-plan
opportunity catalog, so the manifest and `cost_delta` follow what the backlog carries:
`job_cron_overlap` → OPP-JOB-OVERLAP, `spend_step_change` → OPP-STEP-CHANGE,
`warehouse_recent_resize` → OPP-WH-RESIZE, `job_wait_tasks` → OPP-JOB-WAIT-TASK. A finding from
one of them is a candidate for that id. The catalog's verify, tier and sizing rules still decide
the backlog item.

Requires `pip install "starboard @ git+https://github.com/bluewatersql/starboard.git#subdirectory=packages/starboard"` (the server package supplies the SDK-backed
pack execution).

### What comes back

- `data.findings` — ranked findings; each has `finding` (severity, score,
  category, summary, rationale, current_state, suggested_fix) and `evidence`
  (a list of `{query_id, row_index, row}` citations).
- `data.domain_reports` — per-domain coverage and whether a domain `degraded`
  (partial evidence).
- `data.cost_basis` — the public $ basis label; findings are DBU / utilization
  based (a **list-price estimate**, never a finance-grade figure).

### Offline scoring (pure, pre-fetched rows)

When you already have query-pack rows and want to score them without touching the
workspace, use the pure SDK-free helper:

```bash
python -m starboard_x.review score --run-folder $RUN_FOLDER --rows raw/rows.json \
  --domains jobs,sql,warehouse
python -m starboard_x.review score --rows <run-dir>/raw/rows.json --domains jobs,sql,warehouse
```

On a Drive run the first form writes `analysis/review.json` and `findings-manifest.json` into the
run folder (a local `--rows` file is refused). `rows.json` maps each evidence `query_id` to a list of row objects
(e.g. `{"W-W02": [{"warehouse_id": "wh1", "auto_stop_waste_pct": 80.0}]}`).

### Fallback — assemble from starboard-helper

If the bundled script is unavailable, gather per-domain inputs with
`starboard-helper` and score them with the offline helper above. These fetches
can be large (busy fleets, long query history), so write each to a file with
`--out` and **read the file** — this avoids truncating the payload in the tool
result:

```bash
starboard-helper job list --profile <profile> --out <run-dir>/raw/jobs.json
starboard-helper query history --profile <profile> --out <run-dir>/raw/query-history.json
starboard-helper warehouse list --profile <profile> --out <run-dir>/raw/warehouses.json
```

`--out FILE` writes the full envelope to `FILE` and prints a compact summary
(row count + path) to stdout; read `FILE` for the rows. On a Drive run add
`--run-folder $RUN_FOLDER` and give run relpaths (`--out raw/jobs.json`), then read each with
`starboard-helper engagement read --run-folder $RUN_FOLDER --path raw/jobs.json`. Shape them into the
`{query_id: [rows]}` map and run `python -m starboard_x.review score`.

## Step 3 — Analyze the findings yourself

Read the ranked findings from `data.findings` and assess the workspace:

- **Severity and score** — which findings are critical / high / medium / low?
- **Evidence citations** — each finding cites `query_id` + row; confirm the data
  supports the finding.
- **Domain coverage** — note any `degraded` domains where evidence is partial.
- **Cost exposure** — surface list-price DBU estimates from findings; always label
  as *list-price estimates*.

## Step 4 — Produce the workload review

Present findings highest-priority first; cite the `query_id` + row for each:

1. **Executive summary** — overall workspace health in 2–3 sentences
2. **Ranked findings** — severity, score, category, summary, evidence citation,
   and suggested fix per finding
3. **Domain coverage** — which domains were reviewed and any degraded coverage
4. **Recommended actions** — top 3–5 remediations ordered by impact

`$` figures are **list-price DBU estimates** — label them as such.

### Offer to save the report

After presenting the findings, **offer** to save them as a Markdown report:

> "Want me to save this as a report? I'll write it to `analysis/workload-review.md` in this run (its
> Drive run folder, or its run dir under `./starboard-reports/`)."

If the user accepts, write the report to `analysis/workload-review.md` in the run and add a
`README.md` index with a one-line pointer to the report. Confirm where you wrote it. Don't write
anything unless the user opts in. Inside an engagement run the engagement's deliver beat publishes
it; skip the rest of this step.

- **Local run** (`local` / `internal_only_local`): write `<run-dir>/analysis/workload-review.md` and
  `<run-dir>/README.md`. There is no Drive leg.
- **Drive run** (`drive_required` / `drive_default` / `drive_optional`): nothing is written
  locally. Put both files into the run
  folder with `engagement put` (the bytes come on stdin; an identical re-put is a no-op), then
  record them and check the run:

  ```bash
  starboard-helper engagement put --run-folder $RUN_FOLDER --path analysis/workload-review.md <<'EOF'
  <the report Markdown>
  EOF
  starboard-helper engagement put --run-folder $RUN_FOLDER --path README.md <<'EOF'
  <the README index, with a one-line pointer to analysis/workload-review.md>
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
- 1: authentication error — check the workspace profile / `DATABRICKS_HOST` + `DATABRICKS_TOKEN`
- 2: resource not found
- 3: API error — check workspace connectivity
- 4: argument error — check `--domains` / `--rows`
- 7 on a `--run-folder` run whose `error` starts with `BLOCKED_ACCESS`, `STORAGE_INTEGRITY`, `NOT_FOUND`
  or `STORAGE_ERROR`: a storage / integrity / access failure — stop and report `error` verbatim
