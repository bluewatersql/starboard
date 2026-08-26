# Starboard — Optimize & Simplify: Opportunity Catalog

> "Art of the possible" envisioning study. Research/brainstorming only — no code changes.
> Evidence base: commit `b927dfaa` (starboard 0.1.1) + `_grounding_brief.md`.
> Databricks surfaces verified against current docs (Aug 2026). Internal tool claims grounded in
> the skill/MCP definitions available in this environment.
> **This is a map of possibilities (matches AND gaps), not a limit on ideas.**

## Legend

- **LOE**: S (<1 wk / <5 files), M (1–3 wk), L (1–2 mo), XL (quarter+).
- **Match** = capability already exists and can be reused/extended. **Gap** = not present today.
- File citations are `path:line`. Databricks doc URLs given inline.

---

## 0. Executive orientation — what Starboard already is

Starboard is a hexagonal, multi-agent Databricks analysis platform: `starboard-core` (pure
domain incl. a full Spark/Photon **event-log parser**), `starboard` (MCP server + CLI + SDK +
7 domain agents + ~45 tools), `starboard-skills` (dual-mode Claude skills). Its two "engines":

1. **Discovery engine** — runs ~20 declarative **query packs** (`SystemQuery`/`QueryPack`
   dataclasses, `packages/starboard-core/starboard_core/domain/models/discovery/query.py:69-128`)
   over Databricks **system tables**, gated by active products
   (`discovery/query_packs/registry.py:17-61`).
2. **Diagnostic/agent engine** — domain analyzers + a Spark event-log parser + query-profile
   extractors that do root-cause analysis on jobs/queries/clusters.

The optimization thesis: Starboard has a **strong declarative-query substrate and a strong
log/artifact-parsing substrate** that are under-exploited. Most high-value opportunities are
(a) filling system-table gaps in the pack layer, (b) exposing the parser/diagnostic substrate as
reusable ports that internal Databricks telemetry can plug into, and (c) collapsing duplicated
surfaces (skills ×2 dirs, chart builders ×2, intent classifiers ×2, pandas+polars).

---

## 1. Match-vs-Gap Map (headline table)

### 1a. System-table coverage (verified against current Databricks system tables, Aug 2026)

Coverage derived from `grep 'system\.'` across `discovery/query_packs/*.py`. Distinct tables
actually queried (with usage counts): `system.billing.usage` (69), `system.lakeflow.pipelines`
(19), `system.access.audit` (17), `system.query.history` (16), `system.lakeflow.jobs` (16),
`system.mlflow.runs_latest` (10), `system.lakeflow.job_run_timeline` (8),
`system.compute.clusters` (8), `system.mlflow.experiments_latest` (7),
`system.lakeflow.pipeline_update_timeline` (7), `system.lakeflow.job_task_run_timeline` (6),
`system.compute.node_timeline` (6), `system.billing.list_prices` (6), `system.ai_gateway.usage`
(6), `system.access.workspaces_latest` (4), `system.access.table_lineage` (4),
`system.serving.served_entities` (2), `system.serving.endpoint_usage` (2),
`system.information_schema.tables` (2), `system.compute.warehouse_events` (2), plus
`system.sharing.materialization_history` (product_surfaces.py).

