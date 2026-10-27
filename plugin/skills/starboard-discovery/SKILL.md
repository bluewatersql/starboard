---
name: starboard-discovery
description: "Discover and map a Databricks workspace — enumerate jobs, clusters, warehouses, and Unity Catalog assets to build a comprehensive inventory. Use when the user wants a workspace inventory, a health assessment, or to explore what exists in a workspace."
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/run.sh *), Bash(starboard-helper:*), Read, Write
---

# Starboard: Workspace Discovery

> **Run checklist:** an engagement run must satisfy the `starboard-engagement` skill's
> `references/run-checklist.md` (`starboard-helper run check <run-dir>` enforces it).

Discover and map a Databricks workspace — enumerate jobs, clusters, warehouses,
and Unity Catalog assets to build a comprehensive inventory.

> **Routing.** For a workspace health read (proactive, weekly, monthly or QBR) use
> [`starboard-health-review`](../starboard-health-review/SKILL.md); to troubleshoot one job, run,
> query or pipeline as a focused case use [`starboard-troubleshoot`](../starboard-troubleshoot/SKILL.md).
> Each is its own run (one task per run).

## You are the analyst

**You** are the LLM for this skill. The skill hands you deterministic workspace
data; **you** read the rows and write the inventory, observations, and
recommendations yourself.

Do **not** call the `starboard` goal agent, an MCP `*_analysis` / `synthesize_*`
tool, a model-serving endpoint, or any other model. There is no second LLM in
this loop — the data steps below run pure Python (no LLM), and you do the
reasoning. Handing analysis to another model defeats the point of the skill and
breaks when that model's credentials differ from your session's.

## Invocation

> **Overlay routing.** If an internal overlay skill is installed or loaded in this
> session, **follow that skill's discovery invocation instead of the commands
> below** — it supersedes this portable default for that context. A bare numeric
> workspace id or account id with no matching `--profile` entry usually means the
> overlay's no-connect path applies; load the overlay skill first before choosing
> a discovery path.
>
> **What an overlay replaces — and what it doesn't.** An overlay's discovery
> invocation replaces **only Steps 1–2** (confirm inputs, run setup and plan) and **the discovery
> command** (the `run --only --out-dir` call in Step 4). **Steps 4–6 are still
> REQUIRED:** write `discovery/domains/<domain>.md` from the overlay's envelope
> (Step 4 analysis: the discovery command never writes these files — you do, one per
> domain, from that domain's `data.domain_analyses` entry and its pack rows), `discovery/analysis.md` with the graded report card plus
> `README.md` (Step 5), and present the findings (Step 6).

> **Stay out of source.** To run an engagement use the skills and each command's
> `--help`; do **not** read `packages/` source. Column names and copy-paste SQL are in
> the engagement skill's `references/verify-sql.md` (or the overlay's own verify
> reference when an overlay applies). If a column isn't documented there, record the
> gap instead of grepping pack source.

The commands below use the **portable** engine invocation — it runs on any host
(Claude Code, Codex, OpenCode, `databricks aitools`):

```bash
python -m starboard_x.discovery <args>
```

<!-- claude-only -->
Under Claude Code, the pre-approved convenience wrapper
`${CLAUDE_SKILL_DIR}/scripts/run.sh <args>` runs the identical command with no
permission prompt.
<!-- /claude-only -->

## Step 1 — Confirm inputs

> **No-connect (bare workspace id) path:** skip Steps 1–2. The internal overlay's Beat 0 fixes the inputs (30-day lookback, no profile, `--internal-workspace-id`); there is nothing to confirm.

Before loading data, confirm the run parameters with the user — but **only ask
for what they haven't already given**. If their request already specifies a value
(e.g. "discover the workspace for the last 90 days"), use it and skip that
question. If they say "just go" / "use defaults", proceed with the defaults.

Ask for (with defaults):

- **Lookback window** — how many days of history to scan (default: **30**).
- **Workspace / profile** — which `--profile <name>` to use. Ask the user which profile
  reaches the workspace; never pick one yourself.
