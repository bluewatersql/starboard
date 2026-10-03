---
name: starboard-engagement
description: 'The reusable Starboard engagement scaffold — the shared phase flow, primitives, and templates that every customer-facing workflow composes (cost action plans, reliability reviews, QBR decks, CRM touchpoints). Load this alongside a vertical skill (e.g. starboard-action-plan, starboard-deliver): it supplies the beats (gather → scope → verify → present → synthesize → technical-review → humanize → deliver → recur), the composable primitives, and the doc/slide templates so the vertical stays thin and the output is customer-ready, not an agent dump. Use whenever you are running or authoring any Starboard engagement workflow.'
compatibility: opencode
metadata:
  source: packages/starboard-skills/skills/starboard/starboard-engagement/SKILL.md
---

# Starboard: Engagement scaffold

> **Before you start:** open [`references/run-checklist.md`](references/run-checklist.md); you are done only when `starboard-helper run check <run-dir> --out <run-dir>/analysis/run-check.json` exits 0. The saved `analysis/run-check.json` is the record; don't paste the summary into `README.md`.

This is the **shared engagement workflow** — one shape reused across many verticals, so a new
workflow is a *thin vertical that composes this scaffold*, never a new monolithic skill. It is the
parent skill: load it **together with** a vertical (`starboard-action-plan`, `starboard-deliver`, or a
future one). The vertical supplies *what* is analyzed; this scaffold supplies *how* an engagement runs
and how it's made customer-ready.

**You are the analyst.** You (the host) are the LLM. You reason, prioritize, validate, and write —
there is no second LLM in this loop, and no deterministic ranking kernel. Do not call the `starboard`
goal agent or an MCP `*_analysis` / `synthesize_*` tool for the reasoning; the data comes from the
vertical's fetch layer (host **MCP** tools where present, else the **`starboard-helper`** CLI), and the
judgment is yours.

## The phase flow (the beats — do not skip scope, verify, present, review, humanize)

```
gather → scope: workspace (CONFIRM) → verify → present: verified shortlist (CONFIRM)
      → synthesize → technical-review → humanize → deliver (CONFIRM) → recur
```

1. **gather** — the vertical fetches findings/data (MCP or `starboard-helper`). Pull **both** the
   cost picture (`system.billing.usage` by product — jobs, SQL, serverless, Lakebase, Vector Search,
   etc.) **and** the performance/reliability findings across the review domains (latency, failure
   rates, SLA/stability). Tag every number with its source (`query_id`/pack/row) **and its
   `workspace_id`**. `system.billing.usage` is account-scoped; never present an account-wide total
   as one workspace. Retain the full evidence — later beats surface it, they don't discard it.
   **Quote headline numbers verbatim from `data.facts` in the discovery envelope** — never recompute them.
   A field named in `data.facts.fallbacks` (`{field: query_id}`) was filled from a fallback pack
   because its primary query was unavailable; quote it and cite that query id. For the spend
   story's "current run-rate", quote `data.facts.step_change.current_7d_avg_daily_dbus`,
   `pre_step_avg_daily_dbus` and `current_vs_pre_ratio` verbatim (don't derive them from daily
   totals). Read **every** row of a pack you scan for a pattern, not the first few: a
   `wait_for_*_readiness` task at row 7 or 11 of C-J09 is still a fired OPP-JOB-WAIT-TASK, and it is
   often the root-cause link between a run-length step change and job overlap.
2. **scope — CONFIRM the workspace, and only the workspace.** If the data spans multiple workspaces,
   say so and ask which to analyze: the profile's default workspace or all of them. Do **not** ask
   the user to pick opportunities yet — that gate moves to `present`, after they are verified.
