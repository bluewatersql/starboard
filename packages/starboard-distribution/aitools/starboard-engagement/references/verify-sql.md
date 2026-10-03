# Verify SQL templates (public `system.*`)

Copy-paste templates for the `verify` beat ([verify.md](verify.md)). Each one re-derives a signal
from the source system tables at a finer grain than the discovery pack. The
[opportunity catalog](../../starboard-action-plan/references/opportunity-catalog.md) names the
templates each opportunity needs.

**How to run one.** Use the helper; don't fill templates by hand. It reads the template from
this file, fills the `{placeholders}` from its flags, runs it read-only, and writes the
`.sql`/`.json` pair (`<vt-id>[-<suffix>]`, e.g. `vt-job-overlap-348089368173138`):

```bash
starboard-helper verify list --templates <this-dir>/verify-sql.md     # template ids + placeholders
starboard-helper verify run vt-job-overlap --templates <this-dir>/verify-sql.md \
  --ws <workspace-id> --start <facts.window.start> --end <facts.window.end> \
  --job-ids <id1>,<id2> --split-date <facts.step_change.date> --suffix 348089368173138 \
  --out <run-dir>/analysis/verify/
```

Flags: `--ws` → `{ws}`; `--start` / `--end` → `{start}` / `{end}` (take them from
`data.facts.window`); `--job-ids` / `--warehouse-ids` / `--pipeline-ids` → the target ids;
`--split-date` → `{split_date}` / `{step_date}`; `--suffix` names the target in the file name.
Id lists take commas (`--job-ids 1,2`), spaces (`--job-ids 1 2`) or a repeated flag
(`--job-ids 1 --job-ids 2`). Check `verify run --help` for the rest. The table below is what each placeholder means. If a
template doesn't fit, hand-written SQL saved with the same `.sql`/`.json` naming is allowed
(`starboard-helper query sql --warehouse-id <wh-id> --rows objects --sql "$(cat <file>.sql)"`);
it must follow the rules below. `notebook render` embeds such a custom `.sql` in the notebook's
evidence cell when it is a single read-only `SELECT` that reads only `system.*` tables and filters
`workspace_id = '<ws>'`; otherwise it lists the file under `evidence_not_embedded` in its result,
and you add that comparison to the notebook by hand (and the technical review checks it).

**Derived placeholders.** You don't pass these; `verify run` fills them, and `--set NAME=VALUE`
overrides any of them: `{qh_start}` / `{qh_end}` = the 7-day window ending `--end` (clamped to
`--start`); `{window_days}` and `{lookback_days}` = the inclusive days `--start`…`--end`;
`{step_date}` / `{before_start}` / `{before_end}` / `{after_end}` = the 7-day bounds around
`--split-date`; `{change_time}` = `--split-date` at `00:00:00`. Pass `--set change_time='YYYY-MM-DD HH:MM:SS'`
for an exact config-change time. `verify list` shows each template's derived and required
placeholders.