- **Scope** — the available domains are determined in Step 2 (the plan step
  always runs regardless); proceed with all recommended domains by default. If
  the user expresses a focus (e.g. "just jobs"), note it and let them confirm or
  trim the list after seeing the plan — do not skip Step 2.

## Step 2 — Set up the run, then plan

**Set up the run first, before any workspace query**, and do it **directly** (do not delegate to
a subagent). When discovery runs inside an engagement (an action plan or health review), the
engagement's beat 0 already did this: use its `$RUN_FOLDER` (or `<run-dir>`) and go to the plan.
Otherwise:

1. **Preflight** stages the run (never build a path or a Drive folder by hand):
   ```bash
   starboard-helper engagement preflight --task discovery --task-name ws-<workspace_id> \
     --account-key <account_key> --account-name "<account name>" --source-mode customer_workspace
   ```
   Keep `run_id` and read `storage_decision`. Take the workspace name from the workspace hostname
   (e.g. `e2-demo-field-eng`) and the ID from the workspace. A refusal exits 2 with
   `LOCAL_STORAGE_REFUSED` or `STORAGE_UNAVAILABLE`: the `engagement` envelope carries it as
   `errors[0].code` (show `errors[0].message` verbatim), any other helper starts its top-level
   `error` with it (show `error` verbatim). Stop. A preflight `STORAGE_UNAVAILABLE` returns
   `run_id: null` and creates nothing: re-run the same preflight once the storage adapter is
   installed (a local run never needs it). If Google Drive isn't authenticated (exit 3,
   `AUTH_REQUIRED`), show `errors[0].message` (it carries the sign-in step) and wait for the user
   to sign in. With `run_id: null` nothing was staged: re-run the same preflight. Otherwise
   continue the same run with
   `starboard-helper engagement preflight --resume-run-id <run_id>` and the same flags
   (drop `--storage`).
2. **Verify the workspace** behind the profile is the one you meant:
   ```bash
   starboard-helper engagement verify-identity --run-id <run_id> --profile <profile> \
     --expected-workspace-id <workspace_id>
   ```
   Always pass `--profile <name>` with the profile the user chose. The expected ID comes from the
   user or the workspace, never from a profile name. A mismatch exits non-zero and quarantines the
   run: stop, show `error`, and start a new run with preflight.
3. **Route the run**:
   ```bash
   starboard-helper engagement route --run-id <run_id>
   ```
   Act on `storage_decision`:
   - **`drive_required`** (an install with the internal overlay), **`drive_default`** (an
     internal-only install) or **`drive_optional`** (a public install where the operator chose
     `--storage drive`): route returns `run_folder_id`
     (`$RUN_FOLDER`), `run_link` and any `fallback_warning` (show it). **Nothing is written
     locally**: every discovery call below passes `--run-folder $RUN_FOLDER`, its `--out-dir` is a
     run-relative prefix (`--out-dir discovery`), and you read files back with
     `starboard-helper engagement read --run-folder $RUN_FOLDER --path <relpath>`. A local
     `--out-dir`, `--authorization` or `--stdout` is refused.
   - **`local`** (a public install without `--storage drive`) or **`internal_only_local`**:
     `<run-dir>` is preflight's
     `data.local_run_dir`; route writes `<run-dir>/analysis/run-authorization.json`, and every
     discovery call below passes `--authorization <run-dir>`.

A discovery run reads the workspace's system tables only: it never fetches a single job's logs,
cluster event logs or query profiles, and never notes that it didn't.

Then run the plan command to see what the workspace is using and which domains are worth
running. This executes only the audit pack — cheap, one query:

```bash
python -m starboard_x.discovery plan --lookback-days N --run-folder $RUN_FOLDER --profile <profile>
python -m starboard_x.discovery plan --lookback-days N --authorization <run-dir> --profile <profile>
```

