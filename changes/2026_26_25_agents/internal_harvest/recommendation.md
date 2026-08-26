# Harvest Recommendation — Ranked Roadmap

> Which internal IP to harvest first, ranked by **value × feasibility × fidelity**, with sequencing,
> quick-wins vs strategic bets, and governance flags for anything that cannot ship externally.
> Confidence: **[C]** confirmed · **[I]** inferred · **[U]** uncertain.

## Scoring

Each candidate scored 1–5 on **Value** (customer impact + differentiation), **Feasibility** (inverse of
LOE/complexity given Starboard already owns the vehicles), **Fidelity** (how faithful the public-data
version is). Rank = Value × Feasibility × Fidelity (max 125). Scores are judgment calls from the evidence,
not measurements. [I]

| Rank | Harvest | Value | Feasibility | Fidelity | Score | Class |
|---|---|---|---|---|---|---|
| 1 | **logfood metric framings → warehouse/finops/compute packs** (Src 3) | 4 | 5 | 4 | **80** | Quick win |
| 2 | **elt-review finding schema + scorer + checklists → Workload-Review seed** (Src 5) | 4 | 5 | 4 | **80** | Quick win |
| 3 | **Isaac /review methodology → Workload Review engine** (Src 4) | 5 | 3 | 4 | **60** | Strategic (flagship) |
| 4 | **logs-summariser filter taxonomy + triage prompt → log-triage** (Src 2) | 4 | 4 | 3 | **48** | Quick-ish win |
| 5 | **dbr-doctor trace-RCA + evidence tags + query-diff** (Src 1) | 5 | 2 | 3 | **30** | Strategic |
| 6 | **perf/troubleshooting/sizing/RCA reference files** (Src 6) | 3 | 5 | 3 | **45** | Continuous fill-in |

> Note #6 scores 45 but is spread across many tiny, independent content tasks — treat as ongoing backfill
> that rides alongside 1–5 rather than a single scheduled item.

## Ranked rationale

1. **logfood metric framings (Src 3) — do first.** Highest feasibility × fidelity: the internal DBSQL/cost
   queries hit `main.centralized_system_tables.*`, the confirmed cross-account **mirror of public
   `system.*`** (per `centralized-system-tables-translator`), and Starboard *already* queries
   `system.query.history` (`discovery/query_packs/query_performance.py:16-78`). The harvest is the missing
   **categorical framings** — utilization bands, auto-stop waste, query-load buckets, client-app mix,
   T7/T28/T91 windows — which are pure content into existing packs/prompts. Immediate, visible customer value
   (warehouse right-sizing, cost waste), near-lossless. [C]

2. **elt-review schema + scorer + checklists (Src 5) — do first, in parallel.** Already public and open; the
   `severity × impact / effort → bucket` scorer and the 12 per-domain checklists are drop-in seed content
   for both the Workload-Review finding contract and its rule registry. De-risks #3 by giving it real content
   before the engine exists. [C]

3. **Isaac /review → Workload Review (Src 4) — the strategic flagship.** Highest value and the clearest
   differentiator ("review my workspace the way Databricks reviews code"), but medium feasibility: it needs a
   new `rules/` YAML registry, a **validator-council verify-pass**, and an **action-rate feedback loop**, all
   built on top of the existing `patterns/registry.py`/`schema.py` and the 7 domain agents. Sequence it
   *after* 1+2 so the rule registry and finding schema are already populated. [C on method, I on design]

4. **logs-summariser triage (Src 2) — quick-ish win.** The filter-predicate schema + analysis-question prompt
   harvest is lossless and reuses `spark_event_log_extractor.py` + `large_artifact_processor.py`. Feasibility
   is capped by needing a log4j/event-log parse front end and depends on the customer having **log delivery**
   configured. Medium fidelity (file-scan, not indexed). [C/I]

5. **dbr-doctor trace-RCA + query-diff (Src 1) — strategic, later.** Highest ceiling (expert cross-dataset
   RCA), but lowest feasibility/fidelity: rebuilding a semantic layer + evidence-tag taxonomy is real work,
   and the public data lacks the JVM/GC/Hydra series and HMR stack corpus that make the internal RCA strong.
   Start with the **evidence-tag model + A/B query-diff** (both reuse existing extractors) and defer the full
   semantic layer. [C/I]

6. **Reference-file harvest (Src 6) — continuous.** Cheap, independent content tasks (decision trees,
   anti-patterns, sizing tables, RCA doc template, the `system.*` mapping) that compound value across every
   other capability. Backfill continuously. [C/I]

