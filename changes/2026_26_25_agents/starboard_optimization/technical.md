# Starboard — Optimize & Simplify: Technical Design (top picks)

> Architecture sketches for the highest-ranked opportunities. Research only.
> Anchored to the existing hexagonal design and the declarative pack model.

## 0. Grounding: the two extension seams

1. **Declarative pack seam.** A data source = a `QueryPack` of `SystemQuery` dataclasses
   (`packages/starboard-core/starboard_core/domain/models/discovery/query.py:69-128`):
   ```
   SystemQuery(query_id, name, description, sql_template, required_tables: tuple[str,...],
               domain, required=True, lookback_override, max_lookback_days, output_columns,
               discovery_mode, category, metadata)
   QueryPack(pack_id, domain, name, description, queries: tuple[SystemQuery,...],
             gating_products: frozenset[str])
   ```
   Registered in `create_default_registry()` and routed by product in
   `PRODUCT_TO_DOMAIN_PACKS` / `ALWAYS_RUN_PACKS` (`discovery/query_packs/registry.py:17-61,190+`).
   **Adding a pack touches 3 places only:** new `*_pack.py`, an import in `create_default_registry`,
   and (optionally) a product route. No engine change.

2. **Port/adapter seam.** Hexagonal layering (`domain → adapters → agents → app → infra → tools`)
   means new backends bind as adapters behind a Protocol. The log parser already demonstrates this
   with `log_parser/loaders/protocols.py` (loader port) + concrete `dbfs/s3/https/json/local_file`
   loaders.

---

## 1. New system-table packs (N1, N2, N5 shown)

### 1.1 Predictive Optimization pack (N1)
```
# discovery/query_packs/predictive_optimization.py
PREDICTIVE_OPTIMIZATION_PACK = QueryPack(
  pack_id="predictive_optimization", domain="storage", name="Predictive Optimization",
  gating_products=frozenset({"PREDICTIVE_OPTIMIZATION"}),
  queries=(
    SystemQuery(
      query_id="PO-01", name="PO operations & bytes reclaimed",
      required_tables=("system.storage.predictive_optimization_operations_history",),
      sql_template="""
        SELECT operation_type, catalog_name, schema_name,
               COUNT(*) ops, SUM(usage_bytes) bytes, SUM(operation_metrics.number_of_files) files
        FROM system.storage.predictive_optimization_operations_history
        WHERE start_time >= NOW() - INTERVAL {lookback_days} DAYS
        GROUP BY 1,2,3 ORDER BY bytes DESC LIMIT {result_limit}""",
      category=QueryCategory.PROFILE, required=False,  # Preview schema
      metadata=QueryMetadata(summary="What PO compacted/clustered/vacuumed and how much",
                             output_hint="rows per operation type")),
  ))
```
Wire: import in `create_default_registry` (`registry.py:196+`); the `PREDICTIVE_OPTIMIZATION` route
(`registry.py:47`) then resolves to a pack that actually reads the PO table (fixes S6).

### 1.2 Data Quality Monitoring pack (N2)
Target `system.data_quality_monitoring.table_results`; queries: failing checks by table, drift
incidents over `{lookback_days}`, freshness violations. Route `DATA_QUALITY_MONITORING`
(`registry.py:45`) here instead of the empty `monitoring` pack.

### 1.3 Compute reliability + right-sizing pack (N5)
`required_tables=("system.compute.instance_events","system.compute.instance_pools",
"system.compute.node_types","system.compute.warehouses")`. Queries: spot-reclaim rate & MTBF from
`instance_events`; idle-pool $ from `instance_pools` × `billing.usage`; oversized nodes by joining
`node_timeline` utilization to `node_types` capacity; warehouse config drift from `warehouses`.

**Degrade-gracefully rule:** set `required=False` for Preview/Beta tables so a missing table marks
the query (not the whole domain) degraded — matches `SystemQuery.required` semantics
(`query.py:79`).

---

## 2. Port interfaces for external-tool reuse

Introduce four thin Protocols in `starboard/tools/` (or `infra/ports/`). Each has an OSS default
adapter (raw SDK) and an internal adapter. Selection via config/feature flag + workspace profile.

### 2.1 LogRetrievalPort (I1 — logs-summariser OR raw SDK)
```python
class LogRetrievalPort(Protocol):
    async def fetch(self, ref: LogQuery) -> LogBundle: ...
# ref: {entity: cluster|driver|service, id, time_window<=2h, filters}
```
| Adapter | Backing | Notes |
|---|---|---|
| `SdkDbfsLogAdapter` (OSS default) | `databricks-v2` dbfs / SDK / existing `log_parser/loaders/dbfs.py` | cluster log delivery paths |
| `LogsSummariserAdapter` (internal) | `mcp__logs-summariser__analyse_logs` | needs `kube_context {env}-{cloud}-{region}`, ≤2h window; returns summarized logs |

Output `LogBundle` feeds `tools/domain/diagnostic/evidence_extractor.py` →
`root_cause_synthesizer.py`. This reuses the parser/diagnostic substrate unchanged.

