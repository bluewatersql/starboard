---
name: starboard-health-review
description: "Run a Databricks workspace health review — a proactive, weekly, monthly or QBR read of consumption trajectory, efficiency, reliability, adoption breadth, concentration and governance, each assessed or marked unknown, with ranked plays and a run-over-run comparison. Read-only; `$` figures are list-price DBU estimates. Use when the user asks how a workspace or account is doing, for a health check, a monthly or weekly health read, or a QBR health review. For one failing job, query or pipeline use starboard-troubleshoot instead."
allowed-tools: Bash(starboard-helper:*), Read, Write
---

# Starboard: Health review (the `health_check` task)

This is a **thin entry skill** of the Starboard engagement workflow. **Load
[`starboard-engagement`](../starboard-engagement/SKILL.md) first**: it owns the run setup, the
beats, the exit codes and the guardrails. This skill runs one task, `health_check`, and says only
what differs for it.

A health review reads the workspace and writes one report, `deliverables/health-read.md`. It
has no action-plan deliverable set, no verify floor and no notebooks: the plan is the plays the
operator owns. It also has no technical-review or humanize beat (`run check` lists those items
under `skipped_by_profile`); check the read's numbers against the facts yourself.

## You are the analyst

**You** are the LLM for this skill. Starboard computes the health read deterministically
(`engagement analyze`); you reason over it, order the plays, and write the report. Do not call
the `starboard` goal agent, an MCP `*_analysis` / `synthesize_*` tool or any other model.

## Step 1 — Pick the intent and the window

Each intent sets only the window and the comparison. Ask only for what the prompt has not given.

| Intent | Window | Comparison |
|---|---|---|
| proactive (no cadence named) | 30 days | the newest earlier health run of the account |
| monthly (the default) | 30 days | the newest earlier health run of the account |
| weekly | 7 days | the newest earlier health run of the account |
| QBR | 90 days | the previous quarter as the baseline |

The window is the discovery lookback: `--lookback-days 7` on a weekly run, `30` on a monthly or
proactive run and `90` on a QBR run. `engagement analyze` reads the same window from the captured
facts, so every family shares one window; pass it no interval of its own.