## Sequencing

```
Phase 0 (enabling, ~days): adopt the centralized→public system-table mapping (Src 6) as a reference asset;
                            define the shared Finding schema (harvest from Src 5 scorer).
Phase 1 (quick wins, parallel):  #1 logfood framings into warehouse/finops/compute packs+prompts
                                 #2 elt-review checklists+scorer seed the rule registry + finding contract
Phase 2 (flagship):              #3 Workload-Review engine (rules registry + severity gate + validator
                                 council + report), consuming Phase-1 content as its first rule sets
Phase 3 (depth):                 #4 log-triage tool;  #5 trace-RCA evidence tags + query-diff
Continuous:                      #6 reference-file backfill feeding all of the above
```

**Dependency notes.** Phase-1 #2 produces the finding schema and seed rules that Phase-2 #3 consumes — build
#2 first within Phase 1. #4 and #5 are independent of #3 and can slot in whenever capacity allows. Everything
lands in existing vehicles (packs / prompts / YAML registry), so phases can overlap. [I]

## Quick wins vs strategic bets

| Quick wins (ship value in days–weeks, high fidelity, low risk) | Strategic bets (weeks–months, differentiating, needs new engine) |
|---|---|
| #1 logfood metric framings → packs/prompts | #3 Workload Review (validator council, action-rate loop) |
| #2 elt-review scorer + checklists → finding schema + seed rules | #5 dbr-doctor semantic layer + full trace-RCA |
| #4 log-triage prompt + filter schema (if log delivery present) | |
| #6 reference-file backfill | |

## Governance / IP-shipping flags — what CANNOT ship externally

The point of this topic is that we ship **methodology on public data**, never internal data or internal-only
assets. Explicit red lines: [C unless noted]

1. **Internal data namespaces stay internal.** `main.eng_dp_debug_tools`, `main.eng_time_series_metrics`,
   `main.eng_lumberjack`, `main.eng_qpl`, `main.centralized_system_tables.*`, `main.fin_live_gold`,
   `main.gtm_gold/silver`, `main.sfdc_bronze`, `main.certified.workspaces_latest`, the logfood workspace, and
   the ClickHouse log store — **never** referenced in shipped code, prompts, or query packs. Only public
   `system.*` / customer log delivery / public REST/SDK. Port every harvested query through the
   centralized→public mapping and **grep the shipped artifacts for `eng_`, `centralized_system_tables`,
   `fin_live_gold`, `logfood`, `adb-2548836972759138`** before release. [C]

2. **Cross-account / fleet data is internal-only.** logs-summariser's cross-service `kube_context` fleet
   view, dbr-doctor's cross-account observation corpus, and HMR stack-hash clustering are built on
   multi-tenant internal telemetry. The customer-facing versions are **single-workspace/single-customer** by
   construction. Do not attempt to reproduce fleet aggregates. [C]

3. **Finance-grade $ must be labeled as estimates.** Public `system.billing` yields **list-price × usage**,
   not contract net-of-discount rates (`fin_live_gold.paid_usage_metering`). Any $ figure Starboard emits
   must be labeled a **list-price estimate**, never "finance-grade" or contract-accurate — an accuracy *and*
   a commercial-sensitivity concern. [C]

4. **Internal thresholds / expert heuristics — review before shipping.** Specific numeric thresholds baked
   into internal dashboards (utilization bands, config-exposure checks, SAFEr overrides) and internal
   go/ reference links embedded in `/review` rule `source` fields may encode non-public product knowledge.
   Ship *generic, defensible* thresholds (documented rationale) and **strip internal `go/` links and team
   keys** from harvested rule content. [I]

5. **Prompt provenance.** Harvested prompt text (triage questions, `additional_instructions`) should be
   **paraphrased/reauthored**, not copied verbatim from internal tools, to avoid shipping internal wording or
   references. The *pattern* is the asset, not the literal string. [I]

6. **`hmr_stack_hash` fingerprinting** relies on internal runtime stack normalization and a private corpus —
   treat as **internal-only**; the public analog is log4j-stack fingerprinting from delivered logs, which
   should be built fresh rather than ported. [I]

7. **[U] Model-council specifics.** Isaac reviewflow names internal model ids (`system.ai.claude-opus-4-8`,
   `claude-haiku-4-5`) and a `devtools/ai/reviewflow` validator implementation. Harvest the *shape* (ensemble
   + independent validator), not internal model routing or code; confirm which model ids are available to a
   customer-facing Starboard deployment before wiring the council. [U]