The first form is the Drive run, the second the local run. Any non-zero exit: stop and report the
`error`; never retry without the run (`--run-folder` or `--authorization`).

Read the returned JSON:

- `data.products` — detected products with DBU weight (highest first)
- `data.recommended` — impact-ordered domains to run, each with its packs and
  DBU signal; always includes `billing` and `governance`
- `data.always_recommended` — domains worth running regardless of product mix
  (e.g. `billing`, `governance`)
- `data.contextual` — conditionally useful domains (e.g. `migration` when
  classic compute or classic warehouses are detected)
- `data.lookback_days` — confirmed lookback in use

Present an **impact-first menu** of the domains you plan to run, ordered by DBU
weight (highest first). Always-recommended domains (`billing`, `governance`)
appear regardless of weight. Include a contextual domain (e.g. `migration`) only
if `plan` flagged it under `contextual` or if the user asks for it.

**Proceed on "just go"** with all `recommended` domains (including
`always_recommended`). The user can trim the list or add a contextual domain
before you continue. A focused domain set is fine — you do not need every domain
for a useful report.

## Step 3 — Save the plan

Save the plan envelope immediately to `discovery/plan.json` — this is your
provenance record of what was chosen and why. On a local run use the `Write` tool (which creates
parent directories automatically):

```
Write → <run-dir>/discovery/plan.json
```

On a Drive run, never write it locally: put it into the run folder, the JSON on stdin (an
identical re-put is a no-op):

```bash
starboard-helper engagement put --run-folder $RUN_FOLDER --path discovery/plan.json <<'EOF'
<the plan envelope JSON>
EOF
```

## Step 4 — Run each domain incrementally

For each selected domain, run exactly its packs with `--only` and stream results
to disk with `--out-dir`. Do **not** run all domains in a single call — the
per-domain loop keeps individual payloads small and lets you persist analysis as
you go.

The scans run on an **existing** SQL warehouse; discovery never creates or picks
one. Ask the operator **"which existing SQL warehouse may discovery use?"** —
list the choices into the run with
`starboard-helper warehouse list --profile <profile> --run-folder $RUN_FOLDER --out raw/warehouses.json`
(local run: `--out <run-dir>/raw/warehouses.json`) — and pass the chosen ID as
`--warehouse-id` on every domain run.

```bash
# Drive run (drive_required / drive_default / drive_optional)
python -m starboard_x.discovery run \
  --only <pack> [<pack2> ...] \
  --out-dir discovery \
  --lookback-days N \
  --run-folder $RUN_FOLDER \
  --profile <profile> \
  --warehouse-id <warehouse_id>

# Local run (local / internal_only_local)
python -m starboard_x.discovery run \
  --only <pack> [<pack2> ...] \
  --out-dir <run-dir>/discovery \
  --lookback-days N \
  --authorization <run-dir> \
  --profile <profile> \
  --warehouse-id <warehouse_id>
```

An `internal_only` run (the internal overlay) has no profile and no warehouse to
choose: it captures with the overlay's internal form, and an `internal_only_local`
run passes `--authorization <run-dir>` with the internal flags — follow the
overlay, not the forms above.

If a domain run returns no succeeded query (`counts.succeeded` is 0), or every
failed query is a permission error, **stop and report** the errors: the warehouse
or the system-table grants are wrong. Never retry a permission error; only
timeouts are retried.

On a Drive run, record the capture after the last domain run with
`starboard-helper engagement commit --run-folder $RUN_FOLDER --stage capture`.