3. **verify** — re-check at least the top **~8** candidate opportunities — selected by composite
   priority across cost and performance (see [`references/verify.md`](references/verify.md)) — and
   every candidate you will carry as Act now or Investigate (eight is a floor, not a budget) — live (read-only
   `query sql`): reconcile each headline number against `system.billing.usage` (not a 50-row-capped
   pack floor), push attribution to a workspace and, where the product allows, an endpoint/instance,
   assign confidence 1–10 and an expected **recoverable DBU** (bounded — never a per-day rate
   projected across the window). Never fabricate. Run each check with
   `starboard-helper verify run <vt-id> --templates <this-skill-dir>/references/verify-sql.md --ws <id> --start … --end … [--job-ids …] --out <run-dir>/analysis/verify/`
   (the overlay passes its own template file and `--internal-workspace-id` on the no-connect path;
   `--ws` then defaults to that id); on a timeout use the staged 1-day fallback in
   [`references/verify.md`](references/verify.md).
4. **present — CONFIRM the shortlist and the artifact set.** Show the **verified** backlog tiered
   Act now / Investigate / Not now (each with number + evidence + confidence). Ask the user which
   opportunities to carry and **which artifacts to generate** (deck / exec summary / evidence pack +
   notebooks / Slack / CRM draft). Because the list is already verified, selection can't collapse to
   nothing. Build only after they answer.
5. **synthesize** — build the substance: the evidence pack + action plan + charts + one notebook per
   carried Act-now AND Investigate item, composing the primitives below. Generate the notebooks from
   `analysis/backlog.json` with
   `starboard-helper notebook render --backlog <run-dir>/analysis/backlog.json --all --run-dir <run-dir> --out <run-dir>/deliverables/notebooks/`
   (`--item <OPP-ID>[:<target>]` for one item) — don't hand-build them. Render writes each notebook
   path into its item's `notebook` field in `backlog.json` by default (`--no-update-backlog` to
   skip), so there is no separate path-registration step; a bundle-deployed job's remediation
   cell is always bundle YAML plus a redeploy. Map every opportunity to its
   catalog id (e.g. `OPP-WH-IDLE`); see `starboard-action-plan/references/opportunity-catalog.md`
   (contract §2). Render every deliverable chart to PNG with
   `starboard-helper charts render --kind <kind> --data <rows.json> --out <run-dir>/deliverables/charts/<name>.png`
   (needs the `starboard-skills[render]` extra; `--help` lists every kind and its required
   columns). The data file is a **JSON array** of row objects, or **NDJSON** (one object per
   line), whose keys are the kind's **required columns**, so rename the source fields first:

   | Kind | Source rows | Rename (source → required column) |
   |---|---|---|
   | `dbu-trend` | vt-daily-totals rows | `usage_date` → `usage_date`, `dbus` → `total_dbus` |
   | `spend-by-product` | `data.facts.product_mix` | `product` → `billing_origin_product`, `dbus` → `total_dbus` |
   | `spend-concentration` | `data.facts.top_jobs` / `top_pipelines` (or any entity list) | `name` → `driver`, `pct` → `share_pct` |
   | `recoverable-dbu` | `analysis/backlog.json` `bounded_dbu` items | `title` → `opportunity`, `sizing.value` → `recoverable_dbus`, `tier` → `confidence_tier` |

   Write literal JSON with `jq -n` (plain `jq` with no input writes an empty file). To transform
   a verify file, wrap the result in `[ … ]` for an array, e.g.
   `jq '[.data.rows[] | {usage_date, total_dbus: .dbus}]' analysis/verify/vt-daily-totals.json > rows.json`
   (without the brackets jq streams one object per line, which `charts render` reads as NDJSON).
   `python -m starboard_x.charts` emits specs only and doesn't render.
6. **technical-review** — accuracy gate, now covering the generated code too:
   [`references/technical-review.md`](references/technical-review.md).