A comparison only holds between runs of the **same window length**: a 7-day run is compared with
an earlier 7-day run, a 30-day run with a 30-day run, a 90-day run with a 90-day run (the
tolerance is ±1 day of the declared `--lookback-days`, so 31 against 30 is the same length). Only
an earlier `health_check` run that committed a `findings-manifest.json` is ever compared; a
troubleshooting run, or a run with no manifest, is listed in `prior_runs` with `skipped_reason`
(`other_task`, `no_findings_manifest`) and never compared. A prior of another length is
rejected as `window_mismatch` and reads `not_comparable`; so does a `run recur` whose prior has
another `lookback_days`. When no same-length prior exists, say so plainly ("no earlier 7-day run
to compare against"), show the current numbers on their own, tell the operator this run is the
first `<n>`-day baseline (the next `<n>`-day run compares against it), and never present a
7-day against a 30-day number as a change, an improvement, a regression, a new finding or a
recovery.

`engagement history` is optional on every Drive run: `run recur` makes the same baseline
selection and writes `analysis/baseline-selection.json` itself. On a QBR run read the history
with `starboard-helper engagement history --run-folder $RUN_FOLDER` once the capture is committed
(Step 3), before or after `analyze`: its reporting interval is this run's observations, or before
`analyze` the captured discovery facts window (the same window; `reporting_interval_source` says
`observations` or `facts`). Before the capture there is neither, and it exits 2 `USAGE`. Pass the
previous quarter's QBR run to both `engagement analyze` and `run recur` as the same
`--prior drive:<run_folder_id>`, so both compare that run (a local run's analysis reads every
prior run of its case root, as its recur does; `--prior <case-root>/<run_id>` there picks recur's
trend delta only). When the named prior is refused (`engagement analyze` exits 2 `USAGE`,
`run recur` exits 4: not a run of this account, trashed or unreadable), say so once, then run
both with `--baseline` and name this run the first 90-day baseline. Name the quarter you
compared against. When nobody has run
a 90-day review before, the named baseline is usually a 30-day run: that comparison is
`not_comparable` (`window_mismatch`), the normal outcome, not a failure; report it as above and
name this run as the first 90-day baseline. Pass `--baseline` to
`run recur` in both cases: the first run of a case (no prior), and a weekly run that matches a
scheduled run (a fresh start).

Ask which `--profile <name>` reaches the workspace; never pick one yourself. The expected
workspace id comes from the operator or a `ws-<id>` task name, never from a profile name.
**Skip the question when the prompt already settles it.** If the operator asked for internal
telemetry only, or said they have no customer profile for the workspace (even when they also
asked for the customer workspace), there is nothing to ask: run `source-options`, then preflight
`internal_only` directly (Step 2), never a hybrid or customer run you would have to abandon, and
record the missing customer leg under `## Unknowns`.

## Step 2 — Choose the source, then set up the run

```bash
starboard-helper engagement source-options --task health_check
```

Read `data.options[]` (`source_mode`, `storage_policy`, `storage_choices`, `default_storage`,
`needs_workspace_auth`). When `data.choice_required` is false, the run is `customer_workspace`.
When it is true, map the prompt's words to a source ("internal only" → `internal_only`, "their
workspace" → `customer_workspace`, both → `hybrid`), or ask once, using `data.question` as
written: it lists each option with its storage and whether workspace auth is needed. Never choose
silently. An unattended run must
already carry `--source-mode`.

```bash
starboard-helper engagement preflight --task health_check --task-name ws-<workspace_id> \
  --account-key <account_key> --account-name "<account name>" --source-mode <mode>
starboard-helper engagement verify-identity --run-id <run_id> --profile <profile> \
  --expected-workspace-id <workspace_id>
starboard-helper engagement route --run-id <run_id>
```

- **Account key rule:** `--account-key` names the account's folder, registry and history, so
  every run of an account passes the same key. At preflight use the key the operator gave; else
  the WORKSPACE ID. Never use the account name as the key (preflight warns
  `account_key_looks_like_name:`); `verify-identity` runs after preflight, so the key never
  changes mid-run. `ACCOUNT_NAME_TAKEN` (exit 2) means the `--account-name` belongs to another
  key: re-run `engagement preflight` with `--account-key` set to the key the message names if it is the same account,
  else choose a different name; never merge. Use the name the operator gave; else the verified
  account name; else `ws-<workspace_id>` (only when no name exists; say so). Route finds the account
  folder by key whatever its name (a renamed folder is reused with an `account_name_differs`
  warning); a different key starts a separate folder with no history.
- Keep preflight's `run_id`. Pass `--storage drive|local` only when the operator named a store.
  Pass `--unattended` only when the prompt says the run is scheduled or unattended, or says not to
  ask anything. A prompt that pre-supplies answers but says neither is attended: take the answers
  from it and leave the flag off. "Non-interactive" or "nobody will answer" next to an operator script is attended too: the script is the operator. An unattended run cannot approve a customer report.
- `verify-identity` runs on a customer or hybrid leg. A mismatch exits non-zero and quarantines
  the run: stop, show `error` and read nothing.
- An `internal_only` run (internal overlay only) skips `verify-identity` and passes the
  workspace at preflight:
  `starboard-helper engagement preflight --task health_check --task-name ws-<workspace_id> --account-key <account_key> --account-name "<account name>" --source-mode internal_only --internal-workspace-id <workspace_id>`.
  `--internal-workspace-id` is valid only with `--source-mode internal_only`; the overlay's
  internal-only section supplies the capture and verify templates, including the internal-only
  local capture form (`internal_only_local`).
- A customer or hybrid leg with no customer profile is never given one. If you know that before
  preflight (the prompt says so), preflight `internal_only` directly. If it only turns up after a
  customer or hybrid preflight, start a new `internal_only` run with a new preflight
  (`--source-mode internal_only`, then `route`), never by re-labelling the current run. Either
  way, record the gap under the report's `## Unknowns`.

Act on preflight's `storage_decision`:
- **`drive_required`**, **`drive_default`** or **`drive_optional`** (a public install where the
  operator chose `--storage drive`): route returns `run_folder_id` (`$RUN_FOLDER`).
  Every writer takes `--run-folder $RUN_FOLDER` with run-relative paths and **nothing is written
  locally**. Show any `fallback_warning` (the chosen folder wasn't writable, so the run went to
  the `My Drive` account route).
- **`local`** or **`internal_only_local`**: `data.local_run_dir` is
  `<run-dir>` and its parent is the case root (`<case-root>`). Route writes
  `<run-dir>/analysis/run-authorization.json`, and every customer acquisition passes
  `--authorization <run-dir>`.

A refusal exits 2 with `LOCAL_STORAGE_REFUSED` or `STORAGE_UNAVAILABLE`: the `engagement` envelope
carries it as `errors[0].code` (show `errors[0].message` verbatim), any other helper starts its
top-level `error` with it (show `error` verbatim). Stop. A preflight `STORAGE_UNAVAILABLE` returns
`run_id: null` and creates nothing: re-run the same preflight once the storage adapter is
installed (a local run never needs it). The full refusal and exit-code rules are under *Refusals
and exit codes* in [`starboard-engagement`](../starboard-engagement/SKILL.md). Record `run_id`,
`task`, `task_name`, `storage_decision`, the run link (or the local run dir) and every warning
under README `## Storage`.

## Step 3 — Capture

Discovery reads the customer workspace through an existing SQL warehouse, and it never creates
or picks one. Ask the operator **"which existing SQL warehouse may discovery use?"**; to show the
choices, list them into the run:

```bash
starboard-helper warehouse list --profile <profile> --run-folder $RUN_FOLDER --out raw/warehouses.json
```

(local run: `--out <run-dir>/raw/warehouses.json`, no `--run-folder`). The IDs are at
`$.data.warehouses[*].id`. Pass the chosen ID
as `--warehouse-id`. Then run discovery, commit the capture right after it, and run the review
over the saved rows (offline, no second scan):

```bash
starboard --discover --profile <profile> --warehouse-id <warehouse_id> --lookback-days <7|30|90> \
  --data-only --json --out-dir discovery --run-folder $RUN_FOLDER
starboard-helper engagement commit --run-folder $RUN_FOLDER --stage capture
starboard review --from-discovery discovery --run-folder $RUN_FOLDER \
  --domains jobs,sql,warehouse,uc,portfolio-readiness --json \
  --out analysis/review.json --manifest-out findings-manifest.json
```

On a Drive run, let stderr go to the terminal; never redirect stdout or stderr anywhere, or
`tee` them: not to a file, not under `/tmp`, and not to `/dev/null` (`2>/dev/null` hides the
warnings).

**Long captures.** Run the discovery command in the foreground with Bash `timeout: 600000`;
never in the background (no `run_in_background`, `&` or `nohup`). A run capture (`--run-folder`,
or a local `--authorization <run-dir>`) stops itself at `--max-seconds` (default 480) and saves
its progress in the run (`capture/`). Exit 9
`CAPTURE_INCOMPLETE` (`retryable: true`, with `progress` and `resume`) means "not finished yet":
re-run the identical command until it exits 0, and do the same if the host killed the command at
its time limit. Exit 8 `STORAGE_TRANSIENT` during the capture (a Drive write failed
transiently) loses nothing either: re-run the identical command once and it resumes. Report `resumed.queries_reused`, and `resumed.fresh_reason` if present.
`--no-cache` does not turn resume off.

The review always passes `--domains jobs,sql,warehouse,uc,portfolio-readiness`: the governance
family is read from the `uc` and `portfolio-readiness` rules, which the default domains
(`jobs,sql,warehouse`) do not run. Without them governance is `unknown` with the reason
`not_reviewed:<domains>`. Pass the same flag on every form below.

Local run:

```bash
starboard --discover --profile <profile> --warehouse-id <warehouse_id> --authorization <run-dir> \
  --lookback-days <7|30|90> --data-only --json --out-dir <run-dir>/discovery
starboard review --from-discovery <run-dir>/discovery \
  --domains jobs,sql,warehouse,uc,portfolio-readiness --json \
  --out <run-dir>/analysis/review.json --manifest-out <run-dir>/findings-manifest.json
```

An `internal_only` run has its own capture form (no `--profile`, no warehouse): the overlay's
internal-only section has it. On an `internal_only_local` run it is the following, then the
review line with `--run-dir <run-dir>` added, so the review reads only that run's saved
discovery (a local run has no commit step):

```bash
starboard --discover --internal-workspace-id <workspace_id> --authorization <run-dir> \
  --lookback-days <7|30|90> --no-cache --data-only --json --out-dir <run-dir>/discovery
starboard review --run-dir <run-dir> --from-discovery <run-dir>/discovery \
  --domains jobs,sql,warehouse,uc,portfolio-readiness --json \
  --out <run-dir>/analysis/review.json --manifest-out <run-dir>/findings-manifest.json
```

A helper or `starboard review` envelope is `{ok, data, …}`: on a Drive run read `review.json` with
`engagement read --jsonpath '$.data.findings[*].finding.id'` (each `id` is `<rule_id>::<entity>`;
the rule is `'$.data.findings[*].finding.rule_id'`, while `findings-manifest.json` carries
`rule_id` at the top of each finding) and `$.data.degraded`, `$.data.unavailable_queries`,
`$.data.unavailable_domains`; there is no `$.counts`. The `run recur` stdout envelope (Drive
and local alike) carries its fields under `data` as well: read `data.baseline`, `data.comparable`.

Read the discovery's `data.status` in the stdout summary (`ok`, `partial` or `no_evidence`; the
failed queries are `data.failed`, `[{query_id, pack, error}]`, so never open `discovery.json` for
them). A Drive run's summary (at most 8 KB; banner and logs go to stderr) has no `data`: read
top-level `status` and `counts` (they come first, so read `$.status` straight from stdout, never
`tail` it), and `summary.failed`, `summary.packs_with_gaps` and `summary.facts`. Files appear as
compact refs `{path, object_id, size}`. Then:
- **`partial`** (exit 0): some queries failed; carry on and list them under `## Unknowns`.
- **`no_evidence`** (`ok: false`, exit 4 when every failure is a permission error, else 1): no
  scheduled query succeeded. The layout is written but is not evidence. **Stop and report** the
  errors; don't run the review.