**Failures and parallelism.** A verify that fails after its `.sql` is written (query error,
timeout) still writes the `.json`, with `ok: false` and the error. It prints the error on stderr
and exits non-zero, so a pair is never half-written. That failed `.json` is the record the staged
fallback below keeps. Run **at most 3 verifies at once** on a shared warehouse; the timeline and
query-history templates are heavy. Run the rest in waves, or simply one after another (a
sequential single stream is fine and the simplest), and re-run a failed one on its own before you
fall back. Check the `ok` field of each `.json`, not only the exit code of a pipeline (`| tail`
reports `tail`'s exit; use `set -o pipefail`). A **bad-arguments** exit (4) found after the
template id is known (a flag the template needs is missing, a placeholder is unfilled) also writes
the `.json` with `ok: false`, so the attempt is on record. One found before that (an unknown
template id, an unparseable command line such as an unsplit flag string under zsh) writes **no**
`.json`, so check the exit code too: no file means no attempt.

**Which flags a template needs.** `--start` / `--end` are required only when the template uses a
date-derived placeholder (`{start}`, `{end}`, `{qh_start}`, `{qh_end}`, `{window_days}`,
`{lookback_days}`); vt-job-settings-history (`{ws}` + `{job_ids}`) runs without them. `verify list`
reports the same `required` set the runner enforces. Passing the facts window on every call is
harmless.

**Numeric columns are JSON numbers** (typed from the result manifest: DECIMAL, BIGINT, DOUBLE),
for templates and hand-written `query sql` alike, so sum them directly.

**Row shape.** `verify run` writes `data.rows` as objects keyed by column name by default
(`--rows arrays` gives the positional `data.columns` + `data.rows[[…]]` shape). Read values by
name, e.g. `jq '[.data.rows[].excess_dbus // 0] | add' <file>.json`, never by column index.

**If a 7-day query-history template times out** (`vt-warehouse-queue`, `vt-warehouse-drivers`,
`vt-heavy-statements`): keep the failed `.json` (`ok: false`), then re-run on **one full day** (`--start` =
`--end` = the last full day of the window, `--suffix <target>-1d`) and cite both files. A
one-day cut can't show the signal holds across days, so it earns no **Stable** point and the item
is capped at **Investigate** ([verify.md](verify.md#confidence-rubric)).

| Placeholder | Value |
|---|---|
| `{ws}` | Workspace id. **Always filter on it**: system tables cover every workspace in the account |
| `{start}`, `{end}` | `data.facts.window.start` / `.end`: full days, inclusive, excluding today |
| `{step_date}`, `{split_date}` | `data.facts.step_change.date`; for no split, use `{start}` |
| `{before_start}`, `{before_end}`, `{after_end}` | `data.facts.step_change.before_start` / `.before_end` / `.after_end`: the 7-day bounds the facts step used |
| `{job_id}`, `{job_ids}` | One job id, or a quoted list: `'123', '456'` (from `data.facts.top_jobs`) |
| `{warehouse_id}` | Warehouse id |
| `{change_time}` | `data.facts.recent_config_changes[].change_time`, as `YYYY-MM-DD HH:MM:SS` (derived: `--split-date 00:00:00`; `--set` the exact time) |
| `{qh_start}`, `{qh_end}` | Query-history window: **7 days or fewer** (the heaviest table; derived: the 7 days ending `--end`) |
| `{lookback_days}` | Config-history lookback in days (derived: the window length) |
| `{window_days}` | `data.facts.window.days` (derived from `--start`/`--end`) |

**Rules the templates already follow (keep them if you adapt one)**

- Full days only: `usage_date BETWEEN {start} AND {end}`, with `{end}` before today.
- DBU and DSU are separate: filter `usage_unit = 'DBU'`, or group by `usage_unit`. Never sum them.
- Per-day averages divide by `COUNT(DISTINCT usage_date)` over the period, never by a row count.
- Job and pipeline timelines are aggregated in **two levels**: hourly periods → one row per run
  (`MIN(period_start_time)`, `MAX(period_end_time)`, `MAX_BY(result_state, period_end_time)`,
  `MAX_BY(trigger_type, period_end_time)`) → one row per job. `MAX(result_state)` is
  lexicographic and wrong. Runs are selected by when they **ended**.
- Split job metrics by `trigger_type`. CRON and ONETIME (backfill) runs have very different costs.
- Warehouse attribution: billing uses `usage_metadata.warehouse_id`; query history uses
  `compute.warehouse_id`. Neither table has a top-level `warehouse_id`.

**Cluster right-sizing (CRS-06–08) disqualifier.** CRS-06–08 have no verify template of their
own (cluster → job attribution is vt-cluster-driver-attribution): read the pack's `status`
column. When the window has no worker-node samples, each of CRS-06/07/08 returns **one status
row** with `status = 'NO_WORKER_SAMPLES'`, every numeric column null and a `reason`. That row is the "can't size" signal; the result is not empty. Only `status = 'SCORED'` rows are sizing
verdicts. Never treat the status row as a recommendation, and never wait for an empty result.

**Column check:** every column used here was confirmed with `DESCRIBE` on 2026-10-01 against a
telemetry copy of these tables that has the same columns, and every template ran first try on
that copy (table names swapped) in four end-to-end runs; the 2026-10-02 revisions of
vt-job-settings-history, vt-task-durations, vt-warehouse-change-rate and vt-warehouse-drivers ran
first try the same way. Where your workspace's system-table version lacks a column (for example
`timeout_seconds` on `system.lakeflow.jobs`), drop that column. Names differ by table:
`system.lakeflow.jobs` has `name`; `system.compute.warehouses` has `warehouse_name` and **no
`name` column**.

---

## Billing

### vt-product-totals: product totals, full days, DBU and DSU separate

Full precision: `quantity` is unrounded so small lines (a 0.86 DSU Lakebase total, a 0.03 DBU
AI Gateway line) don't round to 0 and reconcile exactly with `data.facts.total` /
`product_mix`. Round only when you present the number.

```sql
SELECT billing_origin_product,
       usage_unit,
       SUM(usage_quantity)        AS quantity,
       COUNT(DISTINCT usage_date) AS days_billed
FROM system.billing.usage
WHERE workspace_id = '{ws}'
  AND usage_date BETWEEN DATE'{start}' AND DATE'{end}'
GROUP BY billing_origin_product, usage_unit
ORDER BY usage_unit, quantity DESC
```

### vt-daily-totals: daily DBU

```sql
SELECT usage_date,
       ROUND(SUM(usage_quantity), 1) AS dbus
FROM system.billing.usage
WHERE workspace_id = '{ws}'
  AND usage_unit = 'DBU'
  AND usage_date BETWEEN DATE'{start}' AND DATE'{end}'
GROUP BY usage_date
ORDER BY usage_date
```

### vt-step-change: per-workload before/after a step date

Uses the **same 7-day bounds as `data.facts.step_change`**: before = `{before_start}`…`{before_end}`,
after = `{step_date}`…`{after_end}` (7 full days each, inclusive). Don't widen it to the whole
facts window: unequal spans (e.g. 13 vs 17 days) give a different lift. The rows are the **top 15
workloads only** (`LIMIT 15`), so they are attribution, not a total: never sum them as the
workspace lift. The workspace lift is `data.facts.step_change.lift_daily_dbus` (quote it), and the
current run-rate is `data.facts.step_change.current_7d_avg_daily_dbus` vs `pre_step_avg_daily_dbus`
(`current_vs_pre_ratio`); vt-daily-totals shows the daily curve. Denominators are the calendar days in each period, so a workload that only ran on
some days isn't inflated. `active_days_before` shows new workloads.

```sql
WITH daily AS (
  SELECT usage_date,
         CASE WHEN usage_metadata.dlt_pipeline_id IS NOT NULL THEN 'pipeline'
              WHEN usage_metadata.job_id          IS NOT NULL THEN 'job'
              WHEN usage_metadata.warehouse_id    IS NOT NULL THEN 'warehouse'
              ELSE 'other' END                                          AS workload_type,
         COALESCE(usage_metadata.dlt_pipeline_id, usage_metadata.job_id,
                  usage_metadata.warehouse_id, billing_origin_product)  AS workload_id,
         SUM(usage_quantity)                                            AS dbus
  FROM system.billing.usage
  WHERE workspace_id = '{ws}'
    AND usage_unit = 'DBU'
    AND usage_date BETWEEN DATE'{before_start}' AND DATE'{after_end}'
  GROUP BY 1, 2, 3
),
days AS (
  SELECT COUNT(DISTINCT CASE WHEN usage_date <  DATE'{step_date}' THEN usage_date END) AS before_days,
         COUNT(DISTINCT CASE WHEN usage_date >= DATE'{step_date}' THEN usage_date END) AS after_days
  FROM daily
)
SELECT d.workload_type,
       d.workload_id,
       MAX(days.before_days)                                                            AS before_days,
       MAX(days.after_days)                                                             AS after_days,
       COUNT(DISTINCT CASE WHEN d.usage_date < DATE'{step_date}' THEN d.usage_date END) AS active_days_before,
       ROUND(COALESCE(SUM(CASE WHEN d.usage_date <  DATE'{step_date}' THEN d.dbus END), 0) / MAX(days.before_days), 1) AS before_avg_daily_dbus,
       ROUND(COALESCE(SUM(CASE WHEN d.usage_date >= DATE'{step_date}' THEN d.dbus END), 0) / MAX(days.after_days), 1)  AS after_avg_daily_dbus,
       ROUND(COALESCE(SUM(CASE WHEN d.usage_date >= DATE'{step_date}' THEN d.dbus END), 0) / MAX(days.after_days)
           - COALESCE(SUM(CASE WHEN d.usage_date <  DATE'{step_date}' THEN d.dbus END), 0) / MAX(days.before_days), 1) AS lift_daily_dbus
FROM daily d CROSS JOIN days
GROUP BY d.workload_type, d.workload_id
ORDER BY lift_daily_dbus DESC
LIMIT 15
```

### vt-perf-target-mix: serverless `performance_target` mix

```sql
SELECT billing_origin_product,
       COALESCE(product_features.performance_target, 'NULL')            AS performance_target,
       CASE WHEN usage_metadata.dlt_pipeline_id IS NOT NULL THEN 'pipeline' ELSE 'job' END AS workload_type,
       COALESCE(usage_metadata.dlt_pipeline_id, usage_metadata.job_id)  AS workload_id,
       ROUND(SUM(usage_quantity), 1)                                     AS dbus,
       ROUND(100 * SUM(usage_quantity) / SUM(SUM(usage_quantity)) OVER (), 2) AS pct_of_pool
FROM system.billing.usage
WHERE workspace_id = '{ws}'
  AND usage_unit = 'DBU'
  AND product_features.is_serverless = true
  AND billing_origin_product IN ('JOBS', 'DLT')
  AND usage_date BETWEEN DATE'{start}' AND DATE'{end}'
GROUP BY 1, 2, 3, 4
ORDER BY dbus DESC
LIMIT 25
```

## Jobs

### vt-job-runs: per-job two-level timeline (per run → per job × trigger)

```sql
WITH runs AS (  -- level 1: hourly periods -> one row per run
  SELECT job_id,
         run_id,
         MIN(period_start_time)                AS run_start,
         MAX(period_end_time)                  AS run_end,
         MAX_BY(result_state, period_end_time) AS result_state,
         MAX_BY(trigger_type, period_end_time) AS trigger_type
  FROM system.lakeflow.job_run_timeline
  WHERE workspace_id = '{ws}'
    AND period_end_time >= DATE_SUB(DATE'{start}', 3)
    AND job_id IN ({job_ids})
  GROUP BY job_id, run_id
  HAVING MAX(period_end_time) >= DATE'{start}' AND MAX(period_end_time) < DATE_ADD(DATE'{end}', 1)
),
run_dbu AS (
  SELECT usage_metadata.job_id AS job_id, usage_metadata.job_run_id AS run_id, SUM(usage_quantity) AS dbus
  FROM system.billing.usage
  WHERE workspace_id = '{ws}'
    AND usage_unit = 'DBU'
    AND usage_date BETWEEN DATE_SUB(DATE'{start}', 3) AND DATE_ADD(DATE'{end}', 1)
    AND usage_metadata.job_id IN ({job_ids})
    AND usage_metadata.job_run_id IS NOT NULL
  GROUP BY 1, 2
),
jobs AS (
  SELECT job_id, name, timeout_seconds
  FROM system.lakeflow.jobs
  WHERE workspace_id = '{ws}'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY job_id ORDER BY change_time DESC) = 1
)
SELECT r.job_id,                          -- level 2: runs -> one row per job x trigger_type
       j.name,
       j.timeout_seconds,
       r.trigger_type,
       COUNT(*)                                                                             AS runs,
       SUM(CASE WHEN r.result_state IN ('FAILED', 'ERROR', 'TIMED_OUT') THEN 1 ELSE 0 END) AS failed_runs,
       SUM(CASE WHEN r.result_state = 'CANCELLED' THEN 1 ELSE 0 END)                        AS cancelled_runs,
       ROUND(AVG((unix_timestamp(r.run_end) - unix_timestamp(r.run_start)) / 60), 1)               AS avg_run_mins,
       ROUND(percentile((unix_timestamp(r.run_end) - unix_timestamp(r.run_start)) / 60, 0.95), 1) AS p95_run_mins,
       ROUND(MAX((unix_timestamp(r.run_end) - unix_timestamp(r.run_start)) / 60), 1)               AS max_run_mins,
       ROUND(SUM(d.dbus), 1)                                                                AS dbus,
       ROUND(AVG(d.dbus), 1)                                                                AS avg_dbus_per_run,
       SUM(CASE WHEN d.dbus IS NULL THEN 1 ELSE 0 END)                                      AS runs_without_billing
FROM runs r
LEFT JOIN run_dbu d USING (job_id, run_id)
LEFT JOIN jobs j    USING (job_id)
GROUP BY r.job_id, j.name, j.timeout_seconds, r.trigger_type
ORDER BY dbus DESC NULLS LAST
```

### vt-job-overlap: concurrent overlap by trigger type, before/after a split date

Each row is one job × period × trigger type. Two concurrency peaks, both counted at the start
of this row's runs (the peak is always reached at some run's start):

- `max_concurrent_same_trigger`: the most runs **of this trigger type** active at once. This is
  the figure to compare with C-J08 for CRON rows, and the one a schedule-overlap claim rests on.
- `max_concurrent_any`: the most runs of the job active at once **counting any trigger** (e.g. a
  CRON run starting while ONETIME backfills are still running). On a per-trigger row it can be
  larger than the same-trigger figure. `max_concurrent_runs` caps all triggers, so this is the
  number the lever actually meets.

Neither is the pack's `max_overlapping_runs_per_run`. **Which concurrency to quote:** when both
exist, quote this template's `max_concurrent_same_trigger` on the CRON row of the period you size
(the post-step `b_after` row when there is a split) — it is verified, scoped to scheduled runs and
to the period the lever addresses. C-J08 `max_concurrent_runs` covers the whole pack window and
every trigger type, so it is usually higher (C-J08 7 vs CRON post-step 6 for the same job is
normal); cite it only as discovery context, never as the sized figure. `median_cron_start_gap_mins` (CRON rows only,
null otherwise) is the median gap between consecutive CRON starts of the job in that period: the
schedule interval for the OPP-JOB-OVERLAP cadence precondition when the cron expression isn't
carried in vt-job-settings-history.

```sql
WITH runs AS (
  SELECT job_id,
         run_id,
         MIN(period_start_time)                AS run_start,
         MAX(period_end_time)                  AS run_end,
         MAX_BY(trigger_type, period_end_time) AS trigger_type
  FROM system.lakeflow.job_run_timeline
  WHERE workspace_id = '{ws}'
    AND period_end_time >= DATE_SUB(DATE'{start}', 3)
    AND job_id IN ({job_ids})
  GROUP BY job_id, run_id
  HAVING MAX(period_end_time) >= DATE'{start}' AND MAX(period_end_time) < DATE_ADD(DATE'{end}', 1)
),
run_dbu AS (
  SELECT usage_metadata.job_run_id AS run_id, SUM(usage_quantity) AS dbus
  FROM system.billing.usage
  WHERE workspace_id = '{ws}'
    AND usage_unit = 'DBU'
    AND usage_date BETWEEN DATE_SUB(DATE'{start}', 3) AND DATE_ADD(DATE'{end}', 1)
    AND usage_metadata.job_id IN ({job_ids})
  GROUP BY 1
),
x AS (  -- runs of the SAME job already active when this run started
  SELECT r.job_id, r.run_id, r.trigger_type, r.run_start, r.run_end,
         COUNT(o.run_id)                                                   AS active_at_start,
         SUM(CASE WHEN o.trigger_type = r.trigger_type THEN 1 ELSE 0 END)  AS same_trigger_active_at_start
  FROM runs r
  LEFT JOIN runs o
    ON o.job_id = r.job_id AND o.run_id <> r.run_id
   AND o.run_start < r.run_start AND o.run_end > r.run_start
  GROUP BY r.job_id, r.run_id, r.trigger_type, r.run_start, r.run_end
),
cron_gap AS (  -- median gap between consecutive CRON starts, per job x period
  SELECT job_id,
         CASE WHEN run_start < DATE'{split_date}' THEN 'a_before' ELSE 'b_after' END AS period,
         'CRON'                                                                    AS trigger_type,
         percentile(gap_mins, 0.5)                                                 AS median_gap_mins
  FROM (
    SELECT job_id, run_start,
           (unix_timestamp(run_start)
            - unix_timestamp(LAG(run_start) OVER (PARTITION BY job_id ORDER BY run_start))) / 60 AS gap_mins
    FROM runs
    WHERE trigger_type = 'CRON'
  ) g
  WHERE gap_mins IS NOT NULL
  GROUP BY 1, 2
),
agg AS (
  SELECT x.job_id,
         CASE WHEN x.run_start < DATE'{split_date}' THEN 'a_before' ELSE 'b_after' END AS period,
         x.trigger_type,
         COUNT(*)                                                AS runs,
         SUM(CASE WHEN x.active_at_start > 0 THEN 1 ELSE 0 END)  AS runs_started_while_running,
         MAX(x.active_at_start) + 1                              AS max_concurrent_any,
         MAX(x.same_trigger_active_at_start) + 1                 AS max_concurrent_same_trigger,
         ROUND(AVG(x.active_at_start), 2)                        AS avg_active_at_start,
         ROUND(AVG(x.same_trigger_active_at_start), 2)           AS avg_same_trigger_active_at_start,
         ROUND(AVG((unix_timestamp(x.run_end) - unix_timestamp(x.run_start)) / 60), 1) AS avg_run_mins,
         ROUND(SUM(d.dbus), 1)                                   AS dbus,
         ROUND(AVG(d.dbus), 1)                                   AS avg_dbus_per_run
  FROM x LEFT JOIN run_dbu d USING (run_id)
  GROUP BY x.job_id, 2, x.trigger_type
)
SELECT a.*,
       ROUND(g.median_gap_mins, 1) AS median_cron_start_gap_mins
FROM agg a
LEFT JOIN cron_gap g
  ON g.job_id = a.job_id AND g.period = a.period AND g.trigger_type = a.trigger_type
ORDER BY a.job_id, a.period, a.trigger_type
```

### vt-job-run-tail: longest runs of one job with per-run DBU

Use this for timeout sizing: sum `excess_dbus` (`run_dbus` − `p95_run_dbus`, floored at 0) over
the CRON tail runs; never use tail minutes × an average rate. `p95_run_dbus` / `p95_run_mins` are
the 95th percentiles over **all** the job's CRON runs in the window (`cron_runs`), not over the 20
rows shown, so they repeat on every row. Both are null when the job had no CRON runs. Sum
`excess_dbus` over **all** rows of the saved json, not a preview. `queue_mins` =
`queue_duration_seconds` summed over the run's periods: a long `run_mins` with a large `queue_mins`
waited rather than ran. No template returns a task-level `timeout_seconds`, so a run longer than the
job timeout in effect is "task timeout, queueing, or not enforced": the owner confirms which.

```sql
WITH runs AS (
  SELECT job_id,
         run_id,
         MIN(period_start_time)                AS run_start,
         MAX(period_end_time)                  AS run_end,
         MAX_BY(result_state, period_end_time)         AS result_state,
         MAX_BY(trigger_type, period_end_time)         AS trigger_type,
         SUM(COALESCE(queue_duration_seconds, 0)) / 60 AS queue_mins
  FROM system.lakeflow.job_run_timeline
  WHERE workspace_id = '{ws}'
    AND period_end_time >= DATE_SUB(DATE'{start}', 3)
    AND job_id = '{job_id}'
  GROUP BY job_id, run_id
  HAVING MAX(period_end_time) >= DATE'{start}' AND MAX(period_end_time) < DATE_ADD(DATE'{end}', 1)
),
run_dbu AS (
  SELECT usage_metadata.job_run_id AS run_id, SUM(usage_quantity) AS dbus
  FROM system.billing.usage
  WHERE workspace_id = '{ws}'
    AND usage_unit = 'DBU'
    AND usage_date BETWEEN DATE_SUB(DATE'{start}', 3) AND DATE_ADD(DATE'{end}', 1)
    AND usage_metadata.job_id = '{job_id}'
  GROUP BY 1
),
cron_p95 AS (  -- over ALL CRON runs of the job in the window, not just the 20 rows shown
  SELECT percentile(d.dbus, 0.95)                                                          AS p95_run_dbus,
         percentile((unix_timestamp(r.run_end) - unix_timestamp(r.run_start)) / 60, 0.95) AS p95_run_mins,
         COUNT(*)                                                                          AS cron_runs
  FROM runs r LEFT JOIN run_dbu d USING (run_id)
  WHERE r.trigger_type = 'CRON'
)
SELECT r.run_id,
       r.trigger_type,
       r.result_state,
       r.run_start,
       ROUND((unix_timestamp(r.run_end) - unix_timestamp(r.run_start)) / 60, 1) AS run_mins,
       ROUND(r.queue_mins, 1)                                                    AS queue_mins,
       ROUND(d.dbus, 1)                                                          AS run_dbus,
       ROUND(p.p95_run_mins, 1)                                                  AS p95_run_mins,
       ROUND(p.p95_run_dbus, 1)                                                  AS p95_run_dbus,
       ROUND(GREATEST(d.dbus - p.p95_run_dbus, 0), 1)                            AS excess_dbus,
       p.cron_runs
FROM runs r LEFT JOIN run_dbu d USING (run_id) CROSS JOIN cron_p95 p
ORDER BY run_mins DESC
LIMIT 20
```

### vt-job-settings-history: effective job settings per change (SCD rows de-duplicated)

`system.lakeflow.jobs` keeps one row per settings write (`change_time`), and a bundle deploy
writes several rows at once, some with `paused` / `trigger_type` momentarily null. This returns
**one row per effective change** of the target jobs: each setting is carried forward from its
latest non-null value (so a null-toggle row is not a change), then consecutive rows with identical
effective settings collapse into one. `change_time` is the first SCD row of that settings state,
`last_change_time` the last, and `scd_rows` how many raw rows were folded in. Read the setting
**in effect at a given run**: the latest `change_time` ≤ the run's `run_start` (vt-job-run-tail).
Use it for the OPP-JOB-TIMEOUT `timeout_seconds` check, the OPP-JOB-OVERLAP schedule interval, and
`deployment_kind` (`BUNDLE` means change the bundle source, not `jobs update`). The `prev_*`
columns show the previous effective value. Carrying forward means a setting cleared to null reads
as unchanged; that is rare (a removed timeout is usually `0`), and the raw rows are one
`SELECT * FROM system.lakeflow.jobs` away if you need them. `performance_target` and
`max_concurrent_runs` are **not columns of this table**: read the performance mode per run from
billing (`product_features.performance_target`, vt-perf-target-mix), and have the owner confirm
`max_concurrent_runs`. `cron_expression` can be null; then take the interval from vt-job-overlap
`median_cron_start_gap_mins`.

```sql
WITH v AS (  -- every SCD row of the target jobs
  SELECT job_id, name, change_time, delete_time, timeout_seconds, trigger_type,
         trigger.schedule.quartz_cron_expression AS cron_expression,
         trigger.schedule.timezone_id            AS cron_timezone,
         trigger.periodic.interval               AS periodic_interval,
         trigger.periodic.units                  AS periodic_units,
         trigger.continuous.enabled              AS continuous_enabled,
         paused,
         deployment.kind                         AS deployment_kind,
         deployment.metadata_file_path           AS deployment_metadata_file_path
  FROM system.lakeflow.jobs
  WHERE workspace_id = '{ws}'
    AND job_id IN ({job_ids})
),
eff AS (  -- effective settings: each field carried forward from its latest non-null value
  SELECT job_id, name, change_time, delete_time,
         LAST(timeout_seconds, true)               OVER c AS timeout_seconds,
         LAST(trigger_type, true)                  OVER c AS trigger_type,
         LAST(cron_expression, true)               OVER c AS cron_expression,
         LAST(cron_timezone, true)                 OVER c AS cron_timezone,
         LAST(periodic_interval, true)             OVER c AS periodic_interval,
         LAST(periodic_units, true)                OVER c AS periodic_units,
         LAST(continuous_enabled, true)            OVER c AS continuous_enabled,
         LAST(paused, true)                        OVER c AS paused,
         LAST(deployment_kind, true)               OVER c AS deployment_kind,
         LAST(deployment_metadata_file_path, true) OVER c AS deployment_metadata_file_path
  FROM v
  WINDOW c AS (PARTITION BY job_id ORDER BY change_time ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
),
keyed AS (
  SELECT *, to_json(named_struct(
           'timeout_seconds', timeout_seconds, 'trigger_type', trigger_type,
           'cron_expression', cron_expression, 'cron_timezone', cron_timezone,
           'periodic_interval', periodic_interval, 'periodic_units', periodic_units,
           'continuous_enabled', continuous_enabled, 'paused', paused,
           'deployment_kind', deployment_kind, 'deleted', delete_time IS NOT NULL)) AS settings_key
  FROM eff
),
flagged AS (  -- 1 where the effective settings differ from the previous row
  SELECT *, CASE WHEN LAG(settings_key) OVER (PARTITION BY job_id ORDER BY change_time) <=> settings_key
                 THEN 0 ELSE 1 END AS is_change
  FROM keyed
),
grouped AS (
  SELECT *, SUM(is_change) OVER (PARTITION BY job_id ORDER BY change_time
                                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS change_seq
  FROM flagged
),
per_change AS (  -- one row per run of identical effective settings
  SELECT job_id, change_seq,
         MAX_BY(name, change_time)                          AS name,
         MIN(change_time)                                   AS change_time,
         MAX(change_time)                                   AS last_change_time,
         COUNT(*)                                           AS scd_rows,
         MAX(delete_time)                                   AS delete_time,
         MAX_BY(timeout_seconds, change_time)               AS timeout_seconds,
         MAX_BY(trigger_type, change_time)                  AS trigger_type,
         MAX_BY(cron_expression, change_time)               AS cron_expression,
         MAX_BY(cron_timezone, change_time)                 AS cron_timezone,
         MAX_BY(periodic_interval, change_time)             AS periodic_interval,
         MAX_BY(periodic_units, change_time)                AS periodic_units,
         MAX_BY(continuous_enabled, change_time)            AS continuous_enabled,
         MAX_BY(paused, change_time)                        AS paused,
         MAX_BY(deployment_kind, change_time)               AS deployment_kind,
         MAX_BY(deployment_metadata_file_path, change_time) AS deployment_metadata_file_path
  FROM grouped
  GROUP BY job_id, change_seq
)
SELECT job_id,
       name,
       change_time,
       last_change_time,
       scd_rows,
       delete_time,
       LAG(timeout_seconds) OVER w AS prev_timeout_seconds,
       timeout_seconds,
       LAG(trigger_type) OVER w    AS prev_trigger_type,
       trigger_type,
       LAG(cron_expression) OVER w AS prev_cron_expression,
       cron_expression,
       cron_timezone,
       periodic_interval,
       periodic_units,
       continuous_enabled,
       LAG(paused) OVER w          AS prev_paused,
       paused,
       deployment_kind,
       deployment_metadata_file_path
FROM per_change
WINDOW w AS (PARTITION BY job_id ORDER BY change_time)
ORDER BY job_id, change_time DESC
LIMIT 200
```

### vt-job-failures: run DBU by terminal state (workspace, uncapped)

```sql
WITH runs AS (
  SELECT job_id, run_id, MAX_BY(result_state, period_end_time) AS result_state
  FROM system.lakeflow.job_run_timeline
  WHERE workspace_id = '{ws}'
    AND period_end_time >= DATE_SUB(DATE'{start}', 3)
  GROUP BY job_id, run_id
  HAVING MAX(period_end_time) >= DATE'{start}' AND MAX(period_end_time) < DATE_ADD(DATE'{end}', 1)
),
run_dbu AS (
  SELECT usage_metadata.job_id AS job_id, usage_metadata.job_run_id AS run_id, SUM(usage_quantity) AS dbus
  FROM system.billing.usage
  WHERE workspace_id = '{ws}'
    AND usage_unit = 'DBU'
    AND usage_date BETWEEN DATE_SUB(DATE'{start}', 3) AND DATE_ADD(DATE'{end}', 1)
    AND usage_metadata.job_run_id IS NOT NULL
  GROUP BY 1, 2
)
SELECT COALESCE(r.result_state, 'UNKNOWN')                       AS result_state,
       COUNT(*)                                                  AS runs,
       COUNT(DISTINCT r.job_id)                                  AS jobs,
       ROUND(SUM(d.dbus), 1)                                     AS dbus,
       ROUND(100 * SUM(d.dbus) / SUM(SUM(d.dbus)) OVER (), 2)    AS pct_of_job_run_dbus
FROM runs r LEFT JOIN run_dbu d USING (job_id, run_id)
GROUP BY 1
ORDER BY dbus DESC NULLS LAST
```

For a per-job breakdown, add `r.job_id` to the SELECT and the GROUP BY.

**Reconciling with `data.facts.job_reliability` (F-06).** Both count **one row per run** by its
final state (the `result_state` of its latest period, so a repaired run counts once) and select
runs whose **last period ended** in `{start}`…`{end}` (full days; a run that finishes today is in
neither). `job_reliability.failed_runs` = this file's `FAILED` + `ERROR` + `TIMED_OUT` rows
(`job_reliability.failed_states` lists them; `TIMEDOUT` is a legacy spelling of `TIMED_OUT`), and
`failed_by_state` gives the per-state split to compare row by row. `job_reliability.window` is
the window F-06 used: run this template with that `--start` / `--end`. The `UNKNOWN` row here is
in-flight runs with no final state, which F-06 excludes. A residual gap of a run or two on the
same window is data that arrived between discovery and verify (the system tables keep
refreshing): say so, quote both figures, and size from this file.

### vt-task-durations: task-level durations of successful CRON runs, before/after a split date

Only tasks of **successful CRON parent runs** count (the parent run's terminal `result_state` is
`SUCCEEDED` and its `trigger_type` is `CRON`), and **skipped / excluded or zero-duration task runs
are dropped**. Mixing triggers, failed parents and zero-length skipped tasks blurs the wait you
are measuring. The `*_before` / `*_after` columns split each task's runs at `--split-date`
(`{split_date}`, by task start); pass `data.facts.step_change.date` to check whether a wait grew
at the step (OPP-JOB-WAIT-TASK / OPP-JOB-OVERLAP / OPP-STEP-CHANGE root-cause link). With no
`--split-date` the split is `--start`, so every run is "after" and the `*_before` columns are 0 /
null. Failure counts of wait tasks come from C-J09 / P-WF01, not from here: this is the healthy-run
duration baseline. Read every row, not only the top few (a `wait_for_*` task ranked 11th counts).

```sql
WITH parents AS (  -- successful CRON parent runs that ended in the window
  SELECT job_id,
         run_id                                 AS job_run_id
  FROM system.lakeflow.job_run_timeline
  WHERE workspace_id = '{ws}'
    AND period_end_time >= DATE_SUB(DATE'{start}', 3)
    AND job_id IN ({job_ids})
  GROUP BY job_id, run_id
  HAVING MAX(period_end_time) >= DATE'{start}' AND MAX(period_end_time) < DATE_ADD(DATE'{end}', 1)
     AND MAX_BY(trigger_type, period_end_time) = 'CRON'
     AND MAX_BY(result_state, period_end_time) = 'SUCCEEDED'
),
tasks AS (  -- level 1: periods -> one row per task run of those parents
  SELECT t.job_id,
         t.task_key,
         t.run_id                                   AS task_run_id,
         MIN(t.period_start_time)                   AS task_start,
         MAX(t.period_end_time)                     AS task_end,
         MAX_BY(t.result_state, t.period_end_time)  AS result_state
  FROM system.lakeflow.job_task_run_timeline t
  JOIN parents p ON p.job_id = t.job_id AND p.job_run_id = t.job_run_id
  WHERE t.workspace_id = '{ws}'
    AND t.period_end_time >= DATE_SUB(DATE'{start}', 3)
    AND t.job_id IN ({job_ids})
  GROUP BY t.job_id, t.task_key, t.run_id
),
d AS (  -- drop skipped / excluded and zero-duration task runs
  SELECT job_id, task_key, result_state,
         (unix_timestamp(task_end) - unix_timestamp(task_start)) / 60 AS mins,
         task_start >= DATE'{split_date}'                              AS after_split
  FROM tasks
  WHERE COALESCE(result_state, '') NOT IN ('SKIPPED', 'EXCLUDED')
    AND task_end > task_start
)
SELECT job_id,                             -- level 2: task runs -> one row per job x task_key
       task_key,
       COUNT(*)                                                                       AS task_runs,
       SUM(CASE WHEN result_state NOT IN ('SUCCEEDED', 'SUCCESS') THEN 1 ELSE 0 END) AS non_success_runs,
       ROUND(percentile(mins, 0.5), 1)                                                AS p50_mins,
       ROUND(percentile(mins, 0.95), 1)                                               AS p95_mins,
       ROUND(SUM(mins) / 60, 1)                                                       AS task_hours,
       SUM(CASE WHEN NOT after_split THEN 1 ELSE 0 END)                               AS task_runs_before,
       ROUND(percentile(CASE WHEN NOT after_split THEN mins END, 0.5), 1)             AS p50_mins_before,
       ROUND(percentile(CASE WHEN NOT after_split THEN mins END, 0.95), 1)            AS p95_mins_before,
       SUM(CASE WHEN after_split THEN 1 ELSE 0 END)                                   AS task_runs_after,
       ROUND(percentile(CASE WHEN after_split THEN mins END, 0.5), 1)                 AS p50_mins_after,
       ROUND(percentile(CASE WHEN after_split THEN mins END, 0.95), 1)                AS p95_mins_after
FROM d
GROUP BY job_id, task_key
ORDER BY task_hours DESC
LIMIT 25
```

## Warehouses

### vt-warehouse-dbu: per-warehouse DBU (`usage_metadata.warehouse_id`)

```sql
SELECT usage_metadata.warehouse_id                               AS warehouse_id,
       product_features.is_serverless                            AS is_serverless,
       sku_name,
       COUNT(DISTINCT usage_date)                                AS days_billed,
       COUNT(DISTINCT date_trunc('HOUR', usage_start_time))      AS billed_hours,
       ROUND(SUM(usage_quantity), 1)                             AS dbus,
       ROUND(SUM(usage_quantity) / COUNT(DISTINCT date_trunc('HOUR', usage_start_time)), 2) AS dbus_per_billed_hour
FROM system.billing.usage
WHERE workspace_id = '{ws}'
  AND usage_unit = 'DBU'
  AND usage_metadata.warehouse_id IS NOT NULL
  AND usage_date BETWEEN DATE'{start}' AND DATE'{end}'
GROUP BY 1, 2, 3
ORDER BY dbus DESC
```

Same full-day window as `data.facts.top_warehouses` (F-11) and the W-W01 / W-W02
`warehouse_dbus` column (full days, today excluded, at the default 30-day lookback). A warehouse can
span several rows (`is_serverless` / `sku_name`): sum them before comparing.

### vt-warehouse-change-rate: DBU per billed hour, 7 days before vs after a config change

Both periods are bounded: 7 days before `{change_time}` and at most 7 days after it (and never
today). `after_hours_sufficient` (same value on both rows) is `true` when the after period has
**≥ 24 billed hours**. When it is `false` the after rate is not yet meaningful: the catalog's
"< 24 h of billing after the change → measure first" disqualifier applies, so say so instead of
quoting the after rate as the run-rate.

```sql
WITH p AS (
  SELECT CASE WHEN usage_start_time < TIMESTAMP'{change_time}' THEN 'a_before' ELSE 'b_after' END AS period,
         COUNT(DISTINCT date_trunc('HOUR', usage_start_time))  AS billed_hours,
         SUM(usage_quantity)                                   AS dbus
  FROM system.billing.usage
  WHERE workspace_id = '{ws}'
    AND usage_unit = 'DBU'
    AND usage_metadata.warehouse_id = '{warehouse_id}'
    AND usage_date >= DATE_SUB(DATE(TIMESTAMP'{change_time}'), 7)
    AND usage_start_time >= TIMESTAMP'{change_time}' - INTERVAL 7 DAYS
    AND usage_start_time <  TIMESTAMP'{change_time}' + INTERVAL 7 DAYS
    AND usage_date < current_date()
  GROUP BY 1
)
SELECT period,
       billed_hours,
       ROUND(dbus, 1)                                                                     AS dbus,
       ROUND(dbus / billed_hours, 2)                                                      AS dbus_per_billed_hour,
       COALESCE(MAX(CASE WHEN period = 'b_after' THEN billed_hours END) OVER (), 0) >= 24 AS after_hours_sufficient
FROM p
ORDER BY period
```

Report the result as a run-rate change, not a recoverable.

### vt-warehouse-queue: daily queueing (`waiting_at_capacity_duration_ms`)

```sql
SELECT date_trunc('DAY', start_time)                                                    AS query_date,
       COUNT(*)                                                                         AS queries,
       ROUND(100 * AVG(CASE WHEN waiting_at_capacity_duration_ms > 0 THEN 1 ELSE 0 END), 1) AS queued_pct,
       ROUND(AVG(waiting_at_capacity_duration_ms) / 1000, 1)                            AS avg_capacity_wait_s,
       ROUND(percentile(waiting_at_capacity_duration_ms, 0.95) / 1000, 1)               AS p95_capacity_wait_s,
       SUM(CASE WHEN waiting_at_capacity_duration_ms > 30000 THEN 1 ELSE 0 END)         AS queries_waiting_over_30s,
       ROUND(AVG(waiting_for_compute_duration_ms) / 1000, 1)                            AS avg_compute_startup_wait_s
FROM system.query.history
WHERE workspace_id = '{ws}'
  AND compute.warehouse_id = '{warehouse_id}'
  AND start_time >= DATE'{qh_start}'
  AND start_time <  DATE_ADD(DATE'{qh_end}', 1)
GROUP BY 1
ORDER BY 1
```

To measure a recent capacity change, set `{qh_end}` to today and read the days on either side
of the change.

### vt-warehouse-drivers: per-warehouse drivers (`query_source`, `client_application`)

```sql
WITH q AS (
  SELECT compute.warehouse_id AS warehouse_id,
         CASE WHEN query_source.dashboard_id                IS NOT NULL THEN 'dashboard'
              WHEN query_source.legacy_dashboard_id         IS NOT NULL THEN 'legacy_dashboard'
              WHEN query_source.genie_space_id              IS NOT NULL THEN 'genie'
              WHEN query_source.job_info.job_id             IS NOT NULL THEN 'job'
              WHEN query_source.pipeline_info.pipeline_id   IS NOT NULL THEN 'pipeline'
              WHEN query_source.alert_id                    IS NOT NULL THEN 'alert'
              WHEN query_source.notebook_id                 IS NOT NULL THEN 'notebook'
              WHEN query_source.sql_query_id                IS NOT NULL THEN 'sql_query'
              ELSE 'other' END                                      AS source_type,
         COALESCE(query_source.dashboard_id, query_source.legacy_dashboard_id, query_source.genie_space_id,
                  query_source.job_info.job_id, query_source.pipeline_info.pipeline_id, query_source.alert_id,
                  query_source.notebook_id, query_source.sql_query_id) AS source_id,
         client_application,
         total_duration_ms, read_bytes, waiting_at_capacity_duration_ms, from_result_cache,
         total_duration_ms - COALESCE(waiting_at_capacity_duration_ms, 0) AS non_capacity_duration_ms
  FROM system.query.history
  WHERE workspace_id = '{ws}'
    AND compute.warehouse_id = '{warehouse_id}'
    AND start_time >= DATE'{qh_start}'
    AND start_time <  DATE_ADD(DATE'{qh_end}', 1)
)
SELECT warehouse_id, source_type, source_id, client_application,
       COUNT(*)                                                                    AS queries,
       ROUND(SUM(read_bytes) / 1e12, 2)                                            AS read_tb,
       ROUND(AVG(read_bytes) / 1e9, 2)                                             AS avg_read_gb_per_query,
       ROUND(SUM(non_capacity_duration_ms) / 3.6e6, 1)                             AS non_capacity_duration_h,
       ROUND(SUM(non_capacity_duration_ms) / 3.6e6, 1)                             AS exec_duration_h,  -- alias of non_capacity_duration_h
       ROUND(100 * SUM(non_capacity_duration_ms) / SUM(SUM(non_capacity_duration_ms)) OVER (), 1) AS pct_of_warehouse_exec,
       ROUND(SUM(total_duration_ms) / 3.6e6, 1)                                    AS duration_h,
       ROUND(100 * SUM(total_duration_ms) / SUM(SUM(total_duration_ms)) OVER (), 1) AS pct_of_warehouse_duration,
       ROUND(AVG(waiting_at_capacity_duration_ms) / 1000, 1)                       AS avg_capacity_wait_s,
       ROUND(100 * AVG(CASE WHEN from_result_cache THEN 1 ELSE 0 END), 1)          AS result_cache_pct
FROM q
GROUP BY warehouse_id, source_type, source_id, client_application
ORDER BY non_capacity_duration_h DESC
LIMIT 25
```

**Rank drivers by `non_capacity_duration_h` (or `read_tb`), not `duration_h`.**
`total_duration_ms` includes the time a query waited for capacity, so on a queueing warehouse the
source that waits most can top `duration_h` / `pct_of_warehouse_duration` while reading almost
nothing: it is a victim of the queue, not its driver. `non_capacity_duration_h` is total duration
minus capacity wait (`exec_duration_h` is the same column under its older name);
`pct_of_warehouse_exec` is its share. It is a **proxy** for execution time, not pure execution: it
still includes compilation, result fetch and compute-startup wait (`waiting_for_compute_duration_ms`).
Call it "non-capacity duration" in customer prose, and confirm a driver from its query profile
before you call the time "execution". Per-query reads are `avg_read_gb_per_query`.

**W-W06 and this template read different windows.** W-W06 reads `start_time >=` the discovery day
minus 7 days with **no upper bound**: 7 full days **plus the partial discovery day** (`window_days`
= 7 on its rows). This template reads `{qh_start}`…`{qh_end}`: the 7 **full** days ending
`--end`, today excluded. Their sources and GB/query therefore differ (one run saw 229.7 vs 280.8
GB/query for the same client, and a different top source). Use this template's figures for the
item; to **reconcile** with W-W06 (the rubric's Reconciled point), re-run it on W-W06's window,
`--set qh_start=<discovery date − 7> --set qh_end=<discovery date> --suffix <target>-ww06`, and
compare like with like. A gap that remains on the same window is unreconciled (no point) unless
you explain it; a gap you only attribute to the window, without that re-run, is an assumption.

### vt-heavy-statements: top statements by bytes read

```sql
SELECT statement_id,
       compute.warehouse_id                                                AS warehouse_id,
       statement_type,
       client_application,
       COALESCE(query_source.dashboard_id, query_source.genie_space_id, query_source.job_info.job_id) AS source_id,
       start_time,
       ROUND(total_duration_ms / 60000, 1)                                 AS total_mins,
       ROUND(read_bytes / 1e12, 3)                                         AS read_tb,
       read_files,
       pruned_files,
       ROUND(100 * pruned_files / NULLIF(pruned_files + read_files, 0), 1) AS pruned_files_pct,
       ROUND(spilled_local_bytes / 1e9, 1)                                 AS spill_gb
FROM system.query.history
WHERE workspace_id = '{ws}'
  AND compute.warehouse_id IS NOT NULL
  AND start_time >= DATE'{qh_start}'
  AND start_time <  DATE_ADD(DATE'{qh_end}', 1)
ORDER BY read_bytes DESC
LIMIT 20
```

Add `AND compute.warehouse_id = '{warehouse_id}'` to scope it to one warehouse.

### vt-warehouse-config-history: size / cluster / auto-stop changes

The name column is `warehouse_name`; this table has no `name` column (unlike
`system.lakeflow.jobs`). Don't add `name` from `data.facts` to the SELECT.

```sql
SELECT warehouse_id,
       warehouse_name,
       change_time,
       warehouse_type,
       LAG(warehouse_size)    OVER w AS prev_size,              warehouse_size,
       LAG(min_clusters)      OVER w AS prev_min_clusters,      min_clusters,
       LAG(max_clusters)      OVER w AS prev_max_clusters,      max_clusters,
       LAG(auto_stop_minutes) OVER w AS prev_auto_stop_minutes, auto_stop_minutes,
       delete_time
FROM system.compute.warehouses
WHERE workspace_id = '{ws}'
WINDOW w AS (PARTITION BY warehouse_id ORDER BY change_time)
QUALIFY change_time >= DATE_SUB(current_date(), {lookback_days})
ORDER BY change_time DESC
```

## Clusters

### vt-cluster-driver-attribution: classic cluster → job attribution with window DBU (uncapped)

Attributes **every classic cluster billed in the window** to its job, so a cluster from a CRS-01
driver-sample row (or any capped CRS / C-C row) can be tied to a job and a DBU figure without
relying on a capped extract. Billing carries `usage_metadata.cluster_id` and
`usage_metadata.job_id` on classic compute; the cluster's config (`cluster_source`, node types,
`worker_count`, `max_autoscale_workers`) comes from the latest `system.compute.clusters` row and
the name from `system.lakeflow.jobs`. Serverless compute has no `cluster_id` and is not here.

One row per **job** (`attributed_to = 'job'`: job clusters are created per run, so `clusters`
counts the per-run clusters and `top_cluster_id` / `top_cluster_name` is the costliest one) or per
**non-job cluster** (`attributed_to = 'cluster'`, `cluster_id` set: all-purpose clusters with no job
on the billing row). The aggregation reads every billing row before grouping, so the result is
not capped: `classic_dbus_total` (the same on every row) is the workspace's classic cluster DBU for
the window, and `pct_of_classic_dbus` each row's share. Compare `classic_dbus_total` with
`data.facts.total.dbus` for the OPP-CLUSTER-RIGHTSIZE materiality test (< 1% → Not now, with the
number in `sizing.value`).

**Matching a driver sample.** CRS-01 rows carry `job_id`, `job_name`, `attributed_job_count` and
`cluster_dbus` (joined on `node_timeline.cluster_id = usage_metadata.cluster_id`, the same join as
here), and CRS-01 lists the highest-DBU billed classic clusters first. Match the row's `job_id` to
this file's `job_id` (`attributed_job_count` > 1 = a shared all-purpose cluster, and `job_id` is
its highest-DBU job; null = not job-attributed, so match on `cluster_id`). For an older envelope
without `job_id`, a job cluster's name is `job-<job_id>-run-<run_id>-…`. CRS-01 `cluster_dbus`
covers its lookback up to the discovery time (partial today included) and `job_name` comes from
billing (may be null), so small differences from this file's full-day `cluster_dbus` and
`lakeflow` job name are expected: use this file's figures for sizing. A CRS cluster that matches
no row was not billed in the window (or is serverless), which is not the same as "the source lacks
the data". `max_worker_count` = 0 with no
`max_autoscale_workers` is a **single-node (driver-only)** cluster: it has no worker nodes, which
is why CRS-06–08 return `NO_WORKER_SAMPLES` for it, and the driver sample is the whole cluster's
utilisation. Then run vt-job-runs on the matched job for per-run DBU.

