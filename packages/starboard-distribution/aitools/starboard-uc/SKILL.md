---
name: starboard-uc
description: "Analyze Unity Catalog metadata and governance — explore catalogs, schemas, tables, lineage, and governance posture. Use when the user asks about Unity Catalog, data governance, catalog/schema/table structure, or data lineage."
allowed-tools: Bash(python -m starboard_x.uc *), Bash(starboard-helper:*), Read, Write
---

# Starboard: Unity Catalog Analysis

Analyze Unity Catalog metadata — explore catalogs, schemas, tables, lineage, and
governance posture.

## You are the analyst

**You** are the LLM for this skill. The skill hands you deterministic catalog and
schema data; **you** read the rows and write the governance assessment and
recommendations yourself.

Do **not** call the `starboard` goal agent, an MCP `*_analysis` / `synthesize_*`
tool, a model-serving endpoint, or any other model. There is no second LLM in
this loop — the data step below runs pure Python (no LLM), and you do the
reasoning. Handing analysis to another model defeats the point of the skill and
breaks when that model's credentials differ from your session's.

## Step 1 — Confirm inputs and set up the run

Before loading data, confirm the run parameters with the user — but **only ask
for what they haven't already given**. If their request already specifies a value
(e.g. "analyze catalog my_catalog"), use it and skip that question. If they say
"just go" / "use defaults", proceed with the defaults.

Ask for (with defaults):

- **Scope** — which catalog and/or schema to analyze, or survey all catalogs?
  Default: **survey all catalogs**.
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

A refusal exits 2 with `LOCAL_STORAGE_REFUSED` or `STORAGE_UNAVAILABLE`: the `engagement` envelope carries it as `errors[0].code` (show `errors[0].message` verbatim), any other helper starts its top-level `error` with it (show `error` verbatim). Stop. A preflight `STORAGE_UNAVAILABLE` returns `run_id: null` and creates nothing: re-run the same preflight once the storage adapter is installed (a local run never needs it). Analyzing a table-schema file already on disk reads no workspace; the setup is for the live catalog reads below and for saving. Setup writes no report; the report is written only if the user
opts in (see the save step).

## Step 2 — Load the data (deterministic, no LLM)

### Analyze a table schema on disk (bundled helper)

If you already have a table's **schema JSON** on disk (columns + optional
`table_name`), run the pure UC analyzer — no network required. It emits the stable
JSON envelope to stdout. The **portable** engine invocation runs on any host
(Claude Code, Codex, OpenCode, `databricks aitools`):

```bash
python -m starboard_x.uc analyze --input <table.json>
```

Input shape:
`{"table_name": "cat.sch.tbl", "columns": [{"name": ..., "data_type": ..., "nullable": ...}, ...]}`.

Read the returned `data.anomalies`, `data.classification` (table type + medallion
layer), `data.semantic_patterns`, and `data.schema_health`, then proceed to
Step 2. Requires `pip install "starboard-kernel[uc] @ git+https://github.com/bluewatersql/starboard.git#subdirectory=packages/starboard-core"`.

### Explore live catalog metadata (starboard-helper)

To explore a live workspace catalog hierarchy, use `starboard-helper`:

```bash
starboard-helper uc catalogs --profile <profile>
starboard-helper uc schemas --profile <profile> --catalog <CATALOG>
starboard-helper uc tables --profile <profile> --catalog <CATALOG> --schema <SCHEMA> --out uc-tables.json
starboard-helper uc table --profile <profile> --full-name <CATALOG>.<SCHEMA>.<TABLE>
starboard-helper uc lineage --profile <profile> --full-name <CATALOG>.<SCHEMA>.<TABLE>
```

A schema with many tables can produce a large `uc tables` payload — add
`--out FILE` (as above) to write the full result to `FILE` and print a compact
summary to stdout, then **read `FILE`** instead of the truncated inline output.
`--out` works on any verb and may go before or after the subcommand.

## Step 3 — Analyze the data yourself

Read the returned rows and assess governance posture:

- **Governance** — do tables have owners and comments? Missing metadata is a
  governance gap.
- **Lineage** — are there orphaned tables (no upstream/downstream)? Potential dead
  data.
- **Table types** — are MANAGED vs EXTERNAL tables used appropriately?
- **Data formats** — are legacy formats (CSV, JSON) used where Delta would be
  better?
- **Access patterns** — are schemas organized logically (bronze/silver/gold or
  domain-based)?

## Step 4 — Produce the report

1. Catalog/schema overview and health
2. Governance gaps (missing owners, comments, tags)
3. Data organization recommendations
4. Lineage observations
5. Priority: critical / high / medium / low

### Offer to save the report

After presenting the findings, **offer** to save them as a Markdown report:

> "Want me to save this as a report? I'll write it to `analysis/uc.md` in this run (its
> Drive run folder, or its run dir under `./starboard-reports/`)."

If the user accepts, write the report to `analysis/uc.md` in the run; set it up now if an offline analysis skipped it and add a
`README.md` index with a one-line pointer to the report. Confirm where you wrote it. Don't write
anything unless the user opts in. Inside an engagement run the engagement's deliver beat publishes
it; skip the rest of this step.

- **Local run** (`local` / `internal_only_local`): write `<run-dir>/analysis/uc.md` and
  `<run-dir>/README.md`. There is no Drive leg.
- **Drive run** (`drive_required` / `drive_default` / `drive_optional`): nothing is written
  locally. Put both files into the run
  folder with `engagement put` (the bytes come on stdin; an identical re-put is a no-op), then
  record them and check the run:

  ```bash
  starboard-helper engagement put --run-folder $RUN_FOLDER --path analysis/uc.md <<'EOF'
  <the report Markdown>
  EOF
  starboard-helper engagement put --run-folder $RUN_FOLDER --path README.md <<'EOF'
  <the README index, with a one-line pointer to analysis/uc.md>
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
- 2: object not found — verify catalog/schema/table name. The error reads "not found or not
  visible to this identity": the object is absent or this identity has no privilege on it; it is not
  proof that it was dropped. With `--out` (and `--run-folder` on a Drive run) the `ok: false`
  envelope is written to the file too, so a negative lookup can be cited as evidence
  (`case revise --evidence <path>`).
- 3: API error — check workspace connectivity
- 7 on a `--run-folder` run whose `error` starts with `BLOCKED_ACCESS`, `STORAGE_INTEGRITY`, `NOT_FOUND`
  or `STORAGE_ERROR`: a storage / integrity / access failure — stop and report `error` verbatim
