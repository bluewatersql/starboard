# Opportunity catalog

Every backlog item carries one id from this catalog. Two runs on the same workspace should produce
the same ids, tiers, sizing kinds, and levers, so their plans can be compared directly. You (the
host) still reason about the evidence and write the plan. The catalog fixes the **vocabulary, the
sizing formula, and the disqualifiers**. It does not do the ranking.

**How to use it**

1. Read `data.facts` first and quote its headline numbers verbatim. Never recompute them.
2. For each signal in the envelope, find its id in the [signal map](#signal-map) below. A signal
   either maps to an id or gets cut, with the reason, in the map. Nothing is silently dropped.
3. Check the entry's **disqualifiers** before you choose a tier.
4. Run the entry's verify template(s) from [`verify-sql.md`](../../starboard-engagement/references/verify-sql.md)
   (an installed internal overlay supplies the same template ids for its own path). Save each one as
   `analysis/verify/<file>.sql` + `.json`.
5. Apply the [tier rule](#tier-rule) and size the item with the entry's formula only.
6. Write the item to `analysis/backlog.json`: `id`, `target`, `tier`,
   `sizing.kind`/`value`/`unit`/`formula` (plus `sizing.metric` for `perf_metric`), `evidence`
   (query ids plus at least one full `analysis/verify/<file>.json` path for Act now and
   Investigate), `lever` (the exact field and value from the entry), and `notebook`. Optionally
   add `lever_command` (the exact command for that lever; see [lever commands](#lever-commands)).
7. Every catalog id whose **trigger fired** in the envelope must appear in `items` or in the
   top-level `cut` list with a `rule` and a reason (see [cut vs Not now](#cut-vs-not-now)), for example
   `"cut": [{"id": "OPP-WH-IDLE", "rule": "disqualifier", "reason": "all warehouses serverless; est_idle_dbus is null by design"}]`.
   `run check` fails on a fired id that is in neither.

**Target.** Every item names the entity it acts on in `target`: `<kind>:<id>` with kind `job`,
`warehouse`, `pipeline`, `cluster`, `dashboard`, `genie`, `schema`, `endpoint` or `instance`
(`job:123456`, `warehouse:abc123def`, `schema:main.sales`), or `workspace` for a workspace-level
item (OPP-STEP-CHANGE, OPP-LAKEBASE, OPP-PO). Use the raw id, never the display name, so two runs
name the same target the same way. An id may appear more than once only for different targets
(two warehouses under `OPP-WH-SCAN`); `run check` fails on a repeated `(id, target)` pair. Fold a
second signal on the same target into one item.

**Target kind and granularity.** Each entry's `Target kind` row names the kind(s) its `target` may
use (comma-separated when several apply); its target-selection rule picks the id. The granularity is
**one item per target**: OPP-JOB-OVERLAP is one item per job (four overlapping jobs = four items,
`job:<id>` each), OPP-WH-QUEUE one per warehouse, and OPP-STEP-CHANGE one `workspace` item with the
per-workload attribution in `sizing.formula`. Each entry's `Verify` row lists the exact template ids
(`vt-…`) to run for that id; usage notes for those templates live in the entry's other rows.

**Coverage is per id; items are per target.** `run check` checks coverage by **id**: a fired id is
covered once it has at least one item **or** a `cut` entry. Which targets become items is the
entry's **target-selection** rule, not "every target the trigger touched": carry one item per
target that rule picks (each passing the trigger and verify), and record a target the trigger
touched but the rule doesn't pick only when it needs a reason a reader would ask for (a
`cut` entry with `target` and `rule: duplicate` / `disqualifier`). Seven warehouses tripping a loose
signal is not seven items.

## Tier rule

This is the single tier rule. It reads the same in `verify.md` and `starboard-action-plan`.

- **Act now** = verified AND (bounded recoverable DBU OR measured performance impact with a
  post-change measurement step) AND low-risk lever.
- **Investigate** = verified signal, sizing is a pilot/measurement or depends on customer context.
- **Not now** = low value or blocked.
- Never size by rate × window or by summing capped rows. Lakebase defaults to Investigate.

Terms used above:

- **Verified** means at least one saved verify output (`analysis/verify/<file>.json`) reproduces
  the signal. Re-reading the discovery envelope does not count.
- **Low-risk lever** means one named setting that the owner applies and can revert, with no data
  loss and no change to an SLA the customer hasn't agreed to.
- **Low value** means the bounded DBU is under 0.5% of `data.facts.total.dbus` and there is no
  material performance or reliability impact.

**Precedence (first match wins).** Apply these in order; a later step never overrides an earlier one.

0. **The [cut rule](#cut-vs-not-now)** decides first whether the fired id is an item at all: no
   evidence, a premise-removing disqualifier, or a duplicate target → `cut`, and the steps below
   don't apply.
1. **Not verified** (no saved verify output reproduces the signal) → not Act now or Investigate:
   keep it a candidate while verify runs; if the verify output can't be produced, cut it
   (`no_evidence`).
2. **An entry disqualifier that says Not now** and leaves a sized signal (intended growth
   confirmed, tail runs are backfills, failure DBU < 1% of spend) → Not now.
3. **An entry disqualifier that blocks the lever** (a capacity or size change on the target in
   the last 7 days, < 24 h of data after a change, the lever doesn't apply to the trigger type,
   concurrent ONETIME/backfill runs on an OPP-JOB-OVERLAP target with no "backfill finished or
   moved" confirmation, an OPP-JOB-OVERLAP target whose CRON `avg_run_mins` is longer than its
   schedule interval with no owner confirmation of the resulting cadence) → Investigate at most,
   with "measure the change" or the confirmation as the step.
4. **Low value** → Not now.
5. **A default that caps the tier** ("Investigate, always", Lakebase defaults to Investigate) →
   Investigate at most.
6. **The tier rule above** → Act now when all three conditions hold, else Investigate.

**Worked example (Act now).** Warehouse W has 4,000 queries in the window. vt-warehouse-queue shows
`queued_pct` of 12–31% on each of the last 7 full days, and the top source (vt-warehouse-drivers) is
one dashboard at 58% of the warehouse's execution time (`pct_of_warehouse_exec`). W-W07 shows `max_clusters` = 2, and
`data.facts.recent_config_changes` has no row for W. Steps 0–5 don't match: it is verified, no
disqualifier fires, queueing is a material performance impact, and OPP-WH-QUEUE has no cap. The
lever is low-risk: `max_num_clusters` 2 → 3 is one setting, reverts in one edit, and loses no data.
The notebook re-measures queueing 7 days after the change. → **Act now**, `perf_metric`
(`peak_daily_queued_pct` = 31.2 `%`), with the added DBU at peak stated as the lever's cost. Change
one fact and the tier changes: `recent_config_changes` shows `max_clusters` 1 → 2 yesterday →
step 3 → **Investigate**, "measure the change".

## Cut vs Not now

A fired id ends up in exactly one place. The test is mechanical: **is the opportunity real on this
workspace, and can you put a number in `sizing.value`?**

- **cut** (`cut[]`, with `rule`) — the trigger fired, but there is nothing to carry:
  - `disqualifier`: an entry disqualifier removes the premise, so there is nothing to size
    (no idle to remove; idle only on serverless; CRS rates the clusters RIGHT_SIZED; the wait
    guards an external dependency with no trigger; no Lakebase billing in the window).
  - `no_evidence`: **the source lacks the evidence** the entry needs — its verify template was run
    and failed or timed out with no staged fallback, or the column isn't carried on this source.
    "Not verified this cycle" is not `no_evidence`: `run check` fails a `no_evidence` cut when none
    of the id's `Verify` templates was attempted (an `analysis/verify/<file>.json` with `ok: false`
    counts as an attempt). The verify minimum in `verify.md` is a floor, not a budget: verify every
    Act-now/Investigate candidate rather than cutting the ones past the first eight.
  - `duplicate`: the same target is already carried by another item whose fix covers this one;
    name that item in `reason`.
- **Not now** (an item, `tier: not_now`) — the signal is real **and sized** (`sizing.value` is a
  number), but it falls below materiality or priority, or a Not-now disqualifier applies that still
  leaves the size standing (backfill tails, intended growth, failure DBU < 1% of spend).

`run check` requires `cut[].rule` ∈ `disqualifier` / `no_evidence` / `duplicate` and a non-empty
`reason`, fails a `no_evidence` cut with no attempted verify for that id, and warns on a Not-now item with `sizing.value: null` (that is a cut).

**Worked example (cut).** W-W02 shows `auto_stop_waste_pct` = 26 and `est_idle_dbus` = 40.0 on a
classic warehouse, so OPP-WH-IDLE fired. vt-warehouse-config-history shows `auto_stop_minutes` = 5
since before the window: the entry's disqualifier "auto-stop already ≤ 10" removes the lever, so
there is no idle the change could recover. →
`{"id": "OPP-WH-IDLE", "target": "warehouse:wh0001", "rule": "disqualifier", "reason": "auto_stop_minutes already 5 (vt-warehouse-config-history); no idle the lever can remove"}`.
If vt-warehouse-dbu had been run and timed out on a classic warehouse instead (the `ok: false` file
saved), the same id is cut with `"rule": "no_evidence"`. Not running it at all is not a cut.

**Worked example (Not now).** vt-job-failures shows ERROR 1,180.0 + TIMED_OUT 220.0 = 1,400.0 DBU
of failed runs, 0.40% of `data.facts.total.dbus`. The signal is real and sized, but it is below
the 1% materiality line → item `OPP-JOB-FAILURE`, `target: "workspace"`, `tier: not_now`,
`sizing: {"kind": "bounded_dbu", "value": 1400.0, "unit": "DBU", …}`, with "below materiality;
flagged to owners" in `sizing.formula`. It is not a cut: nothing disqualifies it, it is just small.

## Sizing kinds (`sizing.kind` in backlog.json)

`sizing.value` is a **JSON number or `null`, never a string**. The unit goes in `sizing.unit`, and
everything else (ranges, factors, caveats) goes in the prose `sizing.formula`.

| kind | When | `value` / `unit` | `formula` must show |
|---|---|---|---|
| `bounded_dbu` | The audited population bounds the saving | The bound, e.g. `1400.0` / `"DBU"` | `bounded_count × per_unit_DBU`, with each factor's source |
| `perf_metric` | The impact is latency, queueing, failure rate or concurrency | The id's **canonical metric** (table below) from the verify file, e.g. `31.2` / `"%"` with `"metric": "peak_daily_queued_pct"` | The metric, its value, its verify file, and the post-change measurement |
| `pilot` | Only a measured change can size it | `null` / `null` | `pilot — measure <metric> on <target> for <period>` |
| `none` | Size-of-problem context only, such as a step change | The size, e.g. `2500.0` / `"DBU/day lift"` | What the number is, and that it is not a saving |

```json
"sizing": {"kind": "bounded_dbu", "value": 1400.0, "unit": "DBU",
           "formula": "Σ DBU of ERROR (1,180.0) + TIMED_OUT (220.0) runs, vt-job-failures; 0.40% of data.facts.total.dbus; CANCELLED 900.0 reported separately; failed-run DBU, not recoverable"}
```

Wrong: `"value": "1,400 DBU"` (a string), `"value": "12–31% queued/day"` (a range: put the
peak in `value` and the range in `formula`).

### Canonical perf metrics

A `perf_metric` value means one thing per id, so two runs can compare it. When `sizing.kind` is
`perf_metric`, set `sizing.metric` and `sizing.unit` to exactly the row below and put the value of
**that** metric in `sizing.value`. Supporting figures (counts, before values, p95, other metrics)
go in `sizing.formula`. Ids not in this table have no `perf_metric` sizing; use the entry's kind
(OPP-OTHER may name its own metric and unit). `run check` fails on any other metric or unit, and
`starboard_skills/helpers/run.py` (`_PERF_METRICS`) holds the same table, with a test keeping the
two equal.

<!-- canonical-perf-metrics:start -->
| id | metric | unit | definition (source) |
|---|---|---|---|
| OPP-WH-QUEUE | peak_daily_queued_pct | % | Highest daily `queued_pct` over the last 7 full days on the target warehouse (vt-warehouse-queue) |
| OPP-WH-SCAN | avg_read_gb_per_query | GB/query | `avg_read_gb_per_query` of the target source on its warehouse (vt-warehouse-drivers) |
| OPP-WH-RESIZE | dbus_per_billed_hour_after | DBU/hour | `dbus_per_billed_hour` after the change (vt-warehouse-change-rate); the before value goes in `formula` |
| OPP-JOB-OVERLAP | pct_runs_started_while_running | % | CRON runs started while another run of the job was active ÷ CRON runs × 100, on the target job (vt-job-overlap; the after-step split when one exists) |
| OPP-JOB-TIMEOUT | max_run_mins | min | Longest CRON run of the target job in minutes (vt-job-run-tail); the p95 goes in `formula` |
<!-- canonical-perf-metrics:end -->

Why these: each is a rate or a per-unit figure that does not grow with the window length, so it
survives a different lookback (no "TB read in 7 days" vs 30 days); each is already the headline
the entry's verify template returns; and each is what the notebook re-measures after the change.
OPP-JOB-OVERLAP uses the share, not the count (120 of 150 and 80% are the same fact; a count
depends on the window) and not `max_concurrent_observed` (that is the concurrency, quoted in
`formula`).

The formula column in each entry is the only allowed sizing for that id. If you can't fill its
inputs from a verify output, use the entry's fallback kind.

## Lever commands

`lever` stays the prose form (field and value). An item **may** also carry `lever_command`: the
exact change as one object, `{"kind": "cli" | "sql" | "json" | "bundle_yaml", "text": "…"}`. `notebook render`
writes `text` verbatim into the notebook's remediation cell, so put a complete, copy-ready
command there with real ids, not `<placeholders>`. The cell stays operator-gated: the owner reads
and runs it. Leave `lever_command` out when the change depends on owner context (a dataset
rewrite, a root-cause fix).

**Without `lever_command`, render infers a command only from one unambiguous setting.** A default
command is filled from the target only when `lever` states exactly one `setting = value` for the
id's canonical field (`max_num_clusters X → Y`, `cluster_size X → Y`, `max_concurrent_runs`,
`timeout_seconds: N`, `performance_target: STANDARD`). Otherwise (another setting named, several
values, a health-alert proposal, or keep / retain / pending wording) the cell is an operator
decision note that says why, and no write preview. One
run proposed a `RUN_DURATION_SECONDS` health alert of 12600 s while keeping the job's 27000-s
timeout, and an earlier renderer wrote `timeout_seconds: 12600`: the wrong lever. If the item's
first step is an owner question, leave `lever_command` out and let the decision note stand.

| kind | Use for | Example `text` |
|---|---|---|
| `cli` | A Databricks CLI call | `databricks warehouses edit wh0001 --max-num-clusters 3` |
| `sql` | A SQL statement | `ALTER SCHEMA main.sales DISABLE PREDICTIVE OPTIMIZATION` |
| `json` | A settings fragment for a `jobs update` on a job that is **not** bundle-deployed | `{"job_id": 123456, "new_settings": {"max_concurrent_runs": 1, "queue": {"enabled": false}}}` |
| `bundle_yaml` | The bundle source change for a **bundle-deployed** job (vt-job-settings-history `deployment_kind` = `BUNDLE`), then redeploy | `resources.jobs.<job_key>:` / `  performance_target: STANDARD` |

**Bundle-deployed jobs always get bundle YAML.** A `jobs update` on a bundle-deployed job is
overwritten by the next `databricks bundle deploy`, which would silently end a pilot or revert a
cap. Use `bundle_yaml` for any job whose latest vt-job-settings-history row has `deployment_kind`
= `BUNDLE`. `notebook render` enforces it: for a bundle-deployed job it renders the bundle YAML
fragment plus a redeploy step, translating a `json` / `jobs update` `lever_command` when it can
(and stopping with an operator decision note when it can't), so the rollback is "revert the bundle
source and redeploy".

**Warehouse resize direction.** For `databricks warehouses edit`, Apply sets the **proposed**
value and Rollback restores the **current** one (W-W07 / vt-warehouse-config-history, latest row).
For an OPP-WH-RESIZE revert, the proposed value is the previous (smaller) size and the current is
today's size. A `lever_command` that sets the recorded current value is a no-op: `notebook render`
replaces it with a decision note.

Typical per id: OPP-WH-QUEUE / OPP-WH-RESIZE / OPP-WH-IDLE `cli` (`databricks warehouses edit`
with `--max-num-clusters`, `--cluster-size` or `--auto-stop-mins`); OPP-JOB-OVERLAP /
OPP-JOB-TIMEOUT / OPP-SERVERLESS-STANDARD-MODE `json` (the `new_settings` fragment for
`databricks jobs update --json`) on a job that isn't bundle-deployed, and `bundle_yaml` on a
bundle-deployed one; OPP-PO `sql`.

---

## Warehouses

### OPP-WH-QUEUE: warehouse queueing / capacity

| Field | Rule |
|---|---|
| Trigger | W-W01 `queued_query_pct` ≥ 10 **or** `avg_capacity_wait_secs` ≥ 10 on a warehouse with ≥ 1,000 queries; supporting signals: C-C03 / C-Q05 `queries_queued_30s_plus`, P-AIBI04 `queued_query_pct` for a dashboard or Genie space |
| Default tier | Investigate (performance-led). **Act now** when vt-warehouse-queue shows `queued_pct` ≥ 10 on **≥ 5 of the last 7 full days** (3–4 of 7 → Investigate, "intermittent queueing: measure another week"), the warehouse had no `max_clusters` or size change in the last 7 days, and the lever is low-risk: either `max_num_clusters` +1 (revertible, no data loss) or a low-risk fix to a single named driver (one dashboard, Genie space, or job) that causes most of the wait. See the [worked example](#tier-rule) |
| Sizing | `perf_metric`, canonical `peak_daily_queued_pct` (`%`); daily `queued_pct` range, `p95_capacity_wait_s`, `queries_waiting_over_30s` go in `formula` (vt-warehouse-queue). The DBU side is a **cost of the lever**, not a saving: added DBU at peak ≈ `dbus_per_billed_hour` (vt-warehouse-dbu) × added clusters × peak hours |
| Lever | First the driver: the dashboard dataset SQL (date predicates, a materialized view) or its refresh schedule. Then capacity: the warehouse `max_num_clusters` setting (`max_clusters` in system tables) |
| Disqualifiers | `data.facts.recent_config_changes` shows a `max_clusters` or size change on this warehouse in the last 7 days → **do not recommend more capacity**. Recommend measuring the change instead (vt-warehouse-queue split at the change time). Do not recommend moving traffic to another warehouse that queues ≥ 10% or has `max_clusters` = 1. W-W01 `utilization_band` "Under-utilized" on a **serverless** warehouse is not evidence of spare capacity, so check its query volume first |
| Target selection | Warehouses ranked by `queued_query_pct × total_queries`; within a warehouse, the driver is the top source by **non-capacity duration** (`non_capacity_duration_h`, alias `exec_duration_h` / `pct_of_warehouse_exec`) or by **read bytes** (`read_tb`, `avg_read_gb_per_query`) in vt-warehouse-drivers. Never pick it by `duration_h` / `pct_of_warehouse_duration`: total duration includes capacity wait, so the source that waits most (a victim of the queue) can top that list while reading almost nothing. A source with high `avg_capacity_wait_s` and low reads is a victim; name it as affected, not as the driver |
| Target kind | warehouse |
| Verify | vt-warehouse-queue, vt-warehouse-drivers, vt-warehouse-config-history |
| Notebook | Daily queue trend before/after any recent change; driver table; the driver's dataset SQL review step; the capacity change only as an operator-gated cell |

### OPP-WH-IDLE: classic/pro idle auto-stop

| Field | Rule |
|---|---|
| Trigger | W-W02 `auto_stop_waste_pct` ≥ 20 **and** `est_idle_dbus` not null; C-C02 rows for all-purpose clusters |
| Default tier | Act now when the bounded DBU passes materiality and the lever is auto-stop; Not now when it is sized but below materiality; cut (`disqualifier`) when a disqualifier leaves no idle DBU to size |
| Sizing | `bounded_dbu` ≤ W-W02 `est_idle_dbus` for the window (idle running hours × the warehouse's DBU/hour). Re-check DBU/hour with vt-warehouse-dbu. Label the result an upper bound: `est_idle_dbus` is unstable between snapshots, so state the snapshot |
| Lever | Warehouse `auto_stop_mins` (current value: W-W07 `auto_stop_minutes`), e.g. 10 for classic/pro; cluster `autotermination_minutes` for C-C02 |
| Disqualifiers | **Serverless warehouse → no idle DBU sizing**: `est_idle_dbus` is NULL by design, and serverless idle is reported in hours, not priced → cut (`disqualifier`). Idle ≤ 5% of running hours (for example, 24×7 ingestion warehouses) → cut (`disqualifier`), "no idle to remove". `auto_stop_minutes` already ≤ 10 → cut (`disqualifier`), "auto-stop already tight" |
| Target selection | Largest `est_idle_dbus` |
| Target kind | warehouse, cluster |
| Verify | vt-warehouse-dbu, vt-warehouse-config-history |
| Notebook | Idle hours vs running hours; the `auto_stop_mins` change as an operator cell; re-measure after 7 days |

### OPP-WH-CLASSIC-TO-SERVERLESS

| Field | Rule |
|---|---|
| Trigger | W-W07 `warehouse_type` CLASSIC or PRO with `warehouse_dbus` ≥ 1% of `data.facts.total.dbus` (`data.facts.warehouses.classic_dbus`) |
| Default tier | Investigate (pilot) when W-W02 idle ≥ 20% or the load is bursty (W-W03); otherwise cut (`disqualifier`): a pilot has no size, so there is no Not-now item to carry |
| Sizing | `pilot — measure DBU per query-hour and p95 latency on a serverless warehouse of the same size for 7 days`. Never "X% idle reduction" unless W-W02 shows that idle |
| Lever | A serverless warehouse of the same `cluster_size` (`enable_serverless_compute: true`) that the workload moves to for the pilot |
| Disqualifiers | Idle ≤ 5% (always busy) → cut (`disqualifier`), "serverless removes idle, and there is none to remove". An open OPP-WH-SCAN or OPP-WH-RESIZE on the same warehouse → fix that first and revisit |
| Target selection | Highest `auto_stop_waste_pct × warehouse_dbus` |
| Target kind | warehouse |
| Verify | vt-warehouse-dbu, vt-warehouse-config-history |
| Notebook | Pilot comparison query: DBU/query-hour and p95 before vs after |

### OPP-WH-SCAN: heavy scans / pruning on a warehouse

| Field | Rule |
|---|---|
| Trigger | W-W06 one source with `pct_of_warehouse_exec` ≥ 30 **and** the warehouse's `distinct_sources` ≥ 3 **and** either warehouse queueing ≥ 10% (`warehouse_queued_pct`, or W-W01 `queued_query_pct`) or a material `read_gb_per_query` for that source (≥ 10 GB/query). A single-tenant ingestion warehouse (one connector, `distinct_sources` 1–2) with no queueing doesn't fire it: one client at 100% of its own warehouse is the warehouse's purpose, not a scan problem. Key on `pct_of_warehouse_exec`, never `pct_of_warehouse_duration` (duration includes capacity wait, so it ranks queue victims). Also: C-Q02 statements with `read_gb` ≥ 1,000 or a low `pruning_ratio`; W-W04 / C-Q01 high `total_read_gb` from one client on a warehouse that meets the `distinct_sources` condition |
| Default tier | Investigate |
| Sizing | `perf_metric`, canonical `avg_read_gb_per_query` (`GB/query`) of the target source (vt-warehouse-drivers; W-W06 carries the same per-source value as `avg_read_gb_per_query` / `read_gb_per_query` over its own `window_days`, so quote the verify value); read TB in the window, `result_cache_pct` and share of warehouse duration go in `formula` (vt-heavy-statements). The warehouse's DBU is an upper reference, not a saving |
| Lever | Add date/key predicates, a materialized view, or liquid clustering on the filter columns; change the dashboard refresh schedule; move an interactive client off an ingestion warehouse |
| Disqualifiers | Never mix windows: W-W06 `total_read_bytes` covers `window_days` (usually 7), while P-AIBI04 `avg_read_mb` is per query over the pack window. Take per-query reads from one query (vt-warehouse-drivers `avg_read_gb_per_query`). Attribute a statement to a warehouse only by `compute.warehouse_id`. vt-warehouse-drivers unavailable (timed out, no staged fallback) → cut (`no_evidence`). If `run check` reports the id fired (its mechanical check can be looser than this trigger) but no warehouse meets the full trigger above, cut it (`disqualifier`) naming the unmet condition, e.g. "only single-tenant ingestion warehouses (`distinct_sources` 1) and no queueing" |
| Target selection | Per warehouse that meets the trigger, the top source by `non_capacity_duration_h` (capacity wait excluded; alias `exec_duration_h`), then by `read_tb`; a source with high `avg_capacity_wait_s` and low reads is a victim, not the target. One item per target warehouse (or per dashboard when the fix is that dashboard's SQL): coverage is per id, so the warehouses the trigger didn't pick need no item |
| Target kind | warehouse, dashboard |
| Verify | vt-warehouse-drivers, vt-heavy-statements |
| Notebook | Driver table; per-statement read/prune list; a step to pull the dataset SQL from the workspace; the post-change `avg_read_gb_per_query` measured for **the cited source only** (its `source_type` / `source_id` / `client_application`), not the warehouse average, so a change in workload mix can't pass for a fix |

### OPP-WH-RESIZE: recent upsize review

| Field | Rule |
|---|---|
| Trigger | `data.facts.recent_config_changes` (W-W07 `recent_changes`) shows a size or cluster-count change in the last 7 days |
| Default tier | Investigate: confirm the intent with the owner. Not now ("watch next cycle") when the warehouse had < 100 running hours in the window |
| Sizing | `perf_metric`, canonical `dbus_per_billed_hour_after` (`DBU/hour`); the before value goes in `formula` (vt-warehouse-change-rate). Label it "run-rate change, not a recoverable". Never multiply the hourly delta by a window |
| Lever | `cluster_size` back to the previous value (`databricks warehouses edit <id> --cluster-size <prev>`), only after the owner confirms the upsize isn't needed |
| Disqualifiers | Less than 24 h of billing after the change (vt-warehouse-change-rate `after_hours_sufficient` = `false`) → measure first; don't quote the after rate as the run-rate. The upsize answered a measured queue (OPP-WH-QUEUE) → treat it as that item's measurement step, not a revert candidate |
| Target selection | Largest DBU/hour delta |
| Target kind | warehouse |
| Verify | vt-warehouse-config-history, vt-warehouse-change-rate |
| Notebook | Before/after rate; queue and latency before/after on the same warehouse |

## Jobs

### OPP-JOB-OVERLAP: concurrent overlapping runs / `max_concurrent_runs`

| Field | Rule |
|---|---|
| Trigger | C-J08 `runs_started_while_running` ≥ 10% of `total_runs` **and** C-J08 `max_concurrent_runs` ≥ 2. `max_overlapping_runs_per_run` is **not** concurrency, so never quote it as "N concurrent" |
| Default tier | Act now when the overlap is in CRON runs (vt-job-overlap), the job is a top-10 job, the notebook re-measures runs and per-run DBU after the change, **and** both lever preconditions below hold. Investigate when the overlap is mostly ONETIME/backfill runs or looks like intentional fan-out |
| Sizing | `perf_metric`, canonical `pct_runs_started_while_running` (`%`, CRON runs); the CRON count, the concurrency (vt-job-overlap `max_concurrent_same_trigger` on the CRON row of the sized period, not C-J08 `max_concurrent_runs`: see the C-J08 note in the [signal map](#signal-map)), `avg_active_at_start` and `avg_run_mins` go in `formula`. An optional upper reference = overlapping CRON runs × (after − before `avg_dbus_per_run`), labelled "at stake, not a saving" |
| Lever | Job `max_concurrent_runs: 1` with `queue: {enabled: false}` (skip a trigger while a run is active). If the job is bundle-deployed, change it in the bundle source (`lever_command` kind `bundle_yaml`). **The cap applies to every run of the job**, not only CRON: run-now, ONETIME and backfill runs started while a run is active are skipped too (or queued, when queueing is on). Never write that ONETIME/backfill runs are "unaffected". **Precondition:** if vt-job-overlap shows concurrent ONETIME runs on the target job in the window, Act now requires the owner to confirm the backfill is finished or moved to a separate job (state it in `lever`, e.g. "precondition: backfill finished 2026-03-02 or moved to its own job"); without that confirmation the tier is Investigate at most (precedence step 3). **Cadence precondition:** when the CRON `avg_run_mins` (vt-job-overlap / vt-job-runs) is longer than the schedule interval (from the cron expression in vt-job-settings-history, or vt-job-overlap `median_cron_start_gap_mins` — the median gap between consecutive CRON starts — when the expression isn't carried; quote that column, don't infer the interval from runs per day), the overlap is structural: every run is still going when the next trigger fires, so the cap skips triggers and the job's **effective cadence becomes the run length** (a 90-min run on an hourly schedule runs about every 2 hours). That changes data freshness, which is not a low-risk lever unless the owner agrees. Act now then requires the owner to confirm the longer cadence is acceptable (state it in `lever`, e.g. "precondition: owner accepts ~2-hourly refresh"); without it the tier is Investigate (precedence step 3), and the first recommendation is to bring the run length back under the interval: the wait tasks (OPP-JOB-WAIT-TASK) or the cause of a run-length step change (OPP-STEP-CHANGE), with the cap as the follow-up. **Root-cause link:** when the job has a `wait_for_*` / `*_readiness` task in C-J09 / vt-task-durations (read every row, not only the top 5), check whether that wait grew at the step date: run vt-task-durations with `--split-date <data.facts.step_change.date>` and compare `p95_mins_before` with `p95_mins_after` for the wait task (successful CRON runs only, in one run). A readiness wait on a slower upstream is a common reason the run outgrew its interval; name the OPP-JOB-WAIT-TASK item on the same job in this item's `lever` and draw the link in the narrative |
| Disqualifiers | Overlap that comes only from ONETIME/backfill runs → this lever doesn't apply. Concurrent ONETIME runs alongside the CRON overlap → the precondition above (Investigate until the backfill is finished or moved). Parameterized chunk fan-out (many concurrent ONETIME runs by design) → Investigate "confirm the fan-out is intended". The current `max_concurrent_runs` is not carried in system tables, so the owner confirms it |
| Telemetry gap (state it up front) | `max_concurrent_runs` is not in system tables, and vt-job-settings-history `cron_expression` can be null on every row (it was on sampled jobs). Then the schedule interval for the cadence precondition **is** vt-job-overlap `median_cron_start_gap_mins`; say that is the source, and that the owner confirms `max_concurrent_runs` |
| Target selection | Highest DBU job in `data.facts.top_jobs` that meets the trigger; one item per job that meets it. Run vt-job-overlap split at `data.facts.step_change.date` when one exists, vt-job-settings-history for the schedule (cadence precondition) and deployment kind, and vt-task-durations `--split-date` on a job with a wait task (root-cause link) |
| Target kind | job |
| Verify | vt-job-overlap, vt-job-runs, vt-job-settings-history |
| Notebook | Overlap by trigger type before/after; the lever as a decision note (bundle YAML fragment for a bundle-deployed job, `new_settings` fragment otherwise) gated on the preconditions above, not an unconditional `jobs update`; re-measure runs per day (the effective cadence) and per-run DBU over a separate after-change window vs a baseline window |

### OPP-JOB-TIMEOUT: timeouts / long runs

| Field | Rule |
|---|---|
| Trigger | C-J03 `max_runtime_mins` ≥ 3 × `avg_runtime_mins`; C-J09 `max_duration_mins` ≫ `p95_duration_mins`; CRS-04 `runtime_max_minutes` |
| Default tier | Investigate (a runaway guard is a reliability fix). Not now when the tail runs are backfills |
| Sizing | `bounded_dbu` only from **per-run DBU**: Σ over the CRON tail runs of `excess_dbus` (= `run_dbus` − `p95_run_dbus`, floored at 0; both columns in vt-job-run-tail, where `p95_run_dbus` is the 95th percentile of per-run DBU over the job's CRON runs in the window). Write it as `Σ excess_dbus over N tail runs (run_dbus − p95_run_dbus <value>)`. Sum `excess_dbus` over **every** row of the saved verify json (read `data.rows` in full, not a preview of the first rows). Fallback, when `p95_run_dbus` or the tail `run_dbus` is null: `perf_metric`, canonical `max_run_mins` (`min`), with `p95_run_mins` in `formula`. **Performance-only path:** when Σ `excess_dbus` = 0 (the longest runs are long but not expensive, e.g. a 3,300-min run at 258 DBU under a 495 DBU p95), or the job already has a `timeout_seconds` in effect at the tail run, size it `perf_metric` `max_run_mins` too, with the p95, the excess sum (0) and the timeout in effect in `formula`: the impact is wall-clock and reliability, not DBU. Never sum a capped row list as a DBU bound in its place. Killed work is usually re-run, so state that this is not a guaranteed saving |
| Lever | Job `timeout_seconds` (or task `timeout_seconds`) set just above the CRON `p95_run_mins`; a `RUN_DURATION_SECONDS` health rule for alerting. The jobs system table is slowly changing (one row per `change_time`): read `timeout_seconds` from the version in effect at the tail run's start (latest `change_time` ≤ the run's `run_start`) in **vt-job-settings-history**, not the latest row (vt-job-runs shows only the latest). If the two differ, or the only version is newer than the tail run, say so in `formula` ("timeout set/changed after the tail run on <date>") and don't claim the run breached the current setting. A tail run longer than the `timeout_seconds` in effect at its start (e.g. a 900-min run under a 400-min timeout) means the timeout is set on a task, not the job, wasn't enforced, or the run spent part of its wall-clock queued or in setup (vt-job-run-tail `queue_mins`; no template returns a task-level `timeout_seconds`, so the owner confirms it). State that, and don't size it as a breach of the job timeout |
| Disqualifiers | Never "tail minutes × the job's average DBU/min". The job already has `timeout_seconds` as of the tail run (vt-job-settings-history shows each version where the jobs table carries it; pick the version per the lever row) → tune it, don't "add" one. The tail runs are ONETIME backfills → Not now. The tail is a wait/polling task → OPP-JOB-WAIT-TASK |
| Telemetry gap (state it up front) | System tables don't show **whether a timeout was enforced** or any **task-level** `timeout_seconds` (no template returns one). So when a run outlasts the job's `timeout_seconds` in effect (e.g. a 3,300-min run under a 450-min `timeout_seconds` on every settings row), telemetry can't say whether a task timeout, non-enforcement or queue/setup time explains it: the item is an **owner question** ("which timeout applies to task X, and why did run R pass it?"), Investigate, and its lever is decided after the answer. Say so in the first line of the item, not as a late caveat |
| Target selection | Largest Σ(tail `excess_dbus`) among CRON runs; when every candidate's sum is 0, the longest CRON `max_run_mins` (performance-only path) |
| Target kind | job |
| Verify | vt-job-runs, vt-job-run-tail, vt-job-settings-history |
| Notebook | Per-run duration and DBU distribution; the timeout setting as an operator cell |

### OPP-JOB-FAILURE: failed-run waste

| Field | Rule |
|---|---|
| Trigger | C-J04 `failure_dbus`; `data.facts.job_reliability.failure_rate_pct`; P-WF01 task `failure_rate_pct` ≥ 25 on a task with ≥ 20 runs |
| Default tier | **Not now** when failed-run DBU < 1% of `data.facts.total.dbus` (record it as "below materiality; flagged to owners", and name any high-failure-rate tasks in the reason). This disqualifier wins over a high task failure rate: a correctness concern below 1% of spend is flagged to owners, not carried. Investigate when failed-run DBU ≥ 1%. Act now only when it is ≥ 1% and has a named root cause and a fix |
| Sizing | Always `bounded_dbu` (never `pilot` or `none`, whatever the tier): `value` = Σ DBU of FAILED/ERROR/TIMED_OUT runs (vt-job-failures), as a number, `unit` `"DBU"`; report CANCELLED separately in `formula`. Label it "failed-run DBU, not recoverable: failed work is usually re-run". Example: `{"kind": "bounded_dbu", "value": 1400.0, "unit": "DBU", "formula": "ERROR 1,180.0 + TIMED_OUT 220.0 (vt-job-failures) = 0.40% of total; CANCELLED 900.0 separate; not recoverable"}` → Not now |
| Lever | The specific root-cause fix; task `max_retries` / `min_retry_interval_millis` only when the failures are transient |
| Disqualifiers | **Never Act-now #1 when failure waste is < 1% of spend.** C-J04 is capped at 50 rows and excludes cancelled runs, so don't call it "failed or cancelled" and don't sum it as a workspace total. P-WF01 task-minutes are not DBU |
| Target selection | Largest failed-run DBU per job; `workspace` when the item sizes the workspace-wide failed-run DBU (vt-job-failures) |
| Target kind | workspace, job |
| Verify | vt-job-failures, vt-job-runs |
| Notebook | Failed runs by job and terminal state; a step to pull the top error from run output |

### OPP-JOB-WAIT-TASK: long polling/wait tasks

| Field | Rule |
|---|---|
| Trigger | C-J09 / P-WF01 task keys that look like waiting (`wait`, `poll`, `sensor`, `readiness`) with high `total_task_hours`. Scan **every** C-J09 / P-WF01 row for these names, not the top few: a `wait_for_*_readiness` task ranked 7th or 11th still fires the id |
| Default tier | Investigate. A readiness wait on a job that also carries OPP-JOB-OVERLAP or sits in the OPP-STEP-CHANGE attribution is often the root-cause link (the upstream got slower, the wait grew, the run outgrew its interval): cross-reference those items |
| Sizing | `pilot — measure job wall-clock and DBU per run after replacing the wait`. Task-hours are not DBU |
| Lever | A table-update or file-arrival trigger (`trigger.table_update` / `trigger.file_arrival`) or a Run Job task dependency instead of a polling task |
| Disqualifiers | The wait guards an external dependency that has no trigger the job can use → cut (`disqualifier`). C-J09 / vt-task-durations unavailable → cut (`no_evidence`) |
| Target selection | Largest `task_hours` (vt-task-durations); one item per job. Run it with `--split-date <data.facts.step_change.date>` when there is a step: `p95_mins_before` → `p95_mins_after` of the wait task is the "did the wait grow" evidence OPP-JOB-OVERLAP and OPP-STEP-CHANGE cross-reference. Its rows are successful CRON runs only (skipped and zero-duration task runs dropped), so quote failure counts from C-J09 / P-WF01 |
| Target kind | job |
| Verify | vt-task-durations |
| Notebook | Task-duration table; the trigger change as an operator cell |

## Serverless

### OPP-SERVERLESS-STANDARD-MODE: `performance_target` pilot

| Field | Rule |
|---|---|
| Trigger | SVA-03 `performance_target` = PERFORMANCE_OPTIMIZED with `pct_of_product_dbus` ≥ 50 on JOBS or DLT; `data.facts.performance_mode.performance_optimized_pct` |
| Default tier | **Investigate, always**, until a pilot has measured it |
| Sizing | `pilot — measure DBU per run and wall-clock per run on <job> for 7 days vs the prior 7 days`. Databricks documents that standard mode "consumes fewer DBUs" but publishes no percentage, so never quote one and never extrapolate a percentage across the pool |
| Lever | Job-level `performance_target: STANDARD` (the other value is `PERFORMANCE_OPTIMIZED`); in the job UI, clear "Performance optimized". A pipeline triggered by a job's pipeline task runs with that job task's setting. On a **bundle-deployed** job (vt-job-settings-history `deployment_kind` = `BUNDLE`) the change goes in the bundle source (`lever_command` kind `bundle_yaml`); a `jobs update` would be overwritten by the next deploy and silently end the pilot |
| Disqualifiers | Interactive or SQL workloads; jobs with an SLA tighter than the run time plus about 6 minutes (standard mode starts in 4–6 minutes); continuous/streaming pipelines; a job that has an **Act-now** change this cycle (the two changes would confound the measurement). Only an Act-now item on the same job disqualifies it: an Investigate or Not-now item on the job is a measurement or an owner question, not a change this cycle, so it doesn't. Say in `lever` that the pilot goes first or after, never at the same time as, any change that item later leads to |
| Target selection | The highest-DBU job in `data.facts.top_jobs` that is CRON-triggered, has no SLA constraint, has an average run ≥ 30 min (so 4–6 min of startup is < 20% of the run), and has no Act-now item this cycle. Run vt-job-runs on that pilot job |
| Target kind | job |
| Verify | vt-perf-target-mix, vt-job-runs |
| Notebook | Before/after CRON DBU per run and wall-clock per run on the target job, as separate baseline and pilot windows (not the workspace mode mix); the `performance_target` change as an operator cell |

## Spend shape

### OPP-STEP-CHANGE: investigate a spend step change

| Field | Rule |
|---|---|
| Trigger | `data.facts.step_change` is not null (C-B04 `step_dbu_lift`); C-B03 large `wow_growth_pct` on a top job |
| Default tier | Investigate (the cause is owner context) |
| Sizing | `none`: quote `data.facts.step_change.lift_daily_dbus` and the per-workload before/after averages (vt-step-change) as "size of the problem". It is not a recoverable. Never multiply it by a window, and don't call accrued spend "recoverable". For "current run-rate", quote `data.facts.step_change.current_7d_avg_daily_dbus`, `pre_step_avg_daily_dbus` and `current_vs_pre_ratio` verbatim; don't re-derive them from vt-daily-totals. vt-step-change rows are the top workloads only (`LIMIT 15`), so never sum them as the workspace lift: the workspace lift is the fact, and the rows are attribution |
| Lever | The owner confirms the cause (deploy, new source, backfill). If it is a regression, revert or fix that change |
| Disqualifiers | Intended data growth confirmed by the owner → Not now. A lift driven by ONETIME/backfill runs → split by trigger (vt-job-overlap / vt-job-runs) before you attribute it. A top-lift job with a `wait_for_*` / `*_readiness` task → check the wait at the step date (vt-task-durations `--split-date <step date>`: `p95_mins_before` vs `p95_mins_after`) and cross-reference its OPP-JOB-WAIT-TASK item: a slower upstream can lengthen every downstream run |
| Target selection | One `workspace` item; workloads in vt-step-change ordered by `lift_daily_dbus` are the attribution in `formula` |
| Target kind | workspace |
| Verify | vt-step-change, vt-daily-totals |
| Notebook | Per-workload before/after; per-run DBU split by trigger type |

## Pipelines

### OPP-DLT-CADENCE: pipeline trigger cadence / full refresh

| Field | Rule |
|---|---|
| Trigger | A top pipeline in `data.facts.top_pipelines` with P-DLT06 `updates_billed` ≥ 24/day or high `avg_dbus_per_update`; any full-refresh updates; the vt-pipeline-updates `trigger_type_mix` (CRS-05 `latest_trigger_type` is only the latest update's type) |
| Default tier | Investigate (cadence depends on the owner's freshness need) |
| Sizing | `bounded_dbu` only when the owner states a target cadence: (current updates − target updates) × `dbus_per_update` (vt-pipeline-updates; a context ratio over the calendar window, not the marginal cost of one update). Otherwise `pilot — measure DBU/day after the cadence change` |
| Lever | The schedule of the job that triggers the pipeline; full-refresh off for routine updates; `continuous: false` where streaming isn't required |
| Disqualifiers | A documented freshness SLA that needs the current cadence; continuous streaming pipelines (no cadence to change) |
| Target selection | Largest `pipeline_dbus`; one item per pipeline |
| Target kind | pipeline |
| Verify | vt-pipeline-updates |
| Notebook | Updates/day, full refreshes, DBU per update |

## Clusters

### OPP-CLUSTER-RIGHTSIZE

| Field | Rule |
|---|---|
| Trigger | CRS-01 / CRS-06 `sizing_reason` or `sizing_direction` = oversized; C-C01 `avg_cpu_pct` < 30 with material `total_dbus`; C-C02 idle all-purpose clusters |
| Default tier | Investigate; Not now when the classic job DBU (a number: state it in `sizing.value`; vt-cluster-driver-attribution `classic_dbus_total`) is < 1% of spend; cut (`disqualifier`) when CRS rates the clusters RIGHT_SIZED |
| Sizing | `bounded_dbu` = cluster `total_dbus` × CRS-06 `reduction_pct` when CRS-06 returns rows; otherwise `pilot — measure runtime and DBU per run on the smaller size` |
| Lever | `node_type_id`, `num_workers`, or `autoscale.max_workers` on the job cluster; `autotermination_minutes` for all-purpose clusters; on a single-node (driver-only) job cluster, the driver `node_type_id` |
| Disqualifiers | CRS-06/07/08 return only the status row (`status = 'NO_WORKER_SAMPLES'`, numeric columns null) → can't size workers, so use the pilot. That status row does **not** void the CRS-01 **driver** rows: a SEVERELY_OVERPROVISIONED driver on a single-node cluster (vt-cluster-driver-attribution `max_worker_count` 0) is the whole cluster's utilisation, so keep it as the signal. A CRS cluster missing from a capped extract is not "no evidence": attribute it with vt-cluster-driver-attribution, which aggregates every billed classic cluster. Serverless compute has no node sizing |
| Target selection | Largest `total_dbus` with an oversized signal. Tie each oversized CRS-01 cluster (driver or worker row) to its job: CRS-01 rows carry `job_id` / `job_name` / `cluster_dbus` (`attributed_job_count` > 1 = a shared cluster); confirm the job and its full-day DBU with vt-cluster-driver-attribution, and pick by that job's `cluster_dbus`; then run vt-job-runs on the job for per-run DBU |
| Target kind | cluster, job |
| Verify | vt-cluster-driver-attribution, vt-job-runs |
| Notebook | CPU/memory percentiles; the sizing change as an operator cell |

## Platform products

### OPP-LAKEBASE: Lakebase usage review

| Field | Rule |
|---|---|
| Trigger | P-LB01 / P-LB04 `total_units` or `pct_change`; SVA-02 Lakebase rows |
| Default tier | **Investigate** (catalog default). The confirming step is the endpoint/instance audit. Do not move it to Not now because it is small; record the size and keep the step |
| Sizing | `none`: Lakebase DBU and DSU totals kept separate (vt-product-totals). Per-instance attribution is unavailable: billing `endpoint_id` (`ep-*`) has no join path to the instance API |
| Lever | The owner reviews instance capacity and stops unused instances (inventory: `starboard-helper database instances`) |
| Disqualifiers | No Lakebase billing in the window → cut (`disqualifier`), "no Lakebase billing in the window" |
| Target selection | Workspace total |
| Target kind | workspace |
| Verify | vt-product-totals |
| Notebook | Lakebase DBU/DSU by day; instance inventory step |

### OPP-PO: predictive optimization

| Field | Rule |
|---|---|
| Trigger | C-B01 / P-AUDIT01 PREDICTIVE_OPTIMIZATION DBU; PO-01 `operation_count` by type |
| Default tier | Not now (PO is usually a net benefit). Investigate only when PO DBU ≥ 5% of `data.facts.total.dbus` |
| Sizing | `none`, or `pilot — measure PO DBU and query latency on the scoped schemas after the change` |
| Lever | `ALTER SCHEMA <catalog>.<schema> DISABLE PREDICTIVE OPTIMIZATION` (or `INHERIT`), scoped to high-churn schemas only |
| Disqualifiers | PO-01 `catalog_name`/`schema_name` null → you can't scope it, so don't recommend disabling. Never recommend disabling PO workspace-wide |
| Target selection | Schemas with the most operations; one `workspace` item, with the scoped schemas named in `lever` |
| Target kind | workspace |
| Verify | vt-product-totals |
| Notebook | PO DBU by day; operations by schema |

### OPP-OTHER (justification required)

Use OPP-OTHER only when no id above fits. The backlog `title` must start with the reason no id
fits, and the item still needs a trigger (query id + column + value), a sizing kind with a formula,
an exact lever, and a verify file for Act now or Investigate. Hygiene items (dormant warehouses,
draft pipelines, stale tables) go here as Not now unless they carry material DBU.

---

## Signal map

Every envelope query maps to an id or is cut with a reason. "facts" means the query feeds
`data.facts`. Quote facts, don't re-derive them.

| Query | Maps to | Notes / cut reason |
|---|---|---|
| P-AUDIT01 | context | Product detection. A detected product with no pack is a coverage gap, not an opportunity |
| C-B01, C-B02 | facts | Totals, mix, months. Use `usage_unit`: DBU and DSU are never summed |
| C-B03 | OPP-STEP-CHANGE | Week-over-week growth on a top job |
| C-B04 | OPP-STEP-CHANGE | `step_date`, `step_dbu_lift`, per-job before/after |
| C-J01 | facts (`top_jobs`) | Target selection for job ids |
| C-J03 | OPP-JOB-TIMEOUT | |
| C-J04 | OPP-JOB-FAILURE | Capped at 50 rows; excludes cancelled |
| C-J05 | facts (`job_reliability`) → OPP-JOB-FAILURE | `job_reliability` (F-06) uses the vt-job-failures definition: one row per run by final state, runs whose last period ended in `job_reliability.window`; `failed_runs` = FAILED + ERROR + TIMED_OUT (`failed_states`, `failed_by_state`). Reconcile on that window; a run or two of drift is source refresh between discovery and verify |
| C-J08 | OPP-JOB-OVERLAP | Trigger: use `max_concurrent_runs`, not `max_overlapping_runs_per_run`. In the plan, quote vt-job-overlap `max_concurrent_same_trigger` on the CRON row of the sized period (post-step when split): it is verified and scoped to scheduled runs. C-J08 `max_concurrent_runs` spans the whole pack window and every trigger type, so it is usually higher (7 vs 6 is normal); cite it as discovery context only |
| C-J09 | OPP-JOB-WAIT-TASK, OPP-JOB-TIMEOUT | |
| C-C01, C-C02 | OPP-CLUSTER-RIGHTSIZE | |
| C-C03, C-Q05 | OPP-WH-QUEUE | |
| C-Q01, C-Q02, C-Q03 | OPP-WH-SCAN | C-Q03 is skipped when statement hashes aren't carried (coverage gap) |
| N-L01, N-L02 | cut | Skipped in practice; no catalog lever |
| N-DT01 | OPP-OTHER (hygiene) | Stale tables; Not now unless material |
| N-NB01 | OPP-OTHER | Interactive notebook DBU; only if material |
| P-LB01, P-LB03, P-LB04, SVA-01, SVA-02 | OPP-LAKEBASE | |
| SVA-03 | OPP-SERVERLESS-STANDARD-MODE | |
| P-AIBI01–04, P-GEN02 | OPP-WH-QUEUE (queued Genie/dashboard), OPP-WH-SCAN (`avg_read_mb`) | P-AIBI04 / P-GEN02 carry `warehouse_id` (one row per dashboard or space × warehouse): use it to pick the OPP-WH-QUEUE target warehouse |
| P-SQL01 | facts (`warehouses`) | Classic vs serverless trend context |
| P-SQL02 | OPP-WH-QUEUE | Cold-start context |
| P-WF01 | OPP-JOB-FAILURE (task), OPP-JOB-WAIT-TASK | |
| P-DLT01 | OPP-OTHER (hygiene) | Do not infer staleness from null timestamps where they aren't carried |
| P-DLT03, P-DLT06, P-DLT11, CRS-05 | OPP-DLT-CADENCE | |
| PO-01 | OPP-PO | |
| W-W01 | OPP-WH-QUEUE | Ignore `utilization_band` on serverless. `utilization_ratio` = busy query-time ÷ wall-clock time; > 1 means queries overlapped (concurrency), **not** saturation: a 2.7 ratio with 0.02% queued is a busy, healthy warehouse. Queueing evidence is `queued_query_pct` / vt-warehouse-queue |
| W-W02 | OPP-WH-IDLE; disqualifier for OPP-WH-CLASSIC-TO-SERVERLESS | `est_idle_dbus` is null for serverless |
| W-W03, W-W04, W-W05 | context for OPP-WH-QUEUE / OPP-WH-SCAN / OPP-WH-CLASSIC-TO-SERVERLESS | |
| W-W06 | OPP-WH-SCAN, OPP-WH-QUEUE (driver) | `total_read_bytes` is over `window_days`: 7 full days plus the partial discovery day, while vt-warehouse-drivers reads the 7 full days ending `facts.window.end`. Reconcile the two only on the same window (vt-warehouse-drivers with `--set qh_start/qh_end` = W-W06's window; see verify-sql.md). Rank by `pct_of_warehouse_exec` (not `pct_of_warehouse_duration`); `distinct_sources` and `warehouse_queued_pct` are per-warehouse context on every row (single-tenant ingestion warehouses have `distinct_sources` 1–2) |
| W-W07 | facts (`recent_config_changes`) → OPP-WH-RESIZE; disqualifier for OPP-WH-QUEUE | |
| CR-01–03 | context for OPP-WH-IDLE | Warehouse lifecycle (starts/stops), not exit codes |
| CRS-01–04, CRS-06–08 | OPP-CLUSTER-RIGHTSIZE (CRS-04 also OPP-JOB-TIMEOUT) | Empty CRS-06–08 = no samples, so can't size workers. CRS-01 lists the highest-DBU billed classic clusters with `job_id` / `job_name` / `attributed_job_count` / `cluster_dbus`; a driver row on a single-node cluster still counts (vt-cluster-driver-attribution) |

## Anti-examples (from the 2026-10-01 six-model run and later prompt tests)

Each of these appeared in a real plan. Each one breaks a rule above.

| Wrong claim | Why it is wrong | Correct form |
|---|---|---|
| "Up to ~75K DBU/30d recoverable" from a +2,500 DBU/day step | rate × window. A daily lift is the size of a problem, not a bound on a saving | OPP-STEP-CHANGE, Investigate, `sizing.kind: none`: "+2,500 DBU/day after 2026-03-02 (vt-step-change); cause unconfirmed" |
| "+75K/month above last month" | rate × window used as a forecast | Quote `data.facts.months` (last full vs prior full month) verbatim |
| "20% idle reduction = 1,900 DBU" on warehouses with ≤ 0.5% idle | Invented idle share; W-W02 shows almost no idle | OPP-WH-CLASSIC-TO-SERVERLESS → cut, `rule: disqualifier`, "no idle to remove" |
| Failure waste (< 0.5% of spend) as Act-now #1, "up to 1,400 DBU recoverable" | Below materiality; failed work is re-run; C-J04 is capped and excludes cancelled | OPP-JOB-FAILURE → Not now, "below materiality; flagged to owners" |
| "Raise max clusters" on a warehouse whose `max_clusters` went 1→2 the day before | Ignores `recent_config_changes` | OPP-WH-QUEUE, Investigate: measure the change with vt-warehouse-queue split at the change time; fix the driver first |
| "Timeout saves 3,600 DBU" = tail minutes × average DBU/min | No per-run DBU; tails were backfills; killed work is re-run | OPP-JOB-TIMEOUT: Σ tail `excess_dbus` (`run_dbus` − `p95_run_dbus`) from vt-job-run-tail, or `perf_metric` |
| "Up to 40 concurrent instances" | `max_overlapping_runs_per_run` is not concurrency (C-J08 `max_concurrent_runs` was 6) | Quote vt-job-overlap `max_concurrent_same_trigger` (CRON row, sized period) |
| "`max_concurrent_runs: 1` stops the CRON overlap; ONETIME/backfill runs are unaffected" | The cap applies to every run of the job: run-now, ONETIME and backfill runs started while a run is active are skipped (or queued) too | OPP-JOB-OVERLAP: say the cap covers all runs; with concurrent ONETIME runs on the job, Act now needs "backfill finished or moved", otherwise Investigate |
| "`max_concurrent_runs: 1` is a low-risk Act-now fix" on a job whose CRON runs average 90 min on an hourly schedule (600 CRON runs in 25 days, 85% started while another was running) | The run is longer than the interval, so the cap skips about every other trigger: the job becomes roughly 2-hourly. That is a freshness change the owner hasn't agreed to, not a low-risk lever | OPP-JOB-OVERLAP, Investigate: "confirm a ~2-hourly cadence is acceptable"; first bring the run under 60 min (wait tasks, the run-length step change), then apply the cap. Act now only with the owner's cadence confirmation in `lever` |
| "Dashboard D drives the queue" because it tops vt-warehouse-drivers by `pct_of_warehouse_duration` (55%) while reading 0.04 GB/query with a 150 s average capacity wait | Total duration includes capacity wait, so the source that waits most tops that list. D is a victim of the queue, not its cause | Rank drivers by `non_capacity_duration_h` (or `read_tb`): the driver is the source with 120 GB/query; D is named as affected |
| OPP-JOB-OVERLAP sized as 120 (a CRON count), 80 (a %) and 6 (max concurrency) in three runs of the same workspace | Three different metrics under one id can't be compared | `sizing.metric: pct_runs_started_while_running`, `unit: "%"`, value 80; the count and the concurrency go in `formula` ([canonical perf metrics](#canonical-perf-metrics)) |
| "Job has no timeout" from the latest jobs-table row when the tail run predates the `timeout_seconds` change | The jobs table is slowly changing; the latest row is not the setting the tail run ran under | Read `timeout_seconds` as of the tail run's start from vt-job-settings-history, or flag "timeout set after the tail run" in `formula` |
| Two OPP-WH-QUEUE items with no `target`, or the same id three times on the same job | Runs can't be compared item-for-item and the duplicates double-count | One item per `(id, target)`, `target: "warehouse:<id>"`; a covered second signal is `cut` with `rule: duplicate` |
| Σ `excess_dbus` = 54.6 from the first 10 of 20 vt-job-run-tail rows (the full sum was 265.6) | A preview isn't the population; the technical review didn't recompute it | Sum every row of the saved verify json; the technical review recomputes each `bounded_dbu` from the full file |
| Two fired OPP-DLT-CADENCE pipelines cut `no_evidence` because vt-pipeline-updates "didn't fit the 8-verify budget" | `no_evidence` means the source lacks the evidence, not that verify wasn't run; the minimum is a floor | Run vt-pipeline-updates on each candidate; cut `no_evidence` only after an attempt fails (`ok: false` file saved) |
| Act-now overlap cap on a job whose `wait_for_upstream_readiness` task (C-J09 row 11) doubled at the step date, with no link drawn | The wait explains the run outgrowing its interval; the cap treats the symptom | OPP-JOB-WAIT-TASK on the same job, cross-referenced from OPP-JOB-OVERLAP and OPP-STEP-CHANGE |
| OPP-WH-SCAN fired on 7 of 7 warehouses, including single-connector ingestion warehouses at 100% of their own duration | The old trigger keyed on `pct_of_warehouse_duration` with no tenancy or queueing condition; one client owning its own ingestion warehouse is not a scan problem | Trigger on `pct_of_warehouse_exec` ≥ 30 with `distinct_sources` ≥ 3 and queueing or material reads; one item per target the target-selection rule picks |
| A `jobs update --json '{"performance_target": "STANDARD"}'` pilot on a bundle-deployed job | The next bundle deploy overwrites it and silently ends the pilot | `lever_command` kind `bundle_yaml` (bundle source change + redeploy); rollback = revert the bundle source |
| "Standard mode cuts DBU by up to X%" | No documented percentage | `pilot — measure DBU per run` |
| Lakebase → Not now with no audit step | Breaks the Lakebase default | OPP-LAKEBASE, Investigate, endpoint audit as the step |