| System table (exists per docs) | Schema status | Covered by a pack? | Gap / opportunity |
|---|---|---|---|
| `system.billing.usage`, `list_prices` | GA | ✅ heavy | — |
| `system.query.history` | Preview | ✅ | — (but see enrichment ideas §3) |
| `system.lakeflow.jobs / job_run_timeline / job_task_run_timeline / pipelines / pipeline_update_timeline` | GA/Preview | ✅ | — |
| `system.compute.clusters / node_timeline / warehouse_events` | GA | ✅ | — |
| `system.compute.warehouses` (config history) | GA | ❌ | **GAP** — only `warehouse_events`; warehouse *config drift* not tracked |
| `system.compute.node_types` | GA | ❌ | **GAP** — sizing/right-sizing reference table unused |
| `system.compute.instance_pools` | Preview | ❌ | **GAP** — pool efficiency/idle analysis |
| `system.compute.instance_events` | Preview | ❌ | **GAP** — spot reclaim / instance transitions for reliability |
| `system.access.audit` | Preview | ✅ | — |
| `system.access.table_lineage` | GA | ✅ | — |
| `system.access.column_lineage` | GA | ❌ | **GAP** — column-level impact analysis / PII propagation |
| `system.access.assistant_events` | Preview | ❌ | **GAP** — Genie/Assistant adoption + NL-query telemetry |
| `system.access.clean_room_events` | Preview | ❌ | **GAP** — clean-room collaboration usage |
| `system.access.inbound_network / outbound_network` | Preview | ❌ | **GAP** — network-policy denials (NETWORKING product maps to `governance` pack but no network table is queried) |
| `system.serving.endpoint_usage / served_entities` | Preview | ✅ | — |
| `system.ai_gateway.usage` | Beta | ✅ | — |
| `system.ai_gateway.external_model_spend` | Beta | ❌ | **GAP** — external-model $ spend attribution |
| `system.mlflow.experiments_latest / runs_latest` | Preview | ✅ | — |
| `system.mlflow.run_metrics_history` | Preview | ❌ | **GAP** — training/eval metric drift over time |
| `system.storage.predictive_optimization_operations_history` | Preview | ❌ | **GAP** — PREDICTIVE_OPTIMIZATION product maps to `governance` but PO table never queried |
| `system.storage.table_auto_upgrade_operations_history` | Preview | ❌ | **GAP** — managed-table upgrade tracking |
| `system.data_quality_monitoring.table_results` | Preview | ❌ | **GAP** — a `monitoring` pack exists (product_surfaces.py) but does NOT query this table |
| `system.data_classification.results` | Preview | ❌ | **GAP** — DATA_CLASSIFICATION maps to `governance` but table not queried |
| `system.alert.alerts / alert_evaluation_history` | Preview | ❌ | **GAP** — SQL alert reliability / noisy-alert analysis |
| `system.lakeflow.zerobus_stream / zerobus_ingest` | Beta | ❌ | **GAP** — streaming ingest volume/throughput |
| `system.marketplace.listing_funnel_events / listing_access_events` | Preview | ❌ | **GAP** — marketplace provider analytics |
| `system.tags.governed_tags` | Beta | ❌ | **GAP** — cost-attribution tag governance |
| `system.sharing.materialization_history` | GA | ✅ | — |
| `system.replication.states` | Private Preview | ❌ | **GAP** — DR/replication health |
| `system.information_schema.*` | GA | ✅ partial (`tables`) | Columns/constraints/routines under-used |

**Key structural finding:** four product→pack routes are **mapped-but-not-implemented** — the
product string routes to a pack that never reads the relevant system table:
`PREDICTIVE_OPTIMIZATION`, `DATA_CLASSIFICATION`, `DATA_QUALITY_MONITORING`, `NETWORKING`
(`registry.py:44-51`). These are the cheapest, highest-confidence new-data wins.

### 1b. Internal tool / skill integration map (this environment)

| Internal tool (this env) | Data it unlocks | Starboard capability it augments | Match/Gap |
|---|---|---|---|
| `logs-summariser` MCP (ClickHouse) | Raw service/cluster logs by kube_context, ≤2h window | Cluster/driver crash RCA beyond public system tables | **Gap** (no connector today) |
| `fe-internal-tools:logfood-querier` | `fin_live_gold`, `gtm_gold`, internal eng dashboards (Cluster 360, DBSQL Endpoint) | Finops $ accuracy, cluster JVM/GC telemetry (`eng_time_series_metrics`, `eng_lumberjack`, `eng_dbsql.cluster_metrics_stream`) | **Gap** |
| `dbr-doctor` MCP | Semantic-layer observation tables (`main.eng_dp_debug_tools`), analysis types: dbr_cluster/qpl_query/job/dbsql/hmr_stack_hash/notebook/workspace | Deep cluster/job/query diagnostics; a ready-made RCA backend | **Gap** (huge reuse) |
| `databricks-v2` MCP | `ask_genie`, warehouses, jobs, dashboards, dbfs, parameterized SQL | NL query entry, warehouse/job ops, dbfs artifact fetch | **Partial** (SDK used directly; Genie not wired) |
| `centralized-system-tables-translator` | `main.centralized_system_tables.*` cross-account | Multi-workspace/fleet analysis of the SAME packs | **Gap** (single-workspace only today) |
| `fe-internal-tools:genie-rooms` | Curated GTM/industry Genie rooms | NL business-context enrichment | **Gap** |
| `fe-databricks-tools:databricks-lineage / lakeview-dashboard(-analyzer)` | Lineage graph, Lakeview build/analyze | UC lineage service; publish findings as dashboards | **Partial/Gap** |

