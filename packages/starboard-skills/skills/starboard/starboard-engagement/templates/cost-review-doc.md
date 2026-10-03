# Template: exec summary (leadership-facing)

**No-text-dump rule: this document is a summary, not a data export. Prose is tight — one paragraph
per section, never a wall of bullets. Tables carry data; prose carries judgment. Every number
cites its source (see [`../references/evidence-cite.md`](../references/evidence-cite.md)).
Apply [`../references/humanize.md`](../references/humanize.md) and
[`../references/scope-sanitize.md`](../references/scope-sanitize.md) before this leaves.**

---

```markdown
<!-- Branded title block. Delivery inserts the Starboard logo as an image via the Docs API
     ({{starboard_logo}} marks its placement) — not a Markdown paste. Source of truth:
     `assets/starboard_logo.png`; hosted Drive id for image insert:
     `1XUFmeZSJn0h9UZoSGfpbLkgD_I0GNT1I` (see capability-bind Rule 8 for the full logo story).
     The logo source is >1 MiB — do NOT inline it via the Docs MCP local-image path (MCP image
     inline is for chart PNGs, not large assets); use the pre-uploaded hosted Drive copy id above
     for `insertInlineImage`, or omit if unavailable. If the hosted copy is unavailable, keep the
     wordmark and omit the image. Match the deck title slide so doc and deck read as one branded
     product. -->
{{starboard_logo}}
**Starboard** — Databricks workload analysis

# Databricks Cost Review — <Customer / Workspace>
<Prepared by> · <Date> · <Lookback: 30 days> · <Scope: workspace(s)>

Figures are list-price DBU estimates; DBU is a usage unit, not a negotiated dollar amount.

---

## Summary

<!-- 3–5 sentences of plain prose. Lead with the most important action, then the size,
     then the honest caveat. No bullet lists here — this is the paragraph a leader reads
     and forwards. Write it; do not generate it from a template sentence. -->
<Where the spend is concentrated in one sentence. The one structural fact that shapes
everything. The 2–3 moves worth making, each sized in recoverable DBU. What was ruled
out and why — one clause.>

---

## Spend breakdown

<!-- One table + one embedded chart. No commentary prose in this section — the chart
     and the table speak for themselves. Render the chart at a Doc-friendly width (use
     --width 600 if the renderer supports it; otherwise the default is fine):
       starboard-helper charts render --kind spend-by-product --data <rows.json> \
         --out <run-dir>/deliverables/charts/spend-by-product.png
     Embedding at {{spend_by_product_chart}}: prefer the **Docs MCP local-image inline path** —
     `docs_document_create_from_markdown` accepts absolute local file paths for images and
     embeds them without gcloud/curl. Use the absolute path to the rendered PNG.
     gcloud/curl is only needed if you want to upload the PNG as a standalone Drive binary
     file (e.g. to get a hosted URL for `insertInlineImage` in the structured Docs API).
     If the Docs MCP is unavailable, insert a visible note in place of the chart —
     e.g. "Chart: <run-dir>/deliverables/charts/spend-by-product.png" — and reference the
     local file. Not a Markdown paste. -->

{{spend_by_product_chart}}

| Product | 30-day DBU (list-price est.) | % of total | Note |
|---|---:|---:|---|
| … | … | … | one clause, not a sentence |

Source: system.billing.usage · workspace <ws-id> · <date range>

---

## Top opportunities

<!-- One table. Rows come directly from the Act-now tier of the verified backlog
     (see the evidence pack) — do not re-derive. No prose needed here; the table
     is the message.
     ZERO ACT-NOW: when the backlog has no act_now item, title this section
     "## Start this week (Investigate, ranked)" and use the table below it instead. Build it
     exactly as the action-plan skill's "Zero Act-now" rule says: investigate items ordered
     prerequisites first (`depends_on` targets, marked "do first"), then confidence (desc), then
     numeric sizing.value before pilot/null, then backlog order; top 5.
     One sentence first: no item met the Act-now bar this cycle, and which disqualifiers fired. -->

<!-- Zero-Act-now variant:
One sentence: "No item met the Act-now bar this cycle (<disqualifiers that fired>); these are the
first confirming steps, ranked."

| # | Opportunity | Confirming step this week | Signal (verified) | Confidence | Notebook |
|---|---|---|---|:---:|---|
| 1 | … | <the measurement / owner confirmation that would make it Act now> | <canonical metric or bounded DBU> | n/10 | notebooks/<slug>.py |
-->

| Opportunity | Recoverable DBU (est.) | Performance impact | Confidence | Owner |
|---|---:|---|:---:|---|
| … | … | <latency / queueing gain — or "adds ~n DBU at peak" — or "cost-only"> | n/10 | … |

<!-- Cost-led plan: lead with the DBU column. Performance-led plan: lead with the
     performance column and write "n/a — performance-led" in the DBU cell rather than
     inventing a saving. A fix that adds DBU at peak says so here. -->
All figures are bounded estimates from verified populations, not rate projections.
Full arithmetic in the [evidence pack](evidence-pack.md).

---

## Investigate

<!-- One short paragraph only. Name the findings that need one more step; say what
     the step is. Do not expand into a full analysis here. -->
<n findings> have a real signal but need a confirming step before they are actionable:
<brief list — one clause each>. The evidence pack carries the confirming query for each.
<Where the effect can't be bounded from the data, say "unbounded — measure via pilot" and name
what the pilot would measure, rather than forcing a DBU number.>

---

## Not recommended

<!-- One short paragraph. Name what was surfaced and why it does not warrant action.
     This is the credibility section — omitting it weakens the doc. -->
<n findings> were reviewed and set aside: <honest one-clause reason each>. Full detail
in the [evidence pack](evidence-pack.md).

---

## Re-check

**Public live-connect path:**

```
starboard review --profile <workspace> --since <prior-run-dir>/findings-manifest.json \
  --manifest-out <new-run-dir>/findings-manifest.json
```

`--since` takes the **path** to the prior run's findings manifest (or snapshot), not a date.
No standing service — this is a one-shot re-run.

**No-connect / internal path** (overlay installed): the same manifest and `--since`, by
workspace id:

```
starboard review --internal-workspace-id <id> --since <prior-run-dir>/findings-manifest.json \
  --manifest-out <new-run-dir>/findings-manifest.json
```

Then `starboard-helper run recur <new-run-dir> --workspace-root starboard-reports/<workspace>`
writes the trend charts and the delta skeleton. First run = baseline.
```
