# Template: evidence pack (full ranked backlog)

The evidence pack is the **single source of truth** for the engagement. Every other artifact
(deck, exec summary, Slack post, CRM draft) is a view of this backlog — it does not re-derive
numbers. See [`../references/evidence-cite.md`](../references/evidence-cite.md) for citation rules
and [`../references/verify.md`](../references/verify.md) for tier definitions and the confidence
and recoverable-DBU scoring model.

**Authoring rule:** populate this from the `verify` beat output only. Do not assert any number
that is not cited here. Every recoverable-DBU figure shows its arithmetic and its bound —
never a rate × window projection.

---

```markdown
# Evidence Pack — <Customer / Workspace>
<Prepared by> · <Date> · <Lookback: 30 days> · <Scope: workspace(s)>

Figures are list-price DBU estimates. Verification: <fill in the actual verification surface —
which read-only source(s) the re-check queries ran against (e.g. the workspace's system billing and
information_schema tables, or the telemetry mirror the run was scoped to), the workspace scope, and
the date range. State only what actually ran; do not carry this line over from another run.>

---

## Backlog summary

<!-- Tier-grouped summary table. Rows are ordered by composite priority (confidence ×
     signal strength, descending) within each tier — not by recoverable DBU alone.
     Populate directly from verify-beat output — do not re-rank here. -->

### Act now

| # | Opportunity | query_id | Row (workspace · attribution) | Verified figure | Recoverable DBU (est.) | Confidence |
|---|---|---|---|---:|---:|:---:|
| 1 | … | … | ws-<id> · <endpoint/job/instance> | … DBU | … DBU | n/10 |

<!-- ZERO ACT-NOW: when the backlog has no act_now item, replace the "Act now" heading and
     table with "### Start this week (Investigate, ranked)": one sentence saying no item met the
     Act-now bar this cycle and which disqualifiers fired, then the Investigate items ordered
     prerequisites first (an item another item `depends_on`, marked "do first: unblocks <id>"),
     then confidence (desc), then numeric sizing.value before pilot/null, then backlog order —
     top 5 (the action-plan skill's "Zero Act-now" rule). Each row's step is the confirming step, not
     the lever. Skip the "Act-now — per-opportunity detail" section; the Investigate detail
     blocks below still cover every item.

| # | Opportunity | query_id | Confirming step this week | Signal (verified) | Confidence | Notebook |
|---|---|---|---|---|:---:|---|
| 1 | … | … | <measurement / owner confirmation> | <metric or DBU> | n/10 | notebooks/<slug>.py |
-->

### Investigate

| # | Opportunity | query_id | Row (workspace · attribution) | Signal | Step needed | Confidence |
|---|---|---|---|---|---|:---:|
| 1 | … | … | ws-<id> · <partial attribution> | … DBU | … | n/10 |

### Not now

| # | Opportunity | query_id | Row | Signal | Reason cut |
|---|---|---|---|---|---|
| 1 | … | … | ws-<id> | … DBU | … |

---

## Act-now — per-opportunity detail

<!-- Repeat this block for each Act-now item. The notebook filename links the confirming
     analysis so a reader can reproduce the finding. -->

### Act <n>: <Opportunity name>

**Tier:** Act now  
**Confidence:** <n>/10 (<rubric breakdown from verify.md, e.g. V3 R2 A2 L1 S1 C0>)  
**Recoverable DBU (est.):** <figure> — <arithmetic, e.g. "N instances × M DBU/instance">  
**Performance impact:** <latency / queueing / failure-rate change and its evidence — or "none (cost-only)".
If the fix adds DBU at peak (e.g. more min clusters to cut queueing), say so and show the added DBU
alongside any recoverable DBU; a performance-led item may have no recoverable DBU at all.>  
**Notebook:** [<opportunity-slug>.py](notebooks/<opportunity-slug>.py)

#### Evidence

| Field | Value |
|---|---|
| query_id | <pack-id or live query ref> |
| workspace_id | <ws-id> |
| Attribution | <endpoint / job / instance / cluster — push as deep as the data allows> |
| Verified figure | <the real number from system.billing.usage, e.g. 2,940 DBU/month> |
| Verification method | live — `query sql --warehouse-id <wh-id>` / system-table only |
| Lookback window | <date range> |

#### Recoverable-DBU arithmetic

```
<factor 1>: <value>  (source: <query_id>, row: <field=value>)
<factor 2>: <value>  (source: <query_id>, row: <field=value>)
recoverable = <factor 1> × <factor 2> = <result> DBU  (list-price estimate)
```

Bound: <audited population — not a projected rate. E.g. "47 confirmed-idle instances as of <date>.">

#### Reconciliation

<!-- Record any discrepancy between the pack-floor figure and the live-verified figure,
     and explain it. If they agree, say so. Omitting this section is not allowed. -->
Pack-floor: <figure>. Live-verified: <figure>. <One clause on why they agree or differ,
e.g. "pack capped at 50 rows; live query returned 47 matching instances.">

#### Attribution gaps

<!-- List any instances where attribution could not be fully resolved, and what was done. -->
<"All instances resolved" — or — "3 of 47 instances unresolved (no matching billing row);
excluded from the recoverable estimate. See the Investigate tier for follow-up.">

---

## Investigate — per-opportunity detail

<!-- Repeat this block for each Investigate item. -->

### Investigate <n>: <Opportunity name>

**Tier:** Investigate  
**Confidence:** <n>/10 (<rubric breakdown>)  
**Signal:** <brief — what the data shows, not yet fully attributed>  
**Performance impact:** <as in Act now — or "none (cost-only)">  
**Sizing:** <bounded DBU estimate — or "unbounded — measure via pilot" when the population or effect
size can't be bounded from the data; say what the pilot would measure>  
**Notebook:** [<opportunity-slug>.py](notebooks/<opportunity-slug>.py)

#### Evidence

| Field | Value |
|---|---|
| query_id | <pack-id or live query ref> |
| workspace_id | <ws-id> |
| Attribution | <what is resolved so far> |
| Signal figure | <the real number — labeled as unconfirmed if not yet reconciled> |
| Verification method | <live / system-table only> |

#### Confirming step required

<!-- One precise action that would move this to Act now. Not a hand-wave. -->
<E.g. "Join billing rows against the endpoint inventory to resolve endpoint_name for the
3 unattributed VS endpoints. Query is in the linked notebook.">

---

## Not-now — reasons

<!-- One entry per Not-now item. Every surfaced finding is disclosed; nothing is silently dropped. -->

### Not now <n>: <Opportunity name>

**Tier:** Not now  
**Signal:** <the raw figure the scan surfaced>  
**Reason cut:** <one clause — e.g. "below materiality threshold (<500 DBU recoverable)",
"already remediated per cluster event log", "externally blocked — cost owner is a
different team with no current engagement">

<!-- No notebook needed for Not-now items unless the reason requires a supporting query. -->
```