---

## 2. Reuse — repackage existing components instead of rebuilding

> Detailed file:line inventory of the tools/log-parser layer is folded in below.

### R1. Spark/Photon event-log parser as a standalone reusable engine
**Description:** `starboard-core/.../log_parser/` is a self-contained, I/O-free-at-core parser with
a **pluggable loader/adapter port** (`loaders/`: `dbfs.py`, `s3.py`, `https.py`, `json.py`,
`local_file.py`, `protocols.py`; cloud adapter `adapters/cloud/s3.py`) and a `computers/`
pipeline (job/stage/task/executor/sql/accum) producing structured metrics. It is already the
crown-jewel reuse asset: source-agnostic ingestion + rich parsed output.
**Reuse moves:** (a) publish it as its own installable (`starboard-logparse`) consumable by
notebooks, CI, other agents; (b) add loaders for new sources (internal ClickHouse, dbr-doctor
Delta tables) behind the existing `protocols.py` port — no core change.
**Strengths:** hexagonal, testable, already multi-source. **Weaknesses:** tightly modeled to
Spark event-log schema; JVM/infra metrics (GC, heap) not in scope (that's LogFood territory).
**Trade-offs:** packaging overhead vs. adoption. **Complexity:** Low–Med. **LOE:** M.

### R2. Diagnostic extractors as a reusable "evidence" toolkit
**Description:** `tools/domain/diagnostic/` holds bespoke-but-generic extractors:
`spark_event_log_extractor/explorer`, `query_profile_extractor/explorer`, `exit_code_triager`,
`evidence_extractor`, `pattern_matcher` + `patterns/registry.py` (declarative pattern catalog),
`root_cause_synthesizer`, `large_artifact_processor`, `artifact_explorer`/`_detector`/`_normalizer`.
**Reuse moves:** expose `pattern_matcher` + `patterns/registry` as a **public, extensible RCA
rule catalog** (like dbr-doctor's `hmr_stack_hash`); let external log sources feed
`evidence_extractor`. **Strengths:** pattern registry is data-driven → easy to grow.
**Complexity:** Med. **LOE:** M.

### R3. Chart rendering as a generic viz service
**Description:** `tools/services/chart_renderer.py` + `direct_chart_builder.py` +
`chart_config_validator.py` render analysis results to charts. Candidate to be a single generic
"result → chart" service reused by every agent and by published dashboards.
**Reuse move:** consolidate the two builders (see S2) and expose one `render(result, hint)` port.
**Complexity:** Low. **LOE:** S–M.

### R4. `query_result_cache` as cross-cutting cache infra
**Description:** `tools/services/query_result_cache.py` + `cached_data_models.py` +
`analytics_sql/cache_adapter.py`. Already a caching layer for SQL results.
**Reuse move:** promote to a shared cache port used by the discovery engine (packs re-run the
same system-table scans repeatedly) and the MCP layer → big latency/cost win (§4, S4/O-cache).
**Complexity:** Med. **LOE:** M.

### R5. UC lineage/storage/governance services
**Description:** `tools/services/uc/` (`lineage.py`, `storage_analysis.py`, `governance.py`,
`catalog_browser.py`, `table_metadata.py`, `schema_operations.py`).
**Reuse move:** back `lineage.py` optionally with `system.access.column_lineage` (gap §3) and
reuse `table_metadata` for the new data-quality/classification packs. **LOE:** M.

### R6. `warehouse_data_provider` abstraction + `notebooks.py` sync helpers
**Description:** `tools/adapters/warehouse_data_provider.py` abstracts warehouse data access; the
just-added `notebooks.py` (`resolve_warehouse`, `start_warehouse`, `list_serving_endpoints`)
duplicates warehouse-resolution logic already present in async adapters (its own docstring admits
it is a sync "counterpart" of `starboard.adapters.databricks.services`). Reuse = one resolution
core with sync + async facades. **LOE:** S.

---

## 3. New Data Sources / Endpoints / API calls

Each is a new query pack or adapter. All are additive: the `SystemQuery`/`QueryPack` model
(`.../discovery/models/discovery/query.py:69-128`) makes a pack ≈ a tuple of SQL templates +
`required_tables` + product gating. See technical.md for the pack template.

### N1. Predictive Optimization pack (quick win — mapped but unimplemented)
`system.storage.predictive_optimization_operations_history`. Answer: is PO running, what did it
compact/cluster/vacuum, $ saved, tables not benefiting. Docs:
https://docs.databricks.com/aws/en/admin/system-tables/storage . **Value:** high (cost).
**LOE:** S. **Strength:** product route already exists (`registry.py:47`). **Weakness:** Preview schema.

### N2. Data Quality Monitoring / Lakehouse Monitoring pack
`system.data_quality_monitoring.table_results`. The `monitoring` pack exists but doesn't query it.
Answer: failing quality checks, drift incidents, freshness. **LOE:** S–M. **Value:** high.

### N3. Data Classification pack
`system.data_classification.results` — PII/sensitive-column detections, coverage, unclassified
sensitive tables. Pairs with `column_lineage` for PII-propagation. **LOE:** S–M.

### N4. Column-lineage enrichment
`system.access.column_lineage` → column-level impact analysis, PII flow, unused-column pruning.
Augments `uc/lineage.py`. **LOE:** M.

### N5. Compute reliability + right-sizing pack
`system.compute.instance_events` (spot reclaims, transitions), `instance_pools` (idle pool $),
`node_types` (right-sizing reference), `warehouses` (config drift). Answer: reliability incidents,
oversized nodes, pool waste. **LOE:** M. **Value:** high (cost + reliability).

### N6. Genie / Assistant adoption pack
`system.access.assistant_events` — who uses Genie/Assistant, NL-query volume, success. Ties to the
Genie integration (§3 tools). **LOE:** S.

### N7. AI Gateway external-model spend pack
`system.ai_gateway.external_model_spend` — $ per external model/route; complements existing
`ai_gateway.usage`. **LOE:** S.

### N8. MLflow metric-history pack
`system.mlflow.run_metrics_history` — training/eval metric trends & regressions across runs.
**LOE:** S–M.

### N9. Alerting reliability pack
`system.alert.alerts` + `alert_evaluation_history` — noisy/never-firing alerts, flapping. **LOE:** S.

### N10. Networking / security-posture pack
`system.access.inbound_network` + `outbound_network` — denied access attempts, egress blocks
(NETWORKING product route exists, `registry.py:51`, but no table queried). **LOE:** S–M.

### N11. Tag governance pack
`system.tags.governed_tags` — untagged cost centers, tag policy compliance → better chargeback.
**LOE:** S.

### N12. Streaming ingest (Zerobus) & Marketplace & Replication packs
`system.lakeflow.zerobus_*`, `system.marketplace.*`, `system.replication.states`. Niche;
Beta/Private-preview. **LOE:** S each, **Value:** situational.

### N13. REST/SDK-sourced signals (not system tables)
- **Lakeview dashboard API** (`/api/2.0/lakeview/dashboards`, create/publish) — publish Starboard
  findings as a live customer-facing dashboard. Docs: https://docs.databricks.com/api/workspace/lakeview .
- **Genie Conversation API** (`/api/2.0/genie/...`, also `databricks-v2:ask_genie`) — NL front door.
- **Jobs/Runs API + `run output`** — live run failures before system tables settle (system tables lag).
- **Query History API** — sub-minute freshness vs `system.query.history` latency.

---

## 4. Skill & Internal-Tool Integration

Approach for all: introduce a small set of **hexagonal ports** (log-retrieval port, NL-query port,
diagnostic-backend port, fleet-SQL port) so an internal Databricks deployment can bind richer
backends while OSS keeps the raw-SDK path. Details in technical.md.

### I1. `logs-summariser` MCP → LogRetrievalPort backend (cluster/service log RCA)
**Augments:** diagnostic agent's cluster/driver crash analysis, which today is limited to public
`system.compute.*` + parsed event logs. logs-summariser returns summarized ClickHouse logs by
`kube_context`, ≤2h window.
**Integration:** implement a `LogRetrievalPort` with two adapters — raw SDK/DBFS (OSS) and
logs-summariser (internal). Feed results into `evidence_extractor`/`root_cause_synthesizer`.
**Match/Gap:** Gap. **Strength:** unlocks kernel/OOM/GC evidence public tables lack. **Weakness:**
internal-only, 2h window, kube_context required. **LOE:** M.

### I2. `dbr-doctor` MCP → DiagnosticBackendPort (reuse a whole RCA engine)
**Augments:** job/query/cluster diagnostics. dbr-doctor already slices a **semantic observation
layer** (`main.eng_dp_debug_tools`) across dbr_cluster/qpl_query/job/dbsql/notebook/workspace and
writes results to UC Delta tables + exposes `knowledge://` entity/variable catalogs.
**Integration:** DiagnosticAgent gains a `dbr-doctor` backend: `detect_input` to classify a pasted
id/URL, `run_workflow` for the slice, then read the UC result table via `databricks-v2` SQL and
run Starboard's synthesizer on it. **Match/Gap:** Gap (massive reuse — do not rebuild).
**Strength:** production RCA telemetry for free. **Weakness:** internal-only; large tool schemas;
governance (writes Delta). **LOE:** M–L.

### I3. `logfood-querier` internal telemetry → deep cluster/warehouse packs
**Augments:** cluster metrics + warehouse right-sizing beyond public tables.
LogFood exposes `main.eng_time_series_metrics.time_series()` (JVM CPU/heap/GC),
`eng_lumberjack.*_cluster_event_log` (executor loss, crashes), `eng_dbsql.cluster_metrics_stream`
(task-slot utilization), `field_emea_product_usage.dwh_endpoint_t28` (28-day endpoint metrics),
`fin_live_gold.paid_usage_metering` (finance-grade $).
**Integration:** an "internal telemetry" pack variant, gated to `--profile=logfood`, mirroring the
Cluster 360 / DBSQL Endpoint dashboard query patterns. **Match/Gap:** Gap. **Strength:** JVM/GC +
finance-grade dollars Starboard cannot otherwise get. **Weakness:** internal-only, VPN, schema
churn (`gtm_data` deprecated 2/2026). **LOE:** M.

### I4. `centralized-system-tables-translator` → fleet / multi-account mode
**Augments:** all packs. Translator rewrites `system.*` → `main.centralized_system_tables.*` with
workspace-id filtering by Salesforce account. Because Starboard packs are declarative SQL with
`required_tables`, a **namespace-rewrite adapter** can retarget every existing pack to run
cross-account. **Match/Gap:** Gap (multi-workspace is env-var only today per brief). **Strength:**
turns single-workspace tool into a fleet tool with near-zero pack changes. **Weakness:** needs
`account_workspace_mappings`, discount CTE nuances, `billing_list_prices` dedup. **LOE:** M.

### I5. `databricks-v2 ask_genie` / `genie-rooms` → NL query port
**Augments:** AnalyticsAgent + query entry. **Integration:** a `NLQueryPort` that can answer
free-form business questions via Genie when a curated room exists, falling back to Starboard's own
`analytics_sql` LLM-SQL generator. **Match/Gap:** Partial. **LOE:** S–M.

### I6. `databricks-v2` warehouses/jobs/dashboards/dbfs → thin ops + artifact fetch
**Augments:** warehouse start/resolve (dedupe `notebooks.py`), job run fetch, **dbfs artifact
retrieval** feeding the log parser, and **Lakeview publish** of findings. **Match/Gap:** Partial
(SDK used directly). **LOE:** S.

### I7. Isaac (internal AI agent) skill/agent packaging
Starboard's dual-mode skills already degrade to `starboard-helper`. Package the same skills for
Isaac's extension model so Starboard runs natively inside Databricks' internal agent. (Research
Isaac's extension API via Glean.) **Match/Gap:** Gap. **LOE:** M (mostly packaging + research).

---

## 5. Internal Simplification / Optimization

> Detailed file:line duplication findings folded in below.

### S1. Skills layout — de-dup already largely done; fix nested redundancy
**Correction to brief:** the second copy `packages/starboard/starboard/skills/` **does not exist**
in the current tree — only `packages/starboard-skills/skills/starboard/starboard-{analyze,cluster,
diagnostic,discovery,finops,job,query,uc,warehouse}/skill.md` (9 skills) plus
`starboard-skills/starboard_skills/helpers/` (the `starboard-helper` CLI). The cross-directory
duplication the brief flags appears already resolved (likely by recent cleanup `114ac121`). Remaining
tidy-ups: the redundant double-`starboard` nesting (`skills/starboard/starboard-*`) and confirming
no stale copies are re-introduced. **Note:** only 9 skills present; `starboard-analyze` etc. exist,
but there is no `-workspace` skill dir here despite a `starboard-workspace` skill being registered in
this environment — worth confirming. **LOE:** S.

### S2. One chart builder, not two
`chart_renderer.py` vs `direct_chart_builder.py` — consolidate to a single generic renderer (R3).
**LOE:** S.

### S3. One intent classifier, not two
`services/intent/intent_classifier.py` vs `tools/domain/analytics_sql/intent_classifier.py` — unify
the intent/ambiguity logic. **LOE:** S–M.

### S4. Discovery-layer result caching
Packs re-scan `system.billing.usage` (69 refs) and other tables repeatedly per run; wire the
existing `query_result_cache` (R4) into the discovery `executor.py` to dedupe scans within/across
runs. **Value:** latency + warehouse $ . **LOE:** M.

### S5. Dependency slimming: pandas + polars + matplotlib
Deps include BOTH `pandas>=2.3` AND `polars>=1.17` AND `numpy` AND `matplotlib` (plus `openai` and
databricks-sql-connector) across `packages/*/pyproject.toml`. Pick one dataframe lib (core already
favors polars) and confirm matplotlib is actually needed vs a lighter renderer. **LOE:** M.

### S6. Fix mapped-but-unimplemented product routes
`registry.py:44-51` routes PREDICTIVE_OPTIMIZATION/DATA_CLASSIFICATION/DATA_QUALITY_MONITORING/
NETWORKING to packs that don't query the relevant tables. Either implement (N1–N3, N10) or remove
the misleading routes. **LOE:** S (paired with N1–N3).

### S7. Warehouse-resolution duplication (`notebooks.py` vs adapters) — see R6. **LOE:** S.

### S8. MCP tool exposure — `tool_scope` now implemented (brief gap resolved)
**Correction to brief:** `tool_scope` exists with three levels `phase_a`/`phase_b`/`full`
(`mcp/config.py:90-104`, default `phase_b`); `resolve_allowed_tools()` handles `full` = all
non-internal tools (`mcp/tool_bridge.py:117-151`); the server registers tools dynamically from
metadata by scope (`mcp/server.py:353-355`) and registers composite tools from
`COMPOSITE_TOOL_METADATA` (`mcp/composite_tools.py:52`, `server.py:418-423`). So exposing all tools
is now a **config choice** (`tool_scope="full"`), not missing capability. Remaining opportunity is
smaller: decide the right default scope and document it; possibly a per-client scope. **LOE:** S.

---

## 6. Consolidated opportunity table (with LOE + value)

| ID | Opportunity | Group | Value | LOE | Value/Effort |
|---|---|---|---|---|---|
| N1 | Predictive Optimization pack | New data | High | S | ★★★★★ |
| S6 | Fix mapped-but-unimplemented routes | Simplify | Med-High | S | ★★★★★ |
| N2 | Data Quality Monitoring pack | New data | High | S–M | ★★★★☆ |
| N5 | Compute reliability + right-sizing pack | New data | High | M | ★★★★☆ |
| I2 | dbr-doctor diagnostic backend | Integration | High | M–L | ★★★★☆ |
| I4 | Centralized-tables fleet mode | Integration | High | M | ★★★★☆ |
| R4/S4 | Discovery result caching | Reuse/Simplify | Med-High | M | ★★★★☆ |
| N3/N4 | Data classification + column lineage | New data | Med-High | M | ★★★☆☆ |
| I3 | LogFood deep telemetry packs | Integration | High (internal) | M | ★★★☆☆ |
| I1 | logs-summariser log-retrieval port | Integration | Med-High | M | ★★★☆☆ |
| S1 | Collapse duplicated skills dirs | Simplify | Med | S–M | ★★★★☆ |
| S2/S3/R3 | Merge chart builders / intent classifiers | Simplify | Med | S–M | ★★★★☆ |
| R1 | Package log parser standalone | Reuse | Med | M | ★★★☆☆ |
| I5/I6 | Genie NL port + ops/dbfs/Lakeview | Integration | Med | S–M | ★★★☆☆ |
| N6–N12 | Assistant/AI-spend/alerts/net/tags/etc | New data | Med | S each | ★★★☆☆ |
| S5 | Dependency slimming | Simplify | Low-Med | M | ★★☆☆☆ |
| I7 | Isaac packaging | Integration | Strategic | M | ★★☆☆☆ |

(Detailed strengths/weaknesses/trade-offs per item in the sections above; ranked in recommendation.md.)