**Long captures.** Run every discovery command in the foreground with the host's longest
command timeout (Claude Code: Bash `timeout: 600000`); never in the background (no
`run_in_background`, `&` or `nohup`). A run's capture (`--run-folder`, or a local
`--authorization <run-dir>`) is resumable and stops itself before that limit: `--max-seconds N`
bounds it (default 480; `0` = no budget; run captures only). At the deadline it saves its
progress in the run (`capture/`) and exits 9 `CAPTURE_INCOMPLETE`
(`errors[0].retryable: true`; `data.progress` has `done`, `remaining` and `reused`, and
`data.resume` is the same command). Re-run the identical command until it exits 0: finished
queries are reused (`data.resumed.queries_reused` on the summary) and only the rest run. Do the
same when the host killed the command at its time limit. Changing a flag (window, `--only`,
scope) starts that capture fresh and `data.resumed.fresh_reason` says why; each `--only` domain
run is its own capture, so that is expected on the next domain. `--no-cache` does not turn resume
off. On a Drive run let stderr go to the terminal; never redirect stdout or stderr anywhere, or
`tee` them: not to a file, not under `/tmp`, and not to `/dev/null` (`2>/dev/null` hides the
warnings); to filter the output, pipe it.

`--lookback-days N` must be the same lookback window confirmed in Step 1 — use
it consistently on every domain run so all results share the same time window.

`--only` runs exactly those packs: no audit phase, no always-run injection. Use
the domain→packs mapping from `data.recommended` in the plan envelope to know
which packs feed each domain (e.g. `vector_search` may map to both
`vector_search` and `serverless_attribution` packs).

After each domain run:

1. **Read the manifest** from stdout (`data.manifest[]` — queries, row counts,
   truncation status, paths to raw files).
2. **Read the raw pack files** named in the manifest:
   ```
   Read → <run-dir>/discovery/raw/<pack>.json
   ```
   On a Drive run:
   `starboard-helper engagement read --run-folder $RUN_FOLDER --path discovery/raw/<pack>.json`
   (add `--max-bytes` for a bounded read).
   A raw pack file is **one pack, flat**: `{"domain", "pack", "results": [ … ]}` (top-level
   `results[]`, no `data` key). The combined `discovery.json` envelope nests the same result
   objects at `data.packs[].results[]`; script against the shape of the file you opened.
   > **Large files / row-capped packs.** For feature-dense workspaces, a `raw/<pack>.json` can
   > be very large and one or more queries may have hit the row cap (`"limit_reached": true` in
   > the per-query envelope). When a pack is large or capped, prefer a compact
   > **summarize-then-reason** pass: use `jq` or Python to extract salient rows or aggregates
   > per query (e.g. counts, top-N by cost, group-by summaries) and load only that condensed
   > view rather than reading the whole file into context. `limit_reached: true` means the
   > workspace total **exceeds** what the row cap emitted — trust the manifest counts plus a
   > targeted aggregate, not a naive full read. (`truncated` is a separate signal meaning the
   > serializer dropped rows from an oversized stdout payload — different from a row cap.)
3. **Analyze the rows** — examine query results for that domain: counts,
   patterns, cost signals, failure modes, configuration anti-patterns.