### 2.2 DiagnosticBackendPort (I2 — dbr-doctor OR native)
```python
class DiagnosticBackendPort(Protocol):
    def classify(self, pasted: str) -> list[Candidate]: ...      # id/URL/ticket
    async def analyze(self, c: Candidate) -> DiagnosticResult: ...
```
| Adapter | Flow |
|---|---|
| `NativeDiagnosticAdapter` (OSS) | existing extractors + parser |
| `DbrDoctorAdapter` (internal) | `detect_input` → `run_workflow(generic_data_slice / smart_input_extraction)` → workflow writes Delta to `main.eng_dp_debug_tools` → read back via `databricks-v2` SQL (push aggregation into SQL) → hand rows to Starboard `root_cause_synthesizer` |

Analysis types map cleanly to Starboard domains: `dbr_cluster`→ClusterAgent, `qpl_query`/`dbsql`→
QueryAgent, `job`→JobAgent, `notebook`→(new), `workspace`→AnalyticsAgent. dbr-doctor also exposes
`knowledge://semantic-layer/entities/*` and `knowledge://variables/*` catalogs to pick slice specs.

### 2.3 NLQueryPort (I5 — Genie OR native analytics_sql)
```python
class NLQueryPort(Protocol):
    async def ask(self, question: str, ctx: WorkspaceCtx) -> NLAnswer: ...
```
| Adapter | Backing |
|---|---|
| `AnalyticsSqlAdapter` (OSS) | existing `tools/domain/analytics_sql/llm_sql_generator.py` |
| `GenieAdapter` (internal/curated) | `databricks-v2:ask_genie` / `genie-rooms` when a room fits the domain |

Routing: prefer Genie when a curated room maps to the question domain; else native LLM-SQL. Cache
via `query_result_cache`.

### 2.4 FleetSqlPort / namespace-rewrite adapter (I4 — centralized system tables)
Because packs carry `required_tables` and `sql_template`, a rewrite adapter can retarget every pack
without editing packs:
```python
def to_centralized(sql: str, account_name: str) -> str:
    # system.{schema}.{table} -> main.centralized_system_tables.{schema}_{table}
    # inject: WITH workspace_ids AS (SELECT DISTINCT workspace_id
    #           FROM <mapping> WHERE name = :account_name)
    # add workspace_id IN (SELECT * FROM workspace_ids) per table
    # dedup billing_list_prices (cluster by account_id); parameterize time ranges
```
Rules mirror the `centralized-system-tables-translator` skill (namespace map, per-table workspace
filter, `billing_list_prices` dedup + `account_id` join, `:time_range` params, optional discount
CTE). Implement as a `QueryExecutor` decorator selected when running in fleet mode; single-workspace
path unchanged. Tables without centralized equivalents (e.g. some `system.access.*`) flagged/skipped.

---

## 3. Discovery result caching (R4/S4)

Insert the existing `tools/services/query_result_cache.py` between `discovery/executor.py` and the
SQL client. Cache key = `hash(sql_template + resolved_params + workspace_id + lookback)`; TTL by
table volatility (billing daily grain → hours; config tables → minutes). Because packs share hot
tables (`system.billing.usage` 69 refs, `system.query.history` 16, `system.lakeflow.jobs` 16),
dedupe identical scans **within a run** first (biggest win), then across runs.

Flow: `executor` asks cache → miss → run SQL via warehouse → store. Add a `--no-cache` and a
freshness floor for time-sensitive queries.

---

## 4. Simplification refactors

| Change | Target | Approach |
|---|---|---|
| One chart builder (S2/R3) | `tools/services/chart_renderer.py` + `direct_chart_builder.py` | Extract one `render(result, hint)->Chart`; delete the redundant path; keep `chart_config_validator` |
| One intent classifier (S3) | `services/intent/intent_classifier.py` + `tools/domain/analytics_sql/intent_classifier.py` | Promote one, adapter-wrap the other's call sites |
| Skills layout (S1) | `packages/starboard-skills/skills/starboard/starboard-*` (only copy; the `starboard/starboard/skills/` copy no longer exists) | Flatten redundant double-`starboard` nesting; ensure server build references the skills package, never a re-copied duplicate |
| Warehouse resolution (R6/S7) | `notebooks.py` ↔ `adapters/.../services` + `warehouse_data_provider.py` | One resolution core; sync + async facades |
| Dep slimming (S5) | `packages/*/pyproject.toml` | Standardize on polars in core; audit pandas/matplotlib actual usage |

## 5. Integration flow (end-to-end example: "why did job X fail last night", internal deploy)

```
User → MCP diagnostic_agent tool
  → DiagnosticBackendPort.classify("<job run URL>")            # dbr-doctor detect_input
  → DiagnosticBackendPort.analyze(job candidate)              # dbr-doctor run_workflow → Delta
  → databricks-v2 SQL reads slice (aggregated)                # small result
  → if crash suspected: LogRetrievalPort.fetch(driver, <=2h)  # logs-summariser
  → log_parser + evidence_extractor + pattern_matcher/registry
  → root_cause_synthesizer → response_framer
  → chart_renderer (optional) / Lakeview publish (optional)
```
Every internal backend is an adapter; the OSS path swaps in native extractors + SDK/DBFS logs with
no change to the agent or synthesizer.