```sql
WITH cluster_dbu AS (  -- every classic cluster billed in the window, per cluster x job (no row cap)
  SELECT usage_metadata.cluster_id                 AS cluster_id,
         usage_metadata.job_id                     AS job_id,
         COUNT(DISTINCT usage_metadata.job_run_id) AS job_runs,
         SUM(usage_quantity)                       AS dbus
  FROM system.billing.usage
  WHERE workspace_id = '{ws}'
    AND usage_unit = 'DBU'
    AND usage_metadata.cluster_id IS NOT NULL
    AND usage_date BETWEEN DATE'{start}' AND DATE'{end}'
  GROUP BY 1, 2
),
clusters AS (  -- latest config row per cluster
  SELECT cluster_id, cluster_name, cluster_source, driver_node_type, worker_node_type,
         worker_count, max_autoscale_workers
  FROM system.compute.clusters
  WHERE workspace_id = '{ws}'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY cluster_id ORDER BY change_time DESC) = 1
),
jobs AS (  -- latest name per job
  SELECT job_id, name AS job_name
  FROM system.lakeflow.jobs
  WHERE workspace_id = '{ws}'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY job_id ORDER BY change_time DESC) = 1
)
SELECT CASE WHEN d.job_id IS NOT NULL THEN 'job' ELSE 'cluster' END             AS attributed_to,
       d.job_id,
       MAX(j.job_name)                                                          AS job_name,
       CASE WHEN d.job_id IS NULL THEN MAX(d.cluster_id) END                    AS cluster_id,
       MAX_BY(d.cluster_id, d.dbus)                                             AS top_cluster_id,
       MAX_BY(c.cluster_name, d.dbus)                                           AS top_cluster_name,
       ARRAY_JOIN(ARRAY_SORT(COLLECT_SET(c.cluster_source)), ',')               AS cluster_sources,
       ARRAY_JOIN(ARRAY_SORT(COLLECT_SET(c.driver_node_type)), ',')             AS driver_node_types,
       ARRAY_JOIN(ARRAY_SORT(COLLECT_SET(c.worker_node_type)), ',')             AS worker_node_types,
       MAX(c.worker_count)                                                      AS max_worker_count,
       MAX(c.max_autoscale_workers)                                             AS max_autoscale_workers,
       COUNT(DISTINCT d.cluster_id)                                             AS clusters,
       SUM(d.job_runs)                                                          AS job_runs,
       ROUND(SUM(d.dbus), 2)                                                    AS cluster_dbus,
       ROUND(SUM(SUM(d.dbus)) OVER (), 2)                                       AS classic_dbus_total,
       ROUND(100 * SUM(d.dbus) / SUM(SUM(d.dbus)) OVER (), 2)                   AS pct_of_classic_dbus
FROM cluster_dbu d
LEFT JOIN clusters c USING (cluster_id)
LEFT JOIN jobs j     USING (job_id)
GROUP BY d.job_id, CASE WHEN d.job_id IS NULL THEN d.cluster_id END
ORDER BY cluster_dbus DESC
```