4. **Write the domain analysis immediately** — do not hold all domains in
   context before writing. The discovery command does not write these files; this step does.
   **Where the write-up starts on `--data-only`:** `data.domain_analyses` holds one
   deterministic entry per domain with `kind: "data_only_summary"`: its `packs`, the
   succeeded / skipped / failed counts, `query_row_counts`, `nonempty_query_ids`,
   `limit_reached_ids`, and pointers to the rows (`data_paths` into the envelope, `raw_paths`
   = `raw/<pack>.json` under `--out-dir`). It has **no grade, findings or judgement**: use it
   as the checklist of which queries returned rows and which were capped or skipped, then
   write the analysis from the rows in `raw/<pack>.json`. (When the full LLM pipeline ran, the
   entries are graded analyses instead; start each file from that domain's entry.)
   ```
   Write → <run-dir>/discovery/domains/<domain>.md
   ```
   On a Drive run, never write it locally; put it into the run folder instead:
   ```bash
   starboard-helper engagement put --run-folder $RUN_FOLDER --path discovery/domains/<domain>.md <<'EOF'
   <the domain write-up Markdown>
   EOF
   ```

Each `domains/<domain>.md` should follow the shape:

- **Summary** — one-paragraph domain overview and key findings
- **Observations** — notable patterns (e.g. job cluster attachment types,
  warehouse sizing gaps, governance coverage)
- **Findings** — specific issues with evidence (query name, row values) and
  remediation guidance
- **Recommended actions** — prioritized, actionable steps

`$` figures are **list-price DBU estimates** — label them as such.

> **W-W01 `utilization_ratio`.** Busy query-time ÷ wall-clock time. A value > 1 means queries
> overlapped (concurrency), **not** that the warehouse is saturated: 2.7 with 0.02% queued is a
> busy, healthy warehouse. Read saturation from `queued_query_pct` / `avg_capacity_wait_secs`.

> **Per-job reliability (`job_reliability_by_job`, F-12).** `discovery/facts.json` carries
> per-job `runs`, `failed_runs` and `cancelled_runs` (same per-run definition as the workspace
> `job_reliability`, F-06) for the **top 25 jobs** by `failed_runs`, then `runs`. It is a
> truncation (`per_job_cap_25`): a job outside the list is not "no failures". The field is null
> when F-12 didn't run. The workspace failure rate always comes from `job_reliability`, never
> from summing this list.

> **Coverage caveat.** Skipped queries (audit, lineage, instance events, statement text where the
> source doesn't carry them) are acceptable and don't fail the run, but name them in
> `analysis.md` and the README; never write as if coverage were complete.

> **Window semantics.** Pack windows written `>= CURRENT_DATE - N` span **N+1 calendar days**
> including the partial current day. Label such figures "last N days (incl. today)", or re-query
> with `< CURRENT_DATE` when an exact N-full-day figure matters (e.g. a headline window total).

> **Vector Search accuracy.** When analyzing the `vector_search` domain, lead with the
> **sprawl summary** (pack query P-VS06) and reconcile totals against
> `system.billing.usage` / `serverless_attribution` — do **not** lead with the row-capped
> per-endpoint list (P-VS01). The per-endpoint list can appear ~10× too small when rows are
> capped, which can invite a wrong "SKU-attribution artifact" conclusion. The real story
> is usually endpoint sprawl — many always-on endpoints sitting at the idle DBU floor —
> which shows clearly in billing aggregates even when the per-endpoint list is capped.

Persist each domain file before moving on. This keeps your working context
bounded regardless of how many domains you run.

## Step 5 — Unified rollup

After all domains are analyzed, write two summary files: into `<run-dir>` on a local run, or on a
Drive run put each into the run folder (the Markdown on stdin), both before the analysis commit:

```bash
starboard-helper engagement put --run-folder $RUN_FOLDER --path discovery/analysis.md <<'EOF'
<the unified rollup Markdown>
EOF
starboard-helper engagement put --run-folder $RUN_FOLDER --path README.md <<'EOF'
<the start-here index Markdown>
EOF
```

### `discovery/analysis.md` — unified rollup

```
Write → <run-dir>/discovery/analysis.md
```

Contents:
1. **Executive summary** — 3–5 sentences on the workspace's overall health, cost
   posture, and top concerns.
2. **Domain report card** — a table: Domain · Grade (A–F or Good/Fair/Poor) ·
   Headline finding.
3. **Top priorities** — ranked list (1–5+) of the highest-value actions across
   all domains, with domain, evidence citation, and list-price DBU impact where
   known.

### `README.md` — start-here index

```
Write → <run-dir>/README.md
```

Contents:
- Workspace name, date, lookback window
- Headline numbers (total jobs, warehouses, DBU spend detected)
- "Start here" pointer: `discovery/analysis.md` for the executive view
- Domain index: list of `discovery/domains/<domain>.md` files with one-line
  summaries
- `## Storage`: `run_id`, task, task name, `storage_decision`, the run dir or the Drive `run_link`,
  and every warning shown
- `## Delivery`: one line per file you point the reader at, e.g.
  `- discovery/analysis.md: run folder only (<run_link or run dir>), not delivered elsewhere`
- `## Recur`: when the run has a `findings-manifest.json` (a `starboard review --from-discovery`
  ran), `starboard-helper run recur --run-folder $RUN_FOLDER` writes it (`--baseline` on the first
  run of the workspace; local: `run recur <run-dir>`); otherwise write
  `- baseline — discovery only, no comparison`

**Finish the run (standalone runs).** Inside an engagement the engagement's beats record and
publish the run; skip this. Otherwise, after the README put, commit the analysis, then
`run check` must exit 0 (a discovery run checks the README sections and the discovery files;
add `--internal` on an internal run, which needs no `deliverables/`), then commit the check stage:

```bash
starboard-helper engagement commit --run-folder $RUN_FOLDER --stage analysis
starboard-helper run check --run-folder $RUN_FOLDER --out analysis/run-check.json   # must exit 0
starboard-helper engagement commit --run-folder $RUN_FOLDER --stage check
starboard-helper engagement status --run-folder $RUN_FOLDER
```

`run check` can take several minutes: run it in the foreground with Bash `timeout: 600000`. A
local run checks `run check <run-dir> --out <run-dir>/analysis/run-check.json` and has no commit
step.

Share route's `run_link` and repeat any `fallback_warning`. The run folder holds the files; they
are not delivered anywhere else until they go through the engagement's report → approve →
deliver | receipt chain, and only a verified receipt counts as delivered. A failed write prints
`resume`: continue with `starboard-helper engagement preflight --resume-run-id <run_id>`. If the
folder's sharing changed since route, the helper stops with `blocked_access`: restore the folder's
previous sharing and re-run, or start a new run with preflight.

## Step 6 — Present findings

Present key findings on-screen, **highest-value first**. Cite the written files:

- Top 3–5 priorities from `analysis.md`
- Where the full report lives (`<run-dir>/`, or the Drive `run_link`)
- Offer to discuss any domain in depth or run additional domains

`$` figures are **list-price DBU estimates** — label them as such.

## Fallback — `starboard-helper` raw fetch

If the bundled helper is unavailable (e.g. `starboard-kernel` not installed),
enumerate resources directly with `starboard-helper` and reason over what it
returns:

```bash
starboard-helper job list --profile <profile> --limit 100
starboard-helper cluster list --profile <profile>
starboard-helper warehouse list --profile <profile>
starboard-helper uc catalogs --profile <profile>
```

In fallback mode, write the same output layout as above (omitting `plan.json` and
the `raw/` files, which require the bundled helper).

## Single-shot mode (alternative)

For a quick one-blob check, after the Step 2 run setup:

```bash
python -m starboard_x.discovery run --data-only --authorization <run-dir> --profile <profile> [--packs DOMAIN ...]
```

This returns the full envelope (all packs, all rows) to stdout, so it is a local-run form only:
on a Drive run, full-envelope stdout is refused; use
`python -m starboard_x.discovery run --data-only --run-folder $RUN_FOLDER --profile <profile>` (it writes the rows
into the run folder and prints a bounded summary). For large
workspaces this can produce a multi-megabyte payload that may truncate under
stdout capture. The incremental `--only --out-dir` flow (Steps 2–5) is preferred
for production use.

## Exit codes (from the bundled helper)

- 0: success
- 1: authentication error — check `DATABRICKS_HOST` / `DATABRICKS_TOKEN` (or `--profile`)
- 2: resource not found
- 3: API error — check workspace connectivity
- 4: bad arguments (e.g. unknown pack name with `--only`; mutually exclusive `--only`/`--packs`)
- 7 on a `--run-folder` run whose `error` starts with `BLOCKED_ACCESS`, `STORAGE_INTEGRITY`, `NOT_FOUND`
  or `STORAGE_ERROR`: a storage / integrity / access failure — stop and report `error` verbatim

A run that `--authorization` or `--run-folder` refuses (bad record, or a workspace outside the
authorized scope) also exits non-zero: stop and report it.
