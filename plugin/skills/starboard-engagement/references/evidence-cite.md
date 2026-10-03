# Primitive: evidence-cite

Every claim in a plan cites its source data point — the **`query_id` + row + the actual number**
(e.g. "warehouse `wh-idle`: `auto_stop_waste_pct=80%` over 30d, query `W-W02`"). No uncited
assertions.

- Tie each recommendation to the specific evidence that produced it, and note whether that evidence
  was **verified live this run** or is **system-table only** (feeds the technical-review verdict).
- `$`/DBU figures are **list-price DBU estimates**, labeled as such — never finance-grade.
- If you can't cite a number, you can't assert it — say what's needed to confirm it instead (see
  the confidence/sufficiency gate in [`technical-review.md`](technical-review.md)).

## The backlog is the spine

The verified backlog produced in the `verify` beat is the **single source of truth** for the
engagement. Every output — deck, doc, exec summary, Slack post, CRM draft — is a *view* of that
backlog, never a re-derivation from raw data.

Structure every backlog entry as:

```
- id:       OPP-... (from the opportunity catalog)
  Tier: Act now | Investigate | Not now
  query_id: <pack-id> + analysis/verify/<file>.json (required for Act now / Investigate)
  row:      <e.g. workspace_id=ws-abc, endpoint=vs-prod-01>
  number:   <the real verified figure, e.g. 2,940 DBU/month>
  confidence: <1–10, scored with the verify.md rubric, e.g. 8 (V3 R2 A2 L0 S1 C0): the same
              points as the backlog item's confidence_breakdown, summing to the score>
  sizing:   <bounded_dbu | perf_metric | pilot | none> + value (a number, e.g. 4819.5, or null
            for a pilot) + unit (e.g. DBU) + the catalog formula with its arithmetic
  reason (Not now only): <why it was cut>
```

The machine-readable copy of this backlog is `analysis/backlog.json`. The tier vocabulary
(`Act now`, `Investigate`, `Not now`), the tier rule, and the verify-file requirement are defined in
[`verify.md`](verify.md). The ids, sizing formulas, and levers are in
[`opportunity-catalog.md`](../../starboard-action-plan/references/opportunity-catalog.md). Use those
names verbatim across all outputs.

Downstream templates (deck slides, doc sections, exec summary bullets) pull from this backlog;
they do not re-score or re-rank. If the user asks for a different view, reorder the backlog
entries — do not derive new numbers.

**Within-tier ordering** follows the composite priority established in the `verify` beat
(impact ÷ effort, with cost and performance as co-equal impact inputs) — not re-ranked by raw
DBU. Cost findings and performance/reliability findings are treated equally: a reliability fix
with high impact and low effort ranks above a cost item that is large but hard to attribute or
action.

## Recoverable-DBU citation rule

Every recoverable DBU estimate must show **its arithmetic and its bound**. The bound is the
audited population, not a projection rate.

Correct form:

> ≈2,940 DBU/endpoint × 300 audited-abandoned endpoints = ≈880K recoverable DBU

Incorrect forms:

> ~880K DBU/month (no arithmetic shown)
> 2,940 DBU/day × 30 days = 88,200 DBU (rate × window — not a bound)

The arithmetic must be reproducible: a reader should be able to check each factor against the
cited evidence row. Label all figures as **list-price DBU estimates** — never finance-grade.
