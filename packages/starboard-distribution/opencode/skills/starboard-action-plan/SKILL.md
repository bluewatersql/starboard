---
name: starboard-action-plan
description: 'The findings→plan vertical of the Starboard engagement workflow: turn workload-review or discovery findings into a verified, customer-ready action plan — scope the workspace, rank candidates by impact÷effort across cost and performance, verify the top ~8 live, and present a verified shortlist before building anything. You (the host) are the analyst — you reason, prioritize, and write; no second LLM, no fixed ranking formula. Use when the user wants an action plan, to prioritize/triage findings, or a ''what should I fix first'' from a review or discovery.'
compatibility: opencode
metadata:
  source: packages/starboard-skills/skills/starboard/starboard-action-plan/SKILL.md
---

# Starboard: Action Plan (engagement vertical)

This is a **thin vertical** of the Starboard engagement workflow. **Load
[`starboard-engagement`](../starboard-engagement/SKILL.md) first** — it supplies the phase beats
(gather → scope: workspace (CONFIRM) → verify → present: verified shortlist (CONFIRM) → synthesize
→ technical-review → humanize → deliver (CONFIRM) → recur), the composable primitives
(evidence-cite, verify, native-remediation, technical-review, humanize, scope-sanitize,
capability-bind), and the doc/deck templates. This skill adds only the **vertical-specific** parts:
where the findings come from, how to prioritize them, and the synthesis shape.

**You are the analyst — you also prioritize.** You (the host) read the findings and write, rank, and
prioritize the plan yourself. There is no ranking script, because a hard-coded ranker can't keep up
with how goals and evidence change. **Sizing and naming are fixed, though.** Every item takes an id,
a sizing formula, a lever, and disqualifiers from
[`references/opportunity-catalog.md`](references/opportunity-catalog.md). There is no second LLM:
don't call the `starboard` goal agent or an MCP `*_analysis` / `synthesize_*` tool.

## Vertical specifics

### Gather — the findings sources
Findings come from an upstream analysis (via the host's **MCP** tools where present, else the
**`starboard-helper`** CLI); you don't re-run the workspace here. Pull **both** the cost picture
(`system.billing.usage` by product — jobs, SQL, serverless, Lakebase, Vector Search, etc.) **and**
the performance/reliability findings across the review domains:

- **Workload review** → `starboard-workload-review` (`data.findings` = `{finding, evidence}` with
  severity, impact, effort, and a `query_id` per evidence row).
- **Discovery** → `starboard-discovery` (findings carry `finding_id`, `priority`, `impact`, and the
  query-pack rows behind them).

### Map: every signal to a catalog id
Quote headline numbers from `data.facts` verbatim; never recompute them. Map every envelope signal
to an id in the [catalog](references/opportunity-catalog.md) (its signal map lists every query and
the standing cuts), or cut it in the plan with a written reason. OPP-OTHER needs a written
justification. A signal you noticed in a
domain note but didn't carry still needs a tier or a cut reason.

### Prioritize: the ordering rule
Rank candidates by **impact ÷ effort** across both cost and performance domains. **Impact has two
co-equal inputs**: recoverable cost (bounded DBU) and performance/reliability improvement (latency,
failure rates, SLA/stability). A high-impact performance or reliability fix is first-class and must
not be down-ranked solely because it lacks a large DBU line. Effort/complexity, including how
confident and actionable the fix is, is the denominator: lead with high-impact, low-effort wins.
Big-but-hard or big-but-unattributable items (e.g. Lakebase with no instance attribution) rank lower.

Hand at least the top **~8 candidates** (from the union of cost and performance findings, ranked
by this composite), and every candidate you will carry as Act now or Investigate, to the engagement
`verify` beat. Eight is a floor, not a budget. That beat runs the catalog's verify templates, saves
each one as `analysis/verify/<file>.sql` + `.json`, pushes attribution, and scores confidence 1–10.
After verification, the `present` beat surfaces the verified backlog
tiered Act now / Investigate / Not now and confirms which opportunities to carry and which artifacts
to generate. **Do not present an unverified shortlist**: the verify beat must run before selection.
State the ordering rationale at the top of the plan and give each carried action a one-line "why it
ranks here".