## Pipelines

### vt-pipeline-updates: update cadence, full refreshes, DBU per update

Returns **every** pipeline in the window (no pipeline filter); pick the target's row. `verify run` warns that `--pipeline-ids` is ignored here.

`trigger_type_mix` is the distribution of update trigger types (`TYPE:count`, e.g.
`CRON:700, RETRY_ON_FAILURE:32`), with `dominant_trigger_type` / `dominant_trigger_pct`. Never
report a single `MAX(trigger_type)`: that is the lexicographically largest type, not the dominant
one.

**Per-update billing caveat:** `pipeline_dbus` is the pipeline's billing over the calendar window,
not billing matched to the selected updates (updates are selected by end time; billing between
updates, e.g. continuous or idle clusters, is included). `dbus_per_update` is a context ratio, not
the marginal cost of one update. Don't present it as a per-update saving without an owner-stated
target cadence and a post-change DBU/day measurement.

```sql
WITH updates AS (  -- level 1: periods -> one row per update
  SELECT pipeline_id,
         update_id,
         MAX_BY(update_type, period_end_time)                  AS update_type,
         MAX_BY(trigger_type, period_end_time)                 AS trigger_type,
         MAX_BY(result_state, period_end_time)                 AS result_state,
         SIZE(MAX_BY(full_refresh_selection, period_end_time)) AS full_refresh_tables,
         MIN(period_start_time)                                AS update_start,
         MAX(period_end_time)                                  AS update_end
  FROM system.lakeflow.pipeline_update_timeline
  WHERE workspace_id = '{ws}'
    AND period_end_time >= DATE_SUB(DATE'{start}', 3)
  GROUP BY pipeline_id, update_id
  HAVING MAX(period_end_time) >= DATE'{start}' AND MAX(period_end_time) < DATE_ADD(DATE'{end}', 1)
),
pipeline_dbu AS (
  SELECT usage_metadata.dlt_pipeline_id AS pipeline_id, SUM(usage_quantity) AS dbus
  FROM system.billing.usage
  WHERE workspace_id = '{ws}'
    AND usage_unit = 'DBU'
    AND usage_metadata.dlt_pipeline_id IS NOT NULL
    AND usage_date BETWEEN DATE'{start}' AND DATE'{end}'
  GROUP BY 1
),
trigger_mix AS (  -- trigger_type distribution per pipeline (not MAX)
  SELECT pipeline_id,
         ARRAY_JOIN(ARRAY_SORT(COLLECT_LIST(CONCAT(trigger_type, ':', CAST(n AS STRING)))), ', ') AS trigger_type_mix,
         MAX_BY(trigger_type, n)                                       AS dominant_trigger_type,
         ROUND(100 * MAX(n) / SUM(n), 1)                               AS dominant_trigger_pct
  FROM (SELECT pipeline_id, COALESCE(trigger_type, 'UNKNOWN') AS trigger_type, COUNT(*) AS n
        FROM updates GROUP BY 1, 2)
  GROUP BY pipeline_id
)
SELECT u.pipeline_id,                     -- level 2: updates -> one row per pipeline
       COUNT(*)                                                                     AS updates,
       ROUND(COUNT(*) / {window_days}, 1)                                           AS updates_per_day,
       SUM(CASE WHEN u.update_type = 'FULL_REFRESH' OR u.full_refresh_tables > 0 THEN 1 ELSE 0 END) AS full_refresh_updates,
       SUM(CASE WHEN u.result_state <> 'COMPLETED' THEN 1 ELSE 0 END)              AS non_completed_updates,
       ROUND(AVG((unix_timestamp(u.update_end) - unix_timestamp(u.update_start)) / 60), 1) AS avg_update_mins,
       MAX(t.trigger_type_mix)                                                      AS trigger_type_mix,
       MAX(t.dominant_trigger_type)                                                 AS dominant_trigger_type,
       MAX(t.dominant_trigger_pct)                                                  AS dominant_trigger_pct,
       ROUND(MAX(d.dbus), 1)                                                        AS pipeline_dbus,
       ROUND(MAX(d.dbus) / COUNT(*), 1)                                             AS dbus_per_update  -- context ratio, see caveat
FROM updates u
LEFT JOIN pipeline_dbu d USING (pipeline_id)
LEFT JOIN trigger_mix t  USING (pipeline_id)
GROUP BY u.pipeline_id
ORDER BY pipeline_dbus DESC NULLS LAST
LIMIT 15
```
