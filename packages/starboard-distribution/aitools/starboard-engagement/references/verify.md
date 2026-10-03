# Primitive: verify

The `verify` beat re-checks every candidate opportunity against live data before anything is
presented to the user. Nothing reaches the `present` beat unverified.

## What "verified" means

A number is **verified** when:

- The headline DBU figure is reconciled live against `system.billing.usage` — not a 50-row-capped
  pack floor, not a cached estimate. The billing table is the authoritative source.
- The finding is attributed to a `workspace_id`, and — where the product allows — to a specific
  endpoint, instance, job, or query.
- A **confidence score** (1–10) is assigned with the [confidence rubric](#confidence-rubric) below.
- The item has a catalog id and is sized with **that id's formula only**
  ([opportunity-catalog.md](../../starboard-action-plan/references/opportunity-catalog.md)). A
  bounded recoverable DBU is stated with its arithmetic:

  ```
  recoverable = bounded_count × per_unit_DBU
  ```

  Never `rate × window`. A daily rate projected across 30 days is not a bound; it is a
  speculation. Never sum capped pack rows (for example, a 50-row C-J04) as a total. State only
  what the audited population supports.
- For a **performance/reliability** item, record the **performance impact** (latency, queueing,
  failure rate, concurrency) with its verify file, any **DBU it adds at peak**, and the
  **post-change measurement** that will show the effect. If the effect can't be measured or
  bounded from the data, the sizing is **"pilot: measure <metric>"** (Investigate). Don't force a
  DBU number.
- At least one saved verify output reproduces the signal (see [The verify library](#the-verify-library)).

## The re-check surface

Verification runs read-only SQL via the host CLI:

```
query sql --warehouse-id <wh-id> --sql "SELECT ..."
```

This is the **proof** surface — verifying that the signal is real. It is not the fix surface
([native-remediation.md](native-remediation.md) covers the operator-applies remediation). An explicit `--warehouse-id`
is required; never auto-select a profile's default warehouse without confirming it first.

On the **public live-connect path**, only `system.*` tables (billing, query history, lakeflow,
compute, information_schema) are queried here, with no internal tables. If an internal overlay
skill is installed and active, it defines a different verify surface for the
no-connect path (the mirror's governed warehouse) and its own copy of the templates; follow that skill's instructions
instead of this section for that path.

## The verify library

Verification is a set of saved, re-runnable queries. It is not a re-read of the discovery envelope.

- **Start from a template, run by the helper.** Pick the matching template from
  [verify-sql.md](verify-sql.md) and run it with `starboard-helper verify run` (below), which
  fills the placeholders and writes the `.sql`/`.json` pair: product totals, daily totals and step change, the per-job
  two-level timeline, overlap by trigger type, failures by terminal state, per-warehouse DBU and
  change rate, queueing, drivers, heavy statements, `performance_target` mix, warehouse config
  history, pipeline updates, classic cluster → job attribution. Each catalog entry names the
  templates it needs. Hand-written SQL is
  allowed only when no template fits, and it must follow the same rules (full days, `COUNT(DISTINCT
  usage_date)` denominators, two-level timeline aggregation).
- **Save every verify query.** Write the SQL to `<run-dir>/analysis/verify/<file>.sql` and its
  result to `<run-dir>/analysis/verify/<file>.json` (the helper's JSON output). Name the file after
  the template and the target, for example `vt-job-overlap-348089368173138`.
- **Minimum count.** At least **min(8, number of Act-now + Investigate items)** `.sql`/`.json`
  pairs. This is a **floor, not a budget**: verify every Act-now/Investigate candidate, however
  many there are.
- **Cite them.** Every Act-now and Investigate backlog item lists at least one
  `analysis/verify/<file>.json` in its `evidence`. An item with no verify file can't be in those
  tiers: it stays a candidate until verified. Cut it `no_evidence` only when the source lacks the
  evidence (its verify was attempted and failed with no fallback, or the column isn't carried):
  `run check` fails a `no_evidence` cut when none of that id's catalog `Verify` templates was
  attempted (a saved `ok: false` `.json` counts as an attempt).
- **Re-reading the envelope is not verification.** Quoting `discovery.json` rows, or `data.facts`,
  proves nothing new. A verify query must re-derive the signal from the source tables, at
  finer grain or a different cut (per run, per day, per trigger type, before/after).

```bash
starboard-helper verify list --templates <engagement-skill-dir>/references/verify-sql.md
starboard-helper verify run <vt-id> --templates <engagement-skill-dir>/references/verify-sql.md \
  --ws <workspace-id> --start <facts.window.start> --end <facts.window.end> \
  [--job-ids …] [--warehouse-ids …] [--pipeline-ids …] [--split-date …] [--suffix <target>] \
  --out <run-dir>/analysis/verify/
```

`verify run` derives `{qh_start}`/`{qh_end}` (the 7 days ending `--end`), `{window_days}`,
`{lookback_days}` and `{change_time}` (`--split-date` at midnight), so query-history and
config-history templates need no `--set` unless you want an exact value. `--start` / `--end` are
needed only when the template uses a date-derived placeholder (`{start}`, `{end}`, `{qh_*}`,
`{window_days}`, `{lookback_days}`); a template that reads only `{ws}` and ids (for example
vt-job-settings-history) runs without them. `verify list` reports the same `required`
placeholders the runner enforces, so read it when unsure. Passing the window on every call is
still fine. Id lists take commas (`--job-ids 1,2`), spaces (`--job-ids 1 2`) or a repeated flag.
Run **at most 3 verifies at once** on a shared warehouse; a sequential single stream is fine. A
failed verify still writes its `.json` with `ok: false` and the error, prints the error on stderr
and exits non-zero. That includes an argument error found **after** the template id is known (a
missing flag the template needs, an unfilled placeholder): it writes `<vt-id>[-<suffix>].json`
with `ok: false`, so the attempt is on record. Only an error before the template is known (an
unknown template id, an unparseable command line) writes nothing. Check the `ok` field of each
saved `.json` rather than trusting a pipeline's exit code (`| tail` reports `tail`'s; use
`set -o pipefail`).

**Numbers are numbers.** `verify run` and `query sql` return numeric columns (DECIMAL / BIGINT /
DOUBLE, typed from the result manifest) as JSON numbers, so `jq add` and backlog `sizing.value`
work without conversion. Strings, dates and timestamps stay strings. If a saved file from an older
helper has numeric strings, convert with `tonumber` before you sum.

On the no-connect path the overlay passes its own template file (`--templates
<overlay>/mirror-verify.md`) plus `--internal-workspace-id <id>`; `--ws` defaults to that id, so
you don't need to repeat it (pass it only to override). Hand-written SQL runs through
`starboard-helper query sql --warehouse-id <wh-id> --rows objects --sql "$(cat <file>.sql)" >
<run-dir>/analysis/verify/<file>.json`.

**Staged fallback when a verify query times out.** Keep the failed `.json` (`ok: false`; it is
the record that the 7-day cut was attempted), re-run on **one full day** (`--start` = `--end` = the last
full day of the window, `--suffix <target>-1d`), and cite both files. The one-day result earns no
**Stable** point and the item is capped at **Investigate**. If the one-day cut also times out,
the item stays a candidate (not verified).

## The three backlog tiers

Every verified candidate lands in exactly one tier. Nothing is silently dropped.

**Tier rule.** This is the single rule. It reads the same in `starboard-action-plan` and the
opportunity catalog.

- **Act now** = verified AND (bounded recoverable DBU OR measured performance impact with a
  post-change measurement step) AND low-risk lever.
- **Investigate** = verified signal, sizing is a pilot/measurement or depends on customer context.
- **Not now** = low value or blocked.
- Never size by rate × window or by summing capped rows. Lakebase defaults to Investigate.

Terms: *verified* = at least one saved verify output reproduces the signal; *low-risk lever* = one
named setting the owner applies and can revert, with no data loss; *low value* = bounded DBU under
0.5% of `data.facts.total.dbus` with no material performance or reliability impact. Check the
catalog entry's disqualifiers before you choose a tier.

**Precedence (first match wins):** (1) not verified → candidate or Not now "blocked";
(2) an entry disqualifier that says Not now → Not now; (3) an entry disqualifier that blocks the
lever (for example a capacity change in the last 7 days) → Investigate at most, "measure the
change"; (4) low value → Not now; (5) a default cap ("Investigate, always", Lakebase) →
Investigate at most; (6) the tier rule. The catalog's
[tier rule](../../starboard-action-plan/references/opportunity-catalog.md#tier-rule) has a worked
Act-now example (warehouse queueing with no capacity change in 7 days and a `max_num_clusters` +1
lever) and shows how one recent config change moves it to Investigate.

### Confidence rubric

Score every carried item the same way so two runs on the same evidence land on the same number.
Add the points; the score is the sum (minimum 1).

| Points | Criterion | Earns it when |
|---:|---|---|
| 3 | **Verified live** | A saved `analysis/verify/<file>.json` re-derives the signal from the source tables (required for Act now / Investigate) |
| 2 | **Reconciled** | The verify figure agrees with `data.facts` or the pack row within 5%, or the difference is explained (window, cap, rounding) in the evidence pack |
| 2 | **Attributed** | Tied to a named target (job, warehouse, endpoint, pipeline), not only to the workspace |
| 1 | **Lever confirmed** | The current setting is read from config or a system table (for example W-W07 `max_clusters`), not inferred. Settings the source doesn't carry (`max_concurrent_runs`) don't earn it |
| 1 | **Stable** | The signal holds on more than one cut: most days of the window, or both sides of a before/after split, not a single-day spike. A one-day timeout-fallback cut never earns it |
| 1 | **No open caveat** | No capped population, coverage gap, or owner question (intent, SLA, freshness) left on the item |

Worked example: a CRON overlap verified with vt-job-overlap (3), reconciled to C-J08 (2), on a
named job (2), with `max_concurrent_runs` not carried (0), present on both sides of the step-change
split (1), and the owner still has to confirm the fan-out is unintended (0) = **8/10**. Show the
breakdown next to the score in the evidence pack, e.g. `8/10 (V3 R2 A2 L0 S1 C0)`.

**Record the breakdown in the backlog, then sum it.** First drafts that score confidence by
judgment drift from the rubric, so write the points per component into the item's
`confidence_breakdown` and set `confidence` to their sum (minimum 1). The keys are the rubric rows
(`verified`, `reconciled`, `attributed`, `lever_confirmed`, `stable`, `no_open_caveat`; the
letters `V R A L S C` are accepted too), each an integer from 0 to that row's points. The worked
example above is:

```json
"confidence": 8,
"confidence_breakdown": {"verified": 3, "reconciled": 2, "attributed": 2,
                         "lever_confirmed": 0, "stable": 1, "no_open_caveat": 0}
```

A second example: an OPP-WH-SCAN source verified with vt-warehouse-drivers (3) whose GB/query is
21% off W-W06 even after re-running the template on W-W06's window, with no explanation (0; a
gap that the window alone explains, written in the evidence pack, would earn the 2, see the W-W06
note in [verify-sql.md](verify-sql.md#vt-warehouse-drivers-per-warehouse-drivers-query_source-client_application)),
on a named warehouse and source (2), lever not a setting (0), on a one-day timeout-fallback cut
(0), with an open owner question (0) = **5/10**, `{"verified": 3, "reconciled": 0, "attributed": 2,
"lever_confirmed": 0, "stable": 0, "no_open_caveat": 0}`. `run check` warns when an Act-now or
Investigate item has no `confidence_breakdown` and fails when its components don't sum to
`confidence` (or a component exceeds its row's points). The technical review re-scores each
breakdown against the verify files.

| Tier | What ships |
|---|---|
| **Act now** | Native-remediation preview + notebook (with the post-change measurement cell) |
| **Investigate** | The confirming step or pilot as a notebook |
| **Not now** | Reason note (too small, already remediated, blocked externally). No silent drop |

These tier names are canonical across all primitives and templates. Use them verbatim.

### Anti-examples (real plans from the 2026-10-01 six-model run)

Each of these is wrong. Don't repeat them.

- **"Up to ~357K DBU/30d recoverable"** from a +11,964 DBU/day step change. That is rate × window.
  The step is the size of the problem (`OPP-STEP-CHANGE`, Investigate, sizing `none`).
- **"+360K/month above August."** rate × window used as a forecast. Quote `data.facts.months`.
- **"20% idle reduction = 7,075 DBU"** on warehouses that were idle ≤ 0.3% of running hours. The
  idle share was invented. With no idle there is nothing to remove, so it is Not now.
- **Failure waste as Act-now #1** ("up to 5,083 DBU recoverable") when failed-run DBU was under
  0.7% of spend. It is below materiality, failed work is re-run, and C-J04 is capped at 50 rows
  and excludes cancelled runs. Not now.
- **"Raise max clusters"** on a warehouse whose `max_clusters` changed 1→3 the day before
  (`data.facts.recent_config_changes`). Recommend measuring that change, and fix the driver.
- **"Timeouts save 14,064 DBU"**, computed as tail minutes × the job's average DBU/minute with no
  per-run DBU. The long runs were backfills, and killed work is re-run. Size from per-run DBU
  (`vt-job-run-tail`) or report the performance metric.
- **Lakebase in Not now** with no audit step. Lakebase defaults to Investigate.

**Notebook template.** Every opportunity in the Act-now and Investigate tiers ships its next step as
a notebook generated from [`../templates/notebook.py`](../templates/notebook.py). The template
structures the evidence-reproducing query, the target enumeration, and the operator-gated remediation
commands into four cells so the operator can confirm the numbers and act independently. Pick the
variant that matches `sizing.kind`: `bounded_dbu` reproduces the DBU figure; `perf_metric`, `pilot`,
and `none` reproduce the metric by day with no DBU figure assumed, and add the post-change
measurement cell split at the change date. Generate them with the helper rather than by hand (it
keeps the `# MAGIC %md` cells intact):
`starboard-helper notebook render --backlog <run-dir>/analysis/backlog.json --all --run-dir <run-dir> --out <run-dir>/deliverables/notebooks/`
(or `--item <OPP-ID>[:<target>]` for one item). Its JSON result returns `rendered` (the count) and
`paths`. The remediation cell gets the item's `lever_command` verbatim, or a default
command only when the `lever` states exactly one unambiguous `setting = value` for the id's
canonical field; anything else (several settings, a health-alert proposal on a timeout item, a
root-cause fix) renders as an operator decision note. The technical review reads each
remediation cell against the `lever`.

## Attribution push

Push attribution as deep as the data allows. Two worked examples:

**Vector Search abandoned endpoints** — billing rows carry `sku_name` but not `endpoint_name`.
Cross-join against the VS endpoint inventory (available via the REST API or MCP tool) to resolve
`endpoint_id → endpoint_name`. If the join leaves gaps, say so; don't concede the attribution.

**Lakebase per-instance** — attribution from `system.billing.usage` to a specific Lakebase
instance is **not possible with currently available data** (verified in workspace
`1444828305810485` using warehouse `6674ed0664e1e8a3`):

- `usage_metadata.database_instance_id` is NULL on all LAKEBASE billing rows.
- Billing carries `usage_metadata.endpoint_id` in `ep-*` format (e.g. `ep-aged-lab-d19keak2`).
- The instance inventory API (`starboard-helper database instances`) returns `name`, `uid`,
  `capacity`, `state` — **none of which carry an `ep-*` value**. The billing `ep-*` key has no
  join path to any instance field exposed by the API.
- No `system.lakebase` schema exists; no other system table was found that bridges `ep-*` to an
  instance name or uid.

**Consequence:** Lakebase spend can be totalled by workspace but **cannot be attributed
per-instance**. Any Lakebase cost finding must land in the **Investigate** tier with the explicit
reason: "LAKEBASE billing `endpoint_id` (`ep-*`) has no join path to the instance API
(`name`/`uid`); per-instance attribution unavailable."

Do **not** prescribe a `database instances` join as if it closes attribution — it does not. Use
`starboard-helper database instances` only to enumerate the instance inventory (names, capacity
states) for context, not for cost attribution.

## The verification bound

Verify at least the **top ~8 candidates** — selected by composite priority across cost and
performance — before any tier assignment, and every candidate you carry as Act now or
Investigate. Eight is a floor, not a budget: a fired id is never cut `no_evidence` because it fell
past the eighth slot. Don't auto-expand to every pack row without asking.

**Candidate selection uses impact ÷ effort across both domains:**

- **Impact** has two co-equal inputs: recoverable cost (bounded DBU) and performance/reliability
  improvement (latency, failure rates, SLA/stability). A high-impact performance or reliability
  finding is first-class and must not be down-ranked solely because it lacks a large DBU line.
- **Effort/complexity** — including how confident and actionable the fix is — is the denominator.
  Lead with high-impact, low-effort wins. Big-but-hard items, or items with poor attribution
  (e.g. Lakebase with no instance-level billing), rank lower.
- Select the ~8 candidates from the **union** of cost findings and performance/reliability
  findings, ranked by this composite — never raw DBU alone.

The ~8-candidate floor keeps the first verification pass short (one warehouse round-trip per candidate)
while covering the candidates that matter most across both dimensions.