- **`WAREHOUSE_PERMISSION_DENIED`** (exit 4): the warehouse is missing or this identity can't
  use it; the error names it and lists the visible IDs (`candidates`). Stop and ask the operator
  for another warehouse.
- Never retry a permission error (same warehouse, same grants). Only timeouts are retried, and
  discovery already retries them (bounded).
- A `query_text` of `<REDACTED>` is masked by the workspace API: record it under `## Unknowns`;
  never guess the SQL.

A health review is a workspace run: it never fetches a single job's logs, a cluster event log or
a query profile. A verify query is optional and only for a play's `next_commands` (the
engagement's verify beat, same templates and `--limit` rules).

## Step 4 — Analyze and order the plays

```bash
starboard-helper engagement analyze --run-folder $RUN_FOLDER [--warehouse-id <warehouse_id>] [--prior drive:<run_folder_id> | --baseline]
starboard-helper engagement analyze --run-dir <run-dir> --workspace-root <case-root> [--warehouse-id <warehouse_id>] [--baseline]
```

The second form is the local run (`--workspace-root` is exactly the run dir's parent). Pass
the same `--prior` or `--baseline` you pass to Step 5's recur (Drive run), so `analyze` and
recur compare the same prior run. Pass the
discovery warehouse as `--warehouse-id` (a public run always has one): the printed verify
commands use it. Without it they print `<warehouse_id>` and list it under the play's
`placeholders`. The summary also carries the window comparison (`comparable`,
`not_comparable_reason`, `window`, `prior_runs`), chosen by the same rule and flags as Step 5's recur.
Read the envelope's digest first: `top_plays[]` (up to 10, in effective order, one per entity
target, each with `effective_rank`, `play_id`, `action_id`, `play_code`, `interaction_type`,
`next_step_kind`, `target` (`kind:id`), `finding_ids`, `severity`, `urgency`, `exposure`,
`host_rank`, `reason`, `next_commands`, `placeholders`, `acceptance_state` (the action's
`pending`/`accepted`/`rejected`, null with no action) and `review_rule_id` (the review rule behind
the play's finding, e.g. `spend_step_change`; null for a non-rule finding); a target's other plays
are under `same_target_plays`, `[{play_id, play_code, action_id, effective_rank,
acceptance_state}]`), `plays_by_code`
(`{<code>: {count, play_ids, samples}}`: the first 25 ids, and `samples` the top 3 plays of the
code as `{play_id, effective_rank, target, reason, exposure}`), `coverage` (`{complete, partial,
unknown}` family names), `observations_by_family` and `findings_by_rule` (`{<rule_id>:
{findings, dropped}}`: each review rule's listed findings and, at its cap, how many more matched).
`prior_runs` lists runs that are not compared
too (`interval: null`, `skipped_reason` `other_task` or `no_observations`). Do not re-read `analysis/plays.json` or
`analysis/observations.json` for what the digest holds; for a missing field use
`engagement read --jsonpath` (`'$[*].play_id'`, then `'[<n>].<field>'`). The value is in
`data.excerpt`; with `--jsonpath` that is an object keyed by expression, even for one path, and
`--jsonpath` is repeatable (several slices in one read). A list returns at most
50 items, so page it with the slice `next_paths` names (`'$[50:100].play_id'`); each `plays.json` item
carries `target`, `effective_rank`, `action_id`, `severity` and `review_rule_id` as the digest
does (a play's `rule_id` is the play rule set, `play_rules_v1`; find a review rule's play by
`review_rule_id`). "Top-ranked" means the
lowest `effective_rank`: host-ranked plays come first, ordered by `host_rank` (a tie keeps the
computed order), then the computed plays; a single `--rank 5` makes that play effective rank 1.
There is no demote.

**A step the facts record but no rule flags.** The discovery facts' `step_change` (and the
consumption_trajectory observations `step_change_present` = 1 and `step_change_lift_daily_dbus`)
records the window day with the largest 7-day lift whatever its size, while `spend_step_change`
fires only on a lift of at least 20% and 100 DBU/day (the default rule floor). When the facts
record a step and no `spend_step_change` finding exists, present it as **recorded, not flagged**:
"spend rose ~N DBU/day (×R, `current_vs_pre_ratio`) from `<date>`; below the step-change rule's
floor, so no finding" under consumption trajectory. It has no play, no rank and no exposure;
never call it a finding, a regression or an action.

`analysis/health.json` has six families (consumption_trajectory, efficiency, reliability,
adoption_breadth, concentration, governance), each assessed or **unknown**. It is large (every
observation and finding id per family) and holds no numbers: read
`--jsonpath '$.families[*].family'` and, per field, `'$.families[*].assessment'`,
`'$.families[*].coverage'`, `'$.families[*].severity'`, `'$.families[*].uncertainty'` and
`'$.families[*].unknown_reason'`. A family's numbers are in `analysis/observations.json` (a list of
`{family, entity_kind, entity_id, metric, value, unit, workspace_id, …}`): read
`'$[*].family'` and `'$[*].metric'` to find the positions (paged with `next_paths`:
`'$[50:100].family'`, …), then `'[<n>].value'` and `'[<n>].unit'`. There is no overall
score and no "healthy" label, and an unknown family is never read as fine. Order the plays with
the engagement's **Host rubric**. Each play's `exposure.exposure_dbus` is the finding's list-price
DBU estimate over the window, on every play except `spend_step_change`, which carries its DBU/day
lift as `exposure_dbus_per_day` (the same figure as the manifest's `evidence_dbu_estimate` and the
cited `lift_daily_dbus`; reason "~N DBU/day run-rate (list-price estimate)"; never sum it with
window totals). The computed order sorts by severity first, then exposure, weighing the run-rate
as DBU/day × the window's days only against plays of the same severity, so a `medium` step
change ranks after every `high` play whatever its size: compare exposure across severities
in your rubric and move it with `play rank --reason` when it outweighs them. Its verify is
`vt-daily-totals`, and `vt-step-change` needs `--split-date <step_date>`. `failed_runs` and
`failed_run_dbus` are set only by the job-failure rules, so never quote `failed_run_dbus` for another kind of play. A play's `next_commands` fit this
run: a health review has no `job fetch` command, and an internal-only run gets the internal
verify form (`--internal-workspace-id <workspace_id>`, plus
`--templates ~/<overlay skill path>/mirror-verify.md` when the overlay skill is installed; the
printed path is the copy the host loaded, and `STARBOARD_OVERLAY_DIR` pins it), never
the public `--profile` one. Cases are carried
unchanged: `analysis/cases.json` lists the account's earlier cases (a troubleshooting run's case
included) exactly as last revised. That is by design; a carried case is context, never a finding
of this health run, and `analyze` never revises it. Rank, accept and reject with:

```bash
starboard-helper engagement play rank --run-folder $RUN_FOLDER --play-id <play_id> --rank <n> --reason "<the factor that moved it>"
starboard-helper engagement action accept --run-folder $RUN_FOLDER --action-id <action_id> --note "<what the operator owns>"
starboard-helper engagement action reject --run-folder $RUN_FOLDER --action-id <action_id> --note "<why not>"
```

A host rank belongs to this run only: the next run's `analyze` starts with `host_rank: null`
(play IDs are stable), so re-apply `play rank` when the reason still holds.

Do not commit here: the one analysis commit is in Step 6, after the last write and before
`run check`. Accept or reject only the actions the operator says they own. An action's state is per account
and carries across runs (its id is stable per finding): one accepted in an earlier run answers
`already: "accepted"` and writes nothing. When the operator says "accept one", pick an action whose
`acceptance_state` in `analysis/actions.json` is still `pending`. On a local run the same verbs take
`--run-dir <run-dir> --workspace-root <case-root>` in place of `--run-folder $RUN_FOLDER`, e.g.
`starboard-helper engagement play rank --run-dir <run-dir> --workspace-root <case-root> --play-id <play_id> --rank <n> --reason "<why>"`.

## Step 5 — Recur

```bash
starboard-helper run recur --run-folder $RUN_FOLDER [--warehouse-id <warehouse_id>] [--prior drive:<run_folder_id> | --baseline]
starboard-helper run recur <run-dir> --workspace-root <case-root> [--warehouse-id <warehouse_id>] [--prior <case-root>/<run_id> | --baseline]
```