7. **humanize** — the de-AI-slop voice gate: [`references/humanize.md`](references/humanize.md).
8. **deliver** — bind capabilities to tools, preview + confirm, degrade visibly; write to the Drive
   folder [`references/capability-bind.md`](references/capability-bind.md). See [**Outputs layout**](#outputs-layout) for the run-directory structure.
9. **recur** — a stateless run-over-run comparison; no standing service, no daemon. Each recurrence
   is a fresh review that diffs against the previous run's local manifest. It works the same on
   the live-connect path (`--profile <workspace>`) and the no-connect path
   (`--internal-workspace-id <id>`, overlay installed): both write `findings-manifest.json` and
   both take `--since`. Below, `<target>` is either flag and `<ws>` is the workspace dir name.
   1. **Locate the prior run.** The newest *other* run dir for this workspace with a manifest:
      `ls -1d starboard-reports/<ws>-*/findings-manifest.json | sort -r` (skip the current run).
      None = this is the **baseline** run: omit `--since`, and this run's manifest becomes the
      baseline for next time.
   2. **Run the review, write the manifest, save the JSON.** When this run has a discovery
      output (`<run-dir>/discovery/`, beat 1), review it — after discovery finishes, never
      concurrently:
      ```bash
      mkdir -p <run-dir>/analysis
      starboard review --from-discovery <run-dir>/discovery --json \
        --out <run-dir>/analysis/review.json \
        --manifest-out <run-dir>/findings-manifest.json \
        --since <prior-run-dir>/findings-manifest.json
      ```
      `--out` writes the JSON envelope; never redirect stdout (`> review.json 2>&1` saves the
      banner and logs into the file). `--from-discovery` evaluates the rules on the saved
      discovery rows: offline (no second scan, no connection), workspace + lookback inherited
      from the discovery output, so review and discovery agree. A query that was skipped in
      discovery degrades its domain: the review JSON and the manifest carry `degraded`,
      `unavailable_queries` and `unavailable_domains`, and recur marks those domains "not
      comparable" (their finding counts aren't a trend). `unavailable_queries` counts only
      skipped queries a review rule reads; the manifest's `discovery_skipped` lists every query
      discovery skipped and `coverage_note` says which of them no rule uses, so an empty
      `unavailable_queries` is not "full coverage". With no discovery run (a standalone or
      scheduled review), use `starboard review <target> --lookback-days 30 --json --out …` with
      the same `--manifest-out` / `--since` flags. (Drop `--since` on the baseline.) The manifest is the machine-readable per-run record:
      per-finding `rule_id`, `entity_id`, `composite_key` (`rule_id::entity_id`), `severity`,
      `score`, and `evidence_dbu_estimate` (list-price DBU; null for reliability/latency findings
      with no DBU attribution). With `--since` the JSON carries the cost-aware `cost_delta`, keyed
      on `composite_key`: `newly_expensive` / `regressed` / `improved` / `persisting` /
      `new_low_cost`, with per-entry `prior_dbu` / `current_dbu` / `dbu_delta` / `dbu_delta_pct`,
      plus `products_dbu_delta`. Manifests are **local files only** — never written to the
      customer workspace. (A v1 `snapshot.json` on `--since` still yields the presence/absence
      `action_rate` — the backward-compatible path.)
   3. **Run the recur helper** — deterministic; do not hand-build the trend JSON:
      ```bash
      starboard-helper run recur <run-dir> --workspace-root starboard-reports/<ws> [--prior <prior-run-dir> | --baseline]
      ```
      It auto-locates the same prior run: the newest other run dir for `<ws>` with a manifest,
      searching only run dirs under the workspace root or beside it (`<ws>-<YYYY-MM-DD>*`), never the wider tree. Pass
      `--prior` to pin it (prompt-supplied run-dir names), or `--baseline` to skip the lookup on a
      first run. `--workspace-root` may be any directory except the run dir itself. Then it:
      - appends `{run_date, total_dbu_estimate, finding_count, critical, high, medium}` to
        `starboard-reports/<ws>/trend/history.json` — idempotent by `run_date`
        (`total_dbu_estimate` = sum of the manifest's `products_dbu`; list-price, label it);
      - writes `charts/data/spend-over-time.json` + `finding-count-over-time.json` and renders
        `charts/trend/spend-over-time.png` + `finding-count-over-time.png` (if the render extra
        is missing it writes the data and says so in `warnings`);
      - writes the `analysis/delta-vs-<prior-date>.md` skeleton from `analysis/review.json`'s
        `cost_delta` — improved / regressed / newly expensive / persisting / new low-cost tables
        (entity, prior→current DBU, %), with both trend PNGs embedded — plus the **primary
        trend**: the backlog's `sizing.value` per `(id, target)`, prior → current (Δ only when the
        metric and unit match), and a backlog delta by catalog id (new / resolved / tier changed).
        The history entry also records the backlog tier counts and per-item sizing. Write
        `backlog.json` before running recur;
      - writes README `## Recur`: `baseline — no prior run` on the first run, else the delta
        summary (`delta vs <prior-date>: N improved, M regressed, …`) with links;
      - writes `analysis/recur-result.json` — `{ok, baseline, prior_run, history_path,
        history_entry, backlog_delta, errors}`. `run check` requires `ok: true` (or
        `baseline: true`); on a failure read `errors`, fix, and re-run (it is idempotent).

      Recur artifacts, relative to `<run-dir>` unless noted: `charts/data/*.json` (trend rows),
      `charts/trend/*.png` (trend charts — not under `deliverables/`; copy one into
      `deliverables/charts/` if the customer artifact needs it), `analysis/delta-vs-<prior-date>.md`
      (recurrence only), `analysis/recur-result.json`, README `## Recur`, and
      `<workspace-root>/trend/history.json` (outside the run dir).

      **Isolated run dir (prompt tests).** When the prompt fixes `RUN_DIR` (e.g.
      `starboard-reports/<MODEL>/<RUN_ID>`) and forbids reading other runs, use
      `--workspace-root "$RUN_DIR/ws-root" --baseline`: history goes to
      `$RUN_DIR/ws-root/trend/history.json` and nothing outside `$RUN_DIR` is touched.
   4. **Write the narrative.** You (the analyst) replace the `_Analyst:` placeholder in
      `analysis/delta-vs-<prior-date>.md`: what improved, what regressed, what is newly expensive,
      and why. Don't read a change in a "not comparable" (degraded) domain as improvement or
      regression — say the evidence was unavailable on one side. `$`/DBU = list-price estimate; product-level DBU totals are account-scoped,
      finding-level DBU is workspace/entity-attributable — carry that caveat. A real trend needs
      ≥2 runs; the baseline renders a single point.
   5. **Deliver** via `starboard-deliver` (beat 8) to the operator's confirmed destinations, and append a
      one-line audit entry to `starboard-reports/schedule.log`. **Skip the append on an isolated
      run dir** (prompt test, same carve-out as the trend root above): `schedule.log` is outside
      `$RUN_DIR`, so record the line in README `## Recur` instead.

   **Scheduling.** For unattended recurrence, wire the `starboard-workload-review-auto` agent to a
   **durable** `CronCreate` schedule — `0 8 1 * *` for a monthly review — and confirm it with
   `CronList` (see that agent's **Scheduling** section; recipes for both `--profile` and
   `--internal-workspace-id`). The agent finds the prior run itself each time. The internal path
   works unattended but needs the internal credentials/profile on the machine that runs it. The
   `recur` beat itself stays stateless: each run is a fresh review that diffs against local files.

**Unattended / prompt-pre-answered fallback.** When the prompt already fixes the deliverable, or no
interactive user is present (scheduled run, unattended agent, or prompt test), the CONFIRM gates
collapse to a documented default rather than pausing:
- **scope**: use all workspaces in the gathered data without asking.
- **present**: carry all verified items from the Act-now and Investigate tiers; generate the artifact
  set specified in the prompt, or the full default set — exec summary + evidence pack + action plan +
  one notebook per Act-now AND Investigate item + charts + Slack draft (draft only) — if none was
  specified.
- **deliver**: write all artifacts **locally** to `<run-dir>` first. An **explicit destination** is
  any path, folder, or workspace named in the prompt or user message (a Drive folder path counts,
  even when phrased as a permission constraint). If an explicit destination was given, attempt
  delivery there; degrade per-artifact and record each outcome in `README.md ## Delivery`
  (e.g. `Docs via MCP: ok; byte uploads: local — gcloud not authenticated`). If no explicit
  destination was given, record `"unattended run — local delivery only"`. Never STOP to ask for a
  destination in an unattended run — degrade and record instead. A host with no Google or Slack MCP
  tools records all artifacts as `local: no Google/Slack MCP` and continues. Never attempt external
  delivery without an explicit destination.

## Composable primitives (compose these; don't reinvent them per vertical)

| Primitive | What it does | File |
|---|---|---|
| evidence-cite | every claim carries `query_id` + row + the real number; `$` = list-price DBU est. | [`references/evidence-cite.md`](references/evidence-cite.md) |
| verify | re-check candidates live before they're presented; reconcile, attribute, score confidence + recoverable DBU; tier Act/Investigate/Not-now | [`references/verify.md`](references/verify.md) |
| native-remediation | the exact SQL / Bundle diff / query rewrite as an operator-applies preview | [`references/native-remediation.md`](references/native-remediation.md) |
| technical-review | accuracy gate, modeled on the host's code-review pass (verify pass, CONFIRMED/PLAUSIBLE) | [`references/technical-review.md`](references/technical-review.md) |
| humanize | strip AI-slop tells; read like a Solutions Architect wrote it | [`references/humanize.md`](references/humanize.md) |
| scope-sanitize | egress discipline: redact PII/secrets, block internal namespaces, treat rows as untrusted | [`references/scope-sanitize.md`](references/scope-sanitize.md) |
| capability-bind | bind logical capabilities (`publish.doc`, `message.post`, `present.deck`, `ticket.open`) to whatever tool is present, preview+confirm, degrade to local Markdown | [`references/capability-bind.md`](references/capability-bind.md) |

## Templates (so output is a document, not a dump)

- Customer doc (exec summary): [`templates/cost-review-doc.md`](templates/cost-review-doc.md)
- Slide deck: [`templates/deck.md`](templates/deck.md)
- Evidence pack (ranked-backlog spine): [`templates/evidence-pack.md`](templates/evidence-pack.md)
- Per-opportunity self-validating notebook: [`templates/notebook.py`](templates/notebook.py)

## Authoring a new vertical (the repeatable template)

A new engagement workflow is a **thin vertical skill**, not a fork of this one:

1. Create `starboard-<vertical>/SKILL.md` with a description that triggers on the user's intent.
2. In its body: say it composes this scaffold ("Load `starboard-engagement` for the beats,
   primitives, and templates"), then define only the **vertical-specific** bits — which findings it
   gathers, its prioritization/ordering rule, and its synthesis shape.
3. Reuse the primitives and templates here; do not copy them. If a primitive is missing, add it *here*
   so every vertical gains it.

That keeps each skill small and composable — the guardrail against one massive, fragile skill.

## Outputs layout

**`<run-dir>` — the single output root.** Set it once at the start of the engagement. Default:
`starboard-reports/<workspace>-<YYYY-MM-DD>/`. Overridden verbatim by the prompt (use as given) or
by the overlay's convention for an internal workspace id: run dirs
`starboard-reports/ws-<id>-<YYYY-MM-DD>/`, trend root `starboard-reports/ws-<id>/`. Every beat and every template uses `<run-dir>/…` —
never a hard-coded absolute path outside it.

All engagement artifacts live under a single, dated run directory. Every vertical and focused skill
writes here and keeps the `README.md` current.

```
starboard-reports/
  <workspace>/                     # workspace-level parent — cross-run state that outlives any single run
    trend/
      history.json                 # accumulated per-run metrics (recurrence trend; see the recur beat)
  <workspace>-<YYYY-MM-DD>/        # one run dir per run (see collision rule below)
    README.md            # "start here" index: what this run is, headline numbers, a pointer to each artifact
    discovery/           # workspace discovery — plan.json, raw/<pack>.json, domains/<domain>.md, analysis.md (starboard-discovery)
    analysis/            # focused-domain reviews + the action plan; review.json (saved `starboard review --json`),
                         #   backlog.json, verify/, recur-result.json (`run recur`),
                         #   run-check.json (`run check --out`)
                         #   + delta-vs-<prior-date>.md on a recurrence
    findings-manifest.json  # machine-readable per-run record (recurrence keystone; local only; both paths)
    charts/              # data/ (trend chart rows) + trend/ (cross-run trend PNGs) — written by `run recur`
    deliverables/        # final customer artifacts (deck, exec summary, evidence pack, notebooks,
                         #   charts/*.png from `charts render`) — mirrors the Drive folder
```

- `<workspace>` = the workspace/profile name, or `ws-<id>` for an internal workspace id;
  `<YYYY-MM-DD>` = run date.
- **Same-day collision rule (avoid mixing runs).** Before writing, check whether
  `starboard-reports/<workspace>-<YYYY-MM-DD>/` already exists from an earlier run
  today. If it does, start a **fresh** run dir suffixed to the minute —
  `<workspace>-<YYYY-MM-DD-HHMM>/` — rather than writing into the existing one.
  A repeat run must never silently overwrite or interleave a prior run's
  `analysis.md` / `discovery/` / `raw/` artifacts (there is no cache; each run's
  data is independent). The `-2`/`-3` filename suffix the focused skills use only
  disambiguates a single report file — it does not protect the whole run tree.
- **Trend storage decision (resolved).** The accumulated trend history lives at the **workspace level**
  (`starboard-reports/<workspace>/trend/history.json`), *not* in a dated run dir — so it persists across
  runs and a single read gives the whole series (no scanning every prior run dir). The rendered trend PNGs
  for a given run are written into that run's `charts/trend/`, so each run's deliverables are self-contained.
- **The orchestrator owns the shared surfaces.** When the run is split across subagents, only the
  orchestrating agent writes `deliverables/`, `README.md` and the Drive folder (and creates or
  deletes Docs). A subagent writes only its assigned files (e.g. `discovery/domains/<domain>.md`,
  an `analysis/` draft) and returns; put that boundary in every subagent prompt
  ([`references/capability-bind.md`](references/capability-bind.md) Rule 6a).
- **Create or update `README.md`** whenever anything is written to the run dir — it is the one file
  a user opens first. Always include:
  - `## Delivery` — one line per artifact: its destination (a URL or `deliverables/` path), or
    `local: <reason>` / `not delivered: <reason>`. `run check` fails a section with no such entry,
    so a placeholder such as "(filled at delivery)" fails: write the real outcomes at delivery.
  - `## Recur` — `baseline — no prior run` on a first run, or a delta note on a recurrence
    (`starboard-helper run recur` writes it; `run check` fails on an empty section).
  - No `## Run check` section is needed: `run check … --out <run-dir>/analysis/run-check.json`
    saves the result.
- Drive target is unchanged (`My Drive/starboard/<Workspace Name>/<YYYY_MM_DD>/`); the local `deliverables/` mirrors it.

## Guardrails (every vertical inherits these)

- Read-only to the customer's Databricks workspace; deliver only to the operator's own destinations.
- `$`/DBU figures are **list-price DBU estimates**, labeled — never finance-grade.
- `scope-sanitize` runs before anything leaves: no PII/secrets/internal namespaces in customer output.
- Every external write is preview + confirm; a missing delivery tool degrades **visibly**, never silently.
- If a Starboard internal enrichment overlay is available in this session, consult it at the scope, verify, and deliver beats for additional signals, and reconcile them into the evidence — the public flow and output discipline are unchanged.
