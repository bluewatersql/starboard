# Starboard — Optimize & Simplify: Ranked Recommendations

> Ranked by value/effort. Grounded in `opportunities.md`. Research only.

## Ranking principle

Starboard's declarative query-pack substrate makes **new system-table coverage nearly free**, and
its parser/diagnostic substrate makes **internal-telemetry integration high-leverage but heavier**.
So the fastest ROI is: (1) close pack gaps that are already half-wired, (2) collapse duplication,
then (3) invest in the port-based integrations that turn Starboard from single-workspace OSS into a
fleet-scale, internally-super-powered analyzer.

## Tier 1 — Quick wins (days each, high confidence)

| Rank | Item | Why now | LOE |
|---|---|---|---|
| 1 | **N1 Predictive Optimization pack** + **S6 route fix** | `PREDICTIVE_OPTIMIZATION` already routes to a pack (`registry.py:47`) but reads no PO table. One new pack fixes a broken promise and surfaces real $ savings. | S |
| 2 | **N2 Data Quality Monitoring pack** | A `monitoring` pack object already exists but never queries `system.data_quality_monitoring.table_results`. Wire it. | S–M |
| 3 | **S2/S3/R3 merge chart builders + intent classifiers** | Two chart builders and two intent classifiers are pure duplication; merging reduces surface with no behavior change. | S–M |
| 4 | **N6/N7/N9/N11 small packs** (Assistant adoption, AI external spend, alert reliability, tag governance) | Each is a single-table pack on the proven `SystemQuery` model. | S each |
| 5 | **R6/S7 dedupe warehouse resolution** (`notebooks.py` ↔ adapters) | New uncommitted code already duplicates async logic; unify before it spreads. | S |

## Tier 2 — Strategic, near-term (weeks)

| Rank | Item | Why | LOE |
|---|---|---|---|
| 6 | **N5 Compute reliability + right-sizing pack** | `instance_events`/`instance_pools`/`node_types`/`warehouses` unlock reliability + cost right-sizing — top customer ask. | M |
| 7 | **R4/S4 discovery result caching** | `system.billing.usage` scanned 69×; caching cuts warehouse cost & latency materially. | M |
| 8 | **I4 centralized-tables fleet mode** | A namespace-rewrite adapter retargets ALL packs cross-account with near-zero pack edits — turns Starboard into a fleet tool. | M |
| 9 | **S1 skills layout tidy-up** | Cross-dir duplication already resolved; remaining: nested `skills/starboard/starboard-*` redundancy + confirm the `-workspace` skill's presence. Lower priority than brief implied. | S |
| 10 | **N3/N4 data classification + column lineage** | PII coverage + column-level impact; pairs well and reuses `uc/` services. | M |

## Tier 3 — Strategic bets (internal-deployment, larger)

| Rank | Item | Why | LOE | FEEDBACK NOTES |
|---|---|---|---|---|
| 11 | **I2 dbr-doctor as diagnostic backend** | Reuses a production RCA engine (semantic observation layer) instead of rebuilding — biggest capability jump for internal users. | M–L | |
| 12 | **I3 LogFood deep telemetry packs** | JVM/GC/executor-loss + finance-grade $ beyond public tables. | M | |
| 13 | **I1 logs-summariser log-retrieval port** | Kernel/OOM evidence for cluster RCA. | M | |
| 14 | **R1 package log parser standalone** | Broadens reuse (notebooks, CI, Isaac). | M | |
| 15 | **I7 Isaac packaging** + **I5/I6 Genie & ops ports** | Native internal-agent distribution + NL front door + Lakeview publish. | M | |
| 16 | **S5 dependency slimming** (pandas/polars, matplotlib) | Lower footprint; do opportunistically. | M | I'd push this higher given the vulnerability/dependency issues that have been happening lately. |

## Suggested sequencing

1. **Sprint A (quick wins):** N1+S6, N2, S2/S3, R6/S7, N6/N7/N9/N11. Ships visible new value + shrinks surface.
2. **Sprint B (substrate):** introduce the **port interfaces** (LogRetrievalPort, DiagnosticBackendPort, NLQueryPort, FleetSQL/namespace-rewrite) — see technical.md — even before all backends exist. Land R4/S4 caching and N5.
3. **Sprint C (fleet + internal):** I4 fleet mode; then internal-only backends I2/I3/I1 behind feature flags/profiles.
4. **Continuous:** S1 skills consolidation, N3/N4, R1 packaging, S5 deps.

## Quick wins vs strategic bets (one-liner)

- **Quick wins:** N1, S6, N2, chart/intent merges, small single-table packs, warehouse-resolution dedupe.
- **Strategic bets:** dbr-doctor backend (I2), fleet mode (I4), LogFood telemetry (I3), log-parser packaging (R1), Isaac distribution (I7).

## Guardrails

- Many gap tables are **Preview/Beta** — gate new packs on schema availability and degrade gracefully
  (`SystemQuery.required=False` for volatile tables).
- Internal integrations (I1–I3) are **internal-only** — must sit behind adapters so OSS builds keep working.
- Fleet mode (I4) crosses trust boundaries (cross-account data) — needs auth/governance review.
