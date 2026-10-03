# Template: engagement slide deck (visual-first)

**Hard rule: one idea per slide, led by a visual. Text is callouts, never paragraphs.
Every number carries its evidence citation (see [`../references/evidence-cite.md`](../references/evidence-cite.md)).**

---

## How the deck is built

The deck is delivered as a **local Markdown outline** — the slide-by-slide spec below — with charts
rendered to PNGs under `deliverables/charts/`. There is **no Slides/Drive deck-build path**: the
outline is the deliverable, and the operator imports or adapts it into their own presentation tool
and applies their own branding. This keeps the deck step dependency-free and reliable for every
operator (no shared base deck, no Slides API, no hosted assets required).

Render charts with:

```
starboard-helper charts render --kind <kind> --data <rows.json> --out <file.png>
```

Chart kinds come from `starboard_x.charts`. **Each kind needs specific input columns** — build
your data file to match the required fields before calling `charts render`:

| Kind | Required columns |
|---|---|
| `utilization-bands` | `utilization_band`, `node_count`, `resource` |
| `cost-trend` | `usage_date`, `list_cost_usd` |
| `dbu-trend` | `usage_date`, `total_dbus` |
| `rightsizing-waterfall` | `stage`, `list_cost_usd` |
| `spend-by-product` | `billing_origin_product`, `total_dbus` |
| `spend-concentration` | `driver`, `share_pct` |
| `recoverable-dbu` | `opportunity`, `recoverable_dbus`, `confidence_tier` |
| `cost-by-product` | `billing_origin_product`, `list_cost_usd` |
| `spend-over-time` | `run_date`, `total_dbu_estimate` |
| `finding-count-over-time` | `run_date`, `count`, `severity` |

For a DBU-denominated spend trend on the DBU-first path use **`dbu-trend`** (`usage_date` +
`total_dbus`); `cost-trend` requires dollars (`list_cost_usd`) and is for `$`-denominated data only.
There is no top-jobs kind: chart top jobs, pipelines, or other entities with
**`spend-concentration`**, mapping `data.facts.top_jobs` `name` → `driver` and `pct` → `share_pct`.
If the `starboard-skills[render]` extra (`vl-convert-python`) is not installed, `charts render`
produces no output — deliver the outline with the chart callouts in place and note visibly that the
charts are unavailable.

---

```
Slide 1 — Title
  Visual: title / branding (the operator applies their own logo and theme when they build
          the deck from this outline).
  Headline: <Customer> · Databricks Cost Review · <date>
  Sub: 30-day list-price DBU review · <scope: workspace(s)>
  Notes: one-line framing. State once: "Figures are list-price DBU estimates — DBU is a
         usage unit, not a negotiated dollar amount."

Slide 2 — Where the spend is  [CHART: spend-by-product]
  Visual: chart kind `spend-by-product`, rendered to a PNG under `deliverables/charts/`.
  Headline: "<Top 2–3 products> account for ~<n>% of spend"
  Callouts (≤3 lines):
    · The structural fact (e.g. "Serverless SQL is unattributed across teams")
    · Any single outlier worth naming
    · Source: system.billing.usage · workspace <ws-id> · 30d
  Notes: query_id + the verified figure from the evidence pack.
         NEVER paste the underlying table onto the slide.

Slide 3 — Total recoverable  [CHART: recoverable-dbu]
  Visual: chart kind `recoverable-dbu`, rendered to a PNG under `deliverables/charts/`.
  Headline: "~<total recoverable DBU> recoverable across <n> Act-now opportunities"
  Callouts (≤3 lines):
    · Bounded arithmetic summary (e.g. "3 levers × verified populations — not a projection")
    · Tier split: Act now <n> / Investigate <n> / Not now <n>
    · Confidence floor: "All Act-now items ≥ 7/10"
  Notes: sum of recoverable_dbu from the evidence pack (Act-now tier only).
         Label as list-price DBU estimate.
  Performance-led plan: if the Act-now items are mostly performance/reliability fixes, retitle
         the slide "Performance impact" — headline the latency/queueing/failure-rate gain, add
         a callout for any "adds ~n DBU at peak", and show the DBU total only if it is real.
         Do not sum an invented saving.
  Zero Act-now: retitle the slide "Start this week (Investigate, ranked)" — the top 5 Investigate
         items in the action-plan skill's "Zero Act-now" order (do-first prerequisites before the
         items that depend on them, then confidence), each with its confirming step,
         plus one callout naming the disqualifiers that kept every item out of Act now. Slides
         4..N then cover those items (the confirming step, not the lever, is the headline).

Slides 4..N — One slide per Act-now opportunity  (repeat this block for each)
  Visual: chart or table for this finding — chart kind if one applies (e.g. `spend-concentration`,
          `rightsizing-waterfall`), rendered to a PNG; otherwise a ≤5-row evidence table.
          NEVER paste raw query output as text.
  Headline: the action as a claim ("Auto-terminate idle clusters → ~<n>K recoverable DBU")
  Callouts (≤3 lines):
    · What: the specific change (one clause)
    · Owner / effort: <team or role> · <XS–XL>
    · Evidence: query_id + row + verified figure
  Notes: full evidence from the evidence pack for this opportunity:
         query_id, row attribution (workspace_id, endpoint/job/instance where resolved),
         recoverable DBU arithmetic, confidence score, and the linked notebook filename.

Slide N+1 — Investigate tier
  Visual: a clean ≤5-row table: opportunity · signal · step needed.
  Headline: "<n> findings need one more step before they're actionable"
  Callouts (≤2 lines):
    · What's blocking each (e.g. "owner lookup", "endpoint audit"); mark items whose effect
      can't be bounded as "unbounded — measure via pilot"
    · The notebook that carries the confirming query
  Notes: list each Investigate item from the evidence pack with its query_id and
         the one confirming step required.

Slide N+2 — Not now
  Visual: a clean ≤5-row table: finding · reason cut.
  Headline: "We looked at <n> more — here's why they don't move"
  Callouts (≤2 lines):
    · The honest summary reason (too small / already remediated / externally blocked)
    · "Full detail in the evidence pack"
  Notes: Not-now entries from the evidence pack. Every surfaced finding is disclosed;
         nothing is silently dropped.

Slide N+3 — Next steps
  Left column — Act-now moves:
    · 2–3 items, each: action · owner · target date
  Right column — Cadence:
    · Investigate items + who picks them up
    · Re-check command:
        starboard review --profile <workspace> --since <prior-run-dir>/findings-manifest.json
          --manifest-out <new-run-dir>/findings-manifest.json   (--since takes a path, not a date)
  Notes: confirm owners and dates with the customer before finalising.
```