### Tier: the single rule
Ordering decides position *within* a tier. The tier itself comes from this rule, which reads the
same in [`verify.md`](../starboard-engagement/references/verify.md) and the catalog:

- **Act now** = verified AND (bounded recoverable DBU OR measured performance impact with a
  post-change measurement step) AND low-risk lever.
- **Investigate** = verified signal, sizing is a pilot/measurement or depends on customer context.
- **Not now** = low value or blocked.
- Never size by rate × window or by summing capped rows. Lakebase defaults to Investigate.

So a performance-led item with no DBU line can be Act now, provided it has a measured impact, a
low-risk lever, and a notebook cell that re-measures after the change. Never invent a DBU figure to
qualify an item. Disqualifiers take precedence over defaults, and defaults over the rule: the
ordered precedence list and a worked Act-now example are in the catalog's
[tier rule](references/opportunity-catalog.md#tier-rule). The worked anti-examples are in
`verify.md` and the catalog. Score confidence with the rubric in `verify.md`.

Write the result to `<run-dir>/analysis/backlog.json`: one item per carried opportunity **and
target**, with `id`, `target` (`<kind>:<raw id>` such as `warehouse:<id>` / `job:<id>`, or
`workspace`; the kind is one in the catalog entry's `Target kind` row; unique per `(id, target)`;
one item per target, e.g. OPP-JOB-OVERLAP one item per job, OPP-STEP-CHANGE one `workspace` item;
coverage is checked **per id** — a fired id is covered by one item or a cut — and the entry's
target-selection rule, not the trigger alone, decides which targets become items), `title`, `tier` (`act_now` / `investigate` / `not_now`),
`confidence`, `sizing` (`kind` / `value` / `unit` / `formula`; `value` is a number or `null`, never a
string; a `perf_metric` also carries `metric`, and `metric` + `unit` must be the id's row in the
catalog's [canonical perf metrics](references/opportunity-catalog.md#canonical-perf-metrics)
table), `evidence`, `lever` (exact field and value), and `notebook`.

`confidence_breakdown` (required in practice on `act_now` / `investigate` items): the
[confidence rubric](../starboard-engagement/references/verify.md#confidence-rubric) points per
component, `{"verified": 3, "reconciled": 2, "attributed": 2, "lever_confirmed": 0, "stable": 1,
"no_open_caveat": 0}`, whose values **sum to `confidence`**. Score it from the rubric, not by feel,
then copy the sum into `confidence`. `run check` warns when an `act_now` / `investigate` item has no
breakdown and fails when the breakdown doesn't sum to `confidence`.

Optional: `depends_on`, a list of `"<OPP-ID>:<target>"` keys (the other item's `id` + `:` + its
`target`, e.g. `["OPP-JOB-WAIT-TASK:job:348089368173138"]`) naming the items that must happen
**first** because they address this item's cause. Use it when the catalog draws a root-cause link:
OPP-JOB-OVERLAP on a job `depends_on` that job's OPP-JOB-WAIT-TASK item; an item whose cause is the
step change `depends_on` `"OPP-STEP-CHANGE:workspace"`. The plan and the "Start this week" view put
a depended-on item first and mark it **do first** (see [Zero Act-now](#zero-act-now-start-this-week-investigate-ranked)).

Optional: `lever_command`, `{"kind": "cli" | "sql" | "json" | "bundle_yaml", "text": "…"}`, the
exact change for the lever (a `databricks …` CLI call, a SQL statement, a settings JSON fragment,
or the bundle YAML change) with real ids. `starboard-helper notebook render` writes `text`
verbatim into the notebook's operator-gated remediation cell. Without it, render fills a default
command **only when the `lever` states exactly one unambiguous `setting = value` for the id's
canonical field** (e.g. `max_num_clusters 2 → 3` on OPP-WH-QUEUE); when the lever names several
settings or numbers, or a different field (an OPP-JOB-TIMEOUT lever that proposes a
`RUN_DURATION_SECONDS` health alert while keeping `timeout_seconds` as is), the cell is an
operator **decision note** with the `lever` prose, not an inferred command. If you want a command
in that case, write it yourself as `lever_command`. **A bundle-deployed
job (vt-job-settings-history `deployment_kind` = `BUNDLE`) always gets bundle YAML**: render
translates a `json` / `jobs update` command into the bundle fragment plus a redeploy step (a
`jobs update` would be overwritten by the next deploy). For a warehouse resize, Apply sets the
proposed value and Rollback restores the current one. The catalog's
[lever commands](references/opportunity-catalog.md#lever-commands) table gives the kind per id.

`notebook render` (`--all` or `--item`) **writes each rendered path into the item's `notebook`
field in `backlog.json`** by default (`--no-update-backlog` to leave the backlog untouched), so you don't
reconcile paths by hand. Its JSON result carries `rendered` (the count) and `paths` (the notebook paths); check
the count equals your Act-now + Investigate items. Re-run `run check` after rendering.

`evidence` lists query ids plus, for Act now and Investigate, at least one **full run-relative path**
`analysis/verify/<file>.json` to a file that exists in the run dir. A bare `vt-warehouse-queue.json`
or a template id doesn't count: `run check` looks for the `analysis/verify/` prefix and the file.

Add a top-level `cut` list, `[{"id", "rule", "reason"}]` (optional `target`), for every catalog id
whose trigger fired but which you don't carry. `rule` is `disqualifier`, `no_evidence` or
`duplicate`; a real, sized signal below priority is a `not_now` item, not a cut (the catalog's
[cut vs Not now](references/opportunity-catalog.md#cut-vs-not-now) rule). `no_evidence` means the
source lacks the evidence: `run check` fails a `no_evidence` cut when none of that id's `Verify`
templates was attempted (a saved `ok: false` `.json` counts), and fails on a fired id that is in
neither `items` nor `cut`.

```json
{"workspace_id": "<id>", "generated_at": "<iso8601>", "facts_window": {"start": "…", "end": "…"},
 "items": [{"id": "OPP-WH-QUEUE", "target": "warehouse:<wh>", "title": "…", "tier": "act_now", "confidence": 8,
            "confidence_breakdown": {"verified": 3, "reconciled": 2, "attributed": 2, "lever_confirmed": 1,
                                     "stable": 0, "no_open_caveat": 0},
            "sizing": {"kind": "perf_metric", "metric": "peak_daily_queued_pct", "value": 31.2, "unit": "%",
                       "formula": "daily queued_pct 12–31% over 7 days (vt-warehouse-queue-<wh>); re-measure 7 days after the change"},
            "evidence": ["W-W01", "analysis/verify/vt-warehouse-queue-<wh>.json"],
            "lever": "max_num_clusters 2 → 3",
            "lever_command": {"kind": "cli", "text": "databricks warehouses edit <wh> --max-num-clusters 3"},
            "notebook": "deliverables/notebooks/opp-wh-queue-<wh>.py"}],
 "cut": [{"id": "OPP-WH-IDLE", "rule": "disqualifier", "reason": "all warehouses serverless; est_idle_dbus is null by design"}]}
```

### Zero Act-now: "Start this week (Investigate, ranked)"
An empty Act-now tier is a legitimate result (cadence preconditions, recent-change disqualifiers,
intermittent queueing and "Investigate, always" defaults can all fire at once). Don't invent an
Act-now item and don't improvise a section name. When `items` has **no `act_now` item**, every
place that would list Act now (the exec summary's **Top opportunities**, the evidence pack's
**Act now** table, deck slide 3, the Slack post) shows **"Start this week (Investigate, ranked)"**
instead, built the same way on every run:

1. Take the `investigate` items.
2. **Prerequisites first.** An item another Investigate item `depends_on` (its cause) goes ahead
   of the item that depends on it, whatever their confidence: OPP-JOB-WAIT-TASK before
   OPP-JOB-OVERLAP on the same job; OPP-STEP-CHANGE before the items whose cause it is, when the
   plan names the step as their cause. Mark such a row **do first** and name what it unblocks
   ("do first: unblocks OPP-JOB-OVERLAP on job 348089368173138"). Otherwise the view tells the
   reader to confirm the symptom before the cause.
3. Then order by `confidence` (highest first); then items with a numeric `sizing.value` before
   `pilot` / `null` ones; then by their order in `backlog.json` (your impact ÷ effort rank) as the
   tie-break. Apply the same order inside a dependency chain.
4. Show the **top 5** (all of them when there are fewer). A depended-on item that would fall
   outside the five is pulled in ahead of its dependent. Each row's action is the item's
   **confirming step** (the measurement or owner confirmation that would make it Act now), not the
   lever itself, with the item's notebook.
5. Say in one sentence above the table that no item met the Act-now bar this cycle and why (name
   the disqualifiers that fired), so a reader doesn't take the empty tier as an omission.

The Investigate section still lists every Investigate item; "Start this week" is the ranked view
of its first five.

### Synthesize — the shape
Build the substance around the engagement **`templates/evidence-pack.md`** (the ranked-backlog spine):
every carried opportunity gets a **native-remediation** preview + **evidence-cite** + confidence entry
in the pack, plus one **`templates/notebook.py`** for each Act-now **and** Investigate item
(`deliverables/notebooks/<slug>.py`, the backlog `notebook` path). The exec summary goes in
**`templates/cost-review-doc.md`**. The full set then passes **technical-review** (accuracy) and
**humanize** (voice) before delivery. The bar is a doc set a Solutions Architect can hand to a customer.

## Finding-specific notes

### SVA-03 — Serverless performance mode lever

When the discovery or workload review surfaces **SVA-03** (serverless performance-target
mix), the catalog id is **`OPP-SERVERLESS-STANDARD-MODE`**:

- **What the docs say.** Serverless jobs have two performance modes. Standard mode suits
  "workloads that can tolerate slightly higher startup latency of **4 to 6 minutes**". "Both
  modes use the same SKU, but standard performance mode consumes fewer DBUs." The docs
  publish **no percentage saving** (Databricks docs, *Run your Lakeflow Jobs with serverless
  compute*, `docs.databricks.com/aws/en/jobs/run-serverless-jobs`, checked 2026-10-01). Don't
  quote a percentage, and don't write "up to X%".
- **The setting.** Job-level `performance_target: STANDARD`. The other value is
  `PERFORMANCE_OPTIMIZED`, which is the default. In the job UI, clear "Performance optimized".
  A pipeline triggered by a job's pipeline task runs with that job task's setting. Don't write
  `COST_OPTIMIZED`. On a **bundle-deployed** job the change goes in the bundle source
  (`lever_command` kind `bundle_yaml`, then redeploy): a `jobs update` is overwritten by the next
  deploy and would silently end the pilot.
- **Pilot target (deterministic).** The highest-DBU job in `data.facts.top_jobs` that is
  CRON-triggered, has no SLA tighter than its run time plus about 6 minutes, averages ≥ 30 min
  per run, and has no **Act-now** item this cycle. An Investigate or Not-now item on the same job
  doesn't disqualify it (it is a measurement or an owner question, not a change).
- **Sizing is "pilot: measure".** Move the pilot job to `STANDARD` for 7 days and compare DBU
  per run and wall-clock per run against the prior 7 days (vt-perf-target-mix + vt-job-runs).
  The item stays **Investigate** until that measurement exists. Never project a flat saving
  across the serverless pool.
- **Do not apply to interactive/SQL workloads**, continuous pipelines, or any job where users
  wait on the startup; those stay `PERFORMANCE_OPTIMIZED`.

## Deliver
Hand the finished Markdown plan to **[`starboard-deliver`](../starboard-deliver/SKILL.md)** (the
capability-bind vertical), and save it to `<run-dir>/analysis/action-plan.md` plus the customer copy
`<run-dir>/deliverables/action-plan.md` (`<run-dir>` is defined once in the engagement scaffold's
Outputs layout). Write `<run-dir>/analysis/backlog.json` alongside it, add/update the run's
`README.md` index, and finish with
`starboard-helper run check <run-dir> --out <run-dir>/analysis/run-check.json` (see the engagement
`references/run-checklist.md`). Never write to the customer's Databricks workspace (read-only).