Pass the same `--warehouse-id` as Step 4 (without it the printed commands carry
`<warehouse_id>` under `placeholders`).

On a Drive run the history is the account registry (`engagement history`, chosen per
observation). On a local run it is the account's earlier local runs; the trend goes to
`<case-root>/trend/history.json`, keyed on `(run_date, run)`, so two same-day recurs are two
entries. On an `internal_only_local` run the review before it may take
`--since <case-root>/<prior_run_id>/findings-manifest.json` (a prior run's manifest in the same
case root; any other `--since` path is refused). Carry the comparison words (`no_prior_measurement`,
`missing_current_evidence`, `not_comparable`, `continuing`, `recovered`, `new`) and never read
`missing_current_evidence` or `not_comparable` as improvement.

A health check has no backlog, so its recur has no backlog sections, no backlog sizing and no
missing-backlog warning. Both forms write `analysis/delta-vs-<prior_date>.md` (the review's
findings delta against the prior run) and a README `- Delta:` line; on a Drive run read it with
`engagement read` and, only when `truncated` is false, put the whole file back with your
narrative (never an excerpt; the engagement skill's recur beat has the rules). On a comparable
run, a health check with no `cost_delta` says "No review findings cost delta
(`analysis/review.json` carries none)."; a not-comparable delta has no cost-delta section and no
such line (its "Capture repeatability (not a change)" table takes that place), so do not add one.
Both forms return one contract (the `run recur` envelope's `data` and `analysis/recur-result.json`):
`comparable`, `not_comparable_reason` (`null`, `"baseline"`, `"window_mismatch"`, `"no_eligible_prior"` or
`"interval_overlap"`), `window` (`comparable`, `reason`, `prior_run_id`, `prior_lookback_days`,
`current_lookback_days`), `prior_runs[{run_id, interval, task, skipped_reason}]` (`interval` may
be null; `skipped_reason` is `other_task`, `no_findings_manifest`, `no_observations` or null) and
`delta_skipped_reason` (null when a delta was written or on a baseline, else
`no_eligible_prior`, `prior_no_findings_manifest` or `prior_manifest_unreadable`). The Drive
result and the local stdout add `prior_run_date`, `history_entry` (local stdout: `entry`),
`delta_path`, `delta_counts` and `backlog_delta` / `backlog_sizing` (empty lists and `[]` for a
health check, not null); a
Drive result also carries `prior_entry`. Both upsert README `## Recur`. `baseline` is true when
no prior run has observations (none at all, or only `prior_runs` rows skipped as
`no_observations`; on a local run, no prior run in the case root) or with `--baseline`; a prior
skipped as `other_task` or `no_findings_manifest` gives `no_eligible_prior` instead; it comes with `comparable: false` and
`not_comparable_reason: "baseline"`, and README then reads "baseline — no prior run". Check
`baseline` first and say "baseline — no comparison", never "not comparable"; only `window_mismatch`
and `interval_overlap` mean a prior existed and could not be compared.
Only an earlier `health_check` run that committed a `findings-manifest.json` is compared (a
pinned `--prior` waives that); any other earlier run is listed in `prior_runs` with its
`skipped_reason`, and with none eligible the run is `comparable: false`,
`not_comparable_reason: "no_eligible_prior"`. A Drive run prefers same-length prior
observations; a local run prefers the newest earlier run with the same `lookback_days`. When
every eligible prior has another length (beyond ±1 day), the output says `comparable: false`
and `not_comparable_reason: "window_mismatch"`, a `window_mismatch:` warning names both
lengths, no window-total or backlog sizing delta is computed (rows read `not_comparable`; a
Drive run's rejected baselines name each `candidate_run_id` and its `interval` in
`analysis/baseline-selection.json`), and README `## Recur` leads with "not comparable
(window_mismatch) — windows differ: the prior run covers N days, this run M" (Drive and local
alike). A delta file written for a not-comparable run leads with
`**not comparable (<reason>)**`, prints the window totals as `prior X · current Y (not compared)`
(no arrow), and counts per rule id the findings (`rule::entity`) present in both captures under
"Capture repeatability (not a change)", even with no `cost_delta`. That table names no entity
(the entity ids are in the two `findings-manifest.json` files; never copy them into the read). The file is `analysis/delta-vs-<prior_date>.md`;
its title is ``Delta vs <prior_date> (prior run `<short id>`)``. Its scope line says whether the
product DBU totals cover one workspace ("cover workspace <id>") or are account-scoped; carry it as
written. `review --since <prior manifest>` applies the same window rule to its `cost_delta`
(`interval_overlap` or `window_mismatch`): there is then no DBU delta and no improved or regressed
class, only `persisting`; never present improved or regressed from it. Show the operator: "the prior run covered N days, this run M days; not comparable",
plus the per-day figure (`DBU/day`, total divided by lookback days) only as indicative context,
labelled list-price. The spend trend chart plots only runs of the current window length. To get
a real comparison, re-run the earlier window length or pin a same-length `--prior`.
When an eligible prior exists but no observation has a baseline (for example the reporting
intervals overlap this run's), recur gives `comparable: false` with
`not_comparable_reason: "interval_overlap"` (or the dominant per-key reason), computes no
outcome, and carried actions get no `outcome_state`. Say "not comparable (<reason>)" and never
read it as "no change".
`starboard-helper engagement status --run-id <run_id>` says where a stopped run stands (`--run-id`
may accompany the run's own `--run-folder` or `--run-dir`); resume it, never restart it.

## Step 6 — Write the health read, register it, check the run

Write `deliverables/health-read.md`:

- the assessed families first, each with its number, source and `workspace_id`; `$` figures are
  **list-price DBU estimates**, labelled as such;
- on an `insufficient_evidence` verdict, the exact line `Insufficient evidence` and what to
  acquire (the `acquire_family_evidence` plays);
- a `## Unknowns` section with one `- <family>: unknown` line per unknown family (and the exact
  line `- customer workspace: not acquired (no customer profile)` whenever the customer workspace
  was not acquired, also when the operator chose internal telemetry only); with no
  unknown family keep the section, write `No family is unknown.`, and still list the skipped or
  failed discovery queries and the coverage gaps (`coverage_note`);
- a family with a `suppressed:<rule_id>[:missing_column:<col>]` uncertainty (the source lacks a
  column the rule needs, e.g. `run_as` on the internal mirror) reads "not assessed (source lacks
  <col>)": never healthy, never a "no owner" finding; a family whose only gap is `suppressed:*`
  has no acquisition request, so there is nothing to re-run (the engagement skill's *Suppressed
  rules*); a family whose only gap is `evidence_capped` has no acquisition request either (no
  command lifts a row cap); say which cap applies where a count is capped (`evidence_capped`,
  `rule_finding_cap`, `per_job_cap_25`); rule coverage is required only for governance, so
  efficiency or reliability can read `coverage: complete` with `not_reviewed:<domain>` in its
  `uncertainty` (e.g. `dlt`, `ml`, `vector_search`, outside the review's `--domains`): its facts
  are complete, and that rule domain was not reviewed: list it here;
- the ordered plays and the actions the operator accepted;
- the run-over-run comparison;
- "about" for an approximate figure, never `~`: the read is delivered to a Doc unchanged, and a
  Doc turns `~` into strikethrough or a literal `\~`.

The README carries a `## Delivery` section before `run check` (run check item 1 needs a real
artifact line there; Step 7 replaces it with each delivery outcome):

```markdown
## Delivery

- deliverables/health-read.md
```

On an internal run (`--internal`) the line names the file you deliver,
`- deliverables/health-read.clean.md`.

Drive run: put the read and the README, commit once, register the read, then check. **Commit
before every `run check`** (it verifies each committed file's md5, so a file put after the last
commit fails it). The flow needs exactly these commits and checks, no others: one `--stage
capture` commit right after discovery (Step 3), one `--stage analysis` commit after the
last `put` / `play rank` / `action` / `recur` / sanitize write (below), one `run check`, one
`--stage check` commit, one more `--stage check` commit after a customer version's put (Step 7,
only when there is one), and, after delivery fills the README, a last `--stage check` commit.
Re-run `run check` only after fixing a failure, and commit again first.

```bash
starboard-helper engagement put --run-folder $RUN_FOLDER --path deliverables/health-read.md <<'EOF'
<the health read Markdown>
EOF
starboard-helper engagement put --run-folder $RUN_FOLDER --path README.md <<'EOF'
<the README: ## Storage, the Delivery section above and the ## Recur section run recur wrote;
 run recur created README.md with only ## Recur, so this put writes the whole file>
EOF
starboard-helper engagement commit --run-folder $RUN_FOLDER --stage analysis
starboard-helper engagement report --run-folder $RUN_FOLDER --report-id health-read --audience internal --path deliverables/health-read.md
starboard-helper run check --run-folder $RUN_FOLDER --out analysis/run-check.json
starboard-helper engagement commit --run-folder $RUN_FOLDER --stage check
```

Local run (`route` already created `<run-dir>/deliverables/`): write
`<run-dir>/deliverables/health-read.md` and `<run-dir>/README.md`, then
`starboard-helper run check <run-dir> --out <run-dir>/analysis/run-check.json`. `run check`
warnings are at `data.warnings`, not the envelope's top level. A local run has
no commits and registers no report, so `run check` gives no "no report yet" warning. Then
append a one-line audit entry to `starboard-reports/schedule.log`, except on an isolated run dir
(record the line in README `## Recur` instead). The line is
`<UTC ISO time> health_check ws-<workspace_id> run=<run_id> source=<source_mode> storage=<storage_decision> recur=<baseline|comparable|not_comparable(<reason>)> [prior=<prior_run_id>] run_check=<exit code>`.

Internal enrichment (an `internal_only` or `hybrid` run with the internal overlay installed):
the order is put the read and the README, sanitize every `deliverables/` text file into its
`.clean` sibling per the overlay's *Beat 4*, then the analysis commit, then `engagement report`
with `--path deliverables/health-read.clean.md` (`report` binds committed bytes only, so a
`.clean` file written after the commit is refused), then `run check` with `--internal`, then
the check commit:
`starboard-helper run check --run-folder $RUN_FOLDER --internal --out analysis/run-check.json`
On an `internal_only_local` run: write the read and the README, sanitize each `deliverables/`
text file with the overlay's local form (`--in <run-dir>/deliverables/<name>.md --out
<run-dir>/deliverables/<name>.clean.md`), then
`starboard-helper run check <run-dir> --internal --out <run-dir>/analysis/run-check.json`.
Without `--internal`, items 12 and 16 (the `.clean` siblings and their sanitizer check) are
not checked: `run check` lists them under `skipped_not_internal`, never under `passed`. On a Drive
run item 16 checks generic wording only (its warning says so): the sanitize step's own result is
the full check, so quote it. Deliver only the `.clean` files. The overlay's *Health reviews and troubleshooting on
the internal-only leg* has the commands.

`run check` uses the `health_check` profile (`data.profile`) and lists the items it does not
need under `skipped_by_profile`. Its `health_report` item fails when the read is missing, is not
the registered `health-read` revision on a Drive run, or breaks the `Insufficient evidence` /
`## Unknowns` rules. Fix every failure until it exits 0. A `publication pending: N customer
report(s)` warning appears only while a customer report awaits its receipt.

## Step 7 — Deliver and hand off

For a finding whose play has `next_step_kind: investigate` (its `play_code` is
`job_reliability_investigation` or `rule_finding_review`; there is no play named `investigate`),
**offer** (never start) a focused case: a new
`troubleshooting` run with [`starboard-troubleshoot`](../starboard-troubleshoot/SKILL.md),
opened on that finding with `--finding-id <finding_id>`. The operator decides; one task per run.
Make the offer before the README re-put below, so the answer goes into that same put. An offer
that gets no answer (an unattended or scripted run) is declined: start nothing and record
`offered, no answer: not started` in that put. The same holds for the customer-version offer
below.

Deliver with [`starboard-deliver`](../starboard-deliver/SKILL.md): it derives the audience from
the destination, offers a customer version only when `allowed_audiences` includes `customer`,
and on a Drive run records a missing tool as `not delivered: <reason>`. The delivered report
keeps its `## Unknowns` section. A customer version is its own file and report, derived from the
registered read; put it, commit, then register it (`report` binds committed bytes only):

```bash
starboard-helper engagement put --run-folder $RUN_FOLDER --path deliverables/health-read-customer.md <<'EOF'
<the customer version, from customer-shareable evidence only>
EOF
starboard-helper engagement commit --run-folder $RUN_FOLDER --stage check
starboard-helper engagement report --run-folder $RUN_FOLDER --report-id health-read-customer --audience customer --path deliverables/health-read-customer.md --derived-from health-read@<n> --cite-observation <observation_id>
```

Cite the observations the version states (`observation_id` from `analysis/observations.json`;
`--cite-evidence <evidence_id>` for evidence); both flags repeat, and a customer report needs at
least one citation.

Then approve and deliver or record its receipt (the deliver skill's chain). Then replace the `- deliverables/health-read.md` line with the
delivery outcomes (the receipt or URL, or `not delivered: <reason>`) and re-commit the check
stage:

```bash
starboard-helper engagement put --run-folder $RUN_FOLDER --path README.md <<'EOF'
<the whole README, with the ## Delivery lines filled in>
EOF
starboard-helper engagement commit --run-folder $RUN_FOLDER --stage check
```

This is the last `--stage check` commit; do not re-run `run check` for it unless a fix needs
it. (local run: write the `## Delivery` lines into `<run-dir>/README.md`).

## Exit codes

`starboard` (`--discover`, `review`):

- 0: success (`data.status` `ok` or `partial`)
- 1: general error, or a `no_evidence` discovery whose failures are not all permission errors
- 2: usage error or a storage refusal (`LOCAL_STORAGE_REFUSED`, `STORAGE_UNAVAILABLE`,
  `INTERNAL_SCOPE_REFUSED`)
- 3: configuration error
- 4: authentication or permission error (`WAREHOUSE_PERMISSION_DENIED`, an expired internal-source
  sign-in, or a `no_evidence` discovery whose failures are all permission errors)
- 5: connection error — check workspace connectivity
- 6: timeout
- 7 on a `--run-folder` run whose `error` starts with `BLOCKED_ACCESS`, `STORAGE_INTEGRITY`, `NOT_FOUND`
  or `STORAGE_ERROR`: a storage / integrity / access failure — stop and report `error` verbatim
- 8: `STORAGE_TRANSIENT` (a retryable Drive failure, `retryable: true`)
- 130: interrupted

`starboard-helper` (`engagement`, `run check`, `verify`, fetches) has its own codes (`run check`
exits non-zero when an item fails): see *Refusals and exit codes* in
[`starboard-engagement`](../starboard-engagement/SKILL.md). A helper failure with a machine code
carries `errors: [{code, message, retryable}]`; `WORKSPACE_TIMEOUT` (exit 3) is retryable. Exit 8
(`STORAGE_TRANSIENT`, on every surface) or any `errors[0].retryable: true`: retry the same
command once; if it fails again, stop and record it (for a `WORKSPACE_TIMEOUT`, narrow the call or
list it under `## Unknowns`). Exit 2 `ACCOUNT_NAME_TAKEN`: re-run
`engagement preflight` with `--account-key` set to the key the message names if it is the same account, else choose a
different `--account-name`; never merge.
