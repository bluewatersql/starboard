# Technical Design — Encoding Harvested IP in Starboard

> How each harvested pattern/heuristic/prompt/schema becomes a **native, no-external-store** asset in
> Starboard, reusing the vehicles that already exist. Includes a concrete **"Workload Review"** design
> modeled on Isaac `/review`. Confidence: **[C]** confirmed from repo/source · **[I]** inferred · **[U]** open.

## 0. The vehicles Starboard already has (reuse, don't rebuild)

| Vehicle | Location (repo) | What it already does | What harvest adds |
|---|---|---|---|
| **Pattern registry + YAML loader** | `packages/starboard/starboard/tools/domain/diagnostic/patterns/{registry.py:52-362, schema.py:24-327}`; catalog `.../patterns/catalog/*.yaml` | Fail-fast Pydantic-validated YAML catalog with `severity / category / responsibility / keywords / regex / evidence_checklist / confidence_factors / recommendations`; keyword index; global singleton | A second registry domain (`rules/`) for **workload-review rules**, same loader pattern |
| **Prompt library (versioned)** | `packages/starboard/starboard/prompts/<domain>/v{1,2}.py` (analytics, cluster, diagnostic, discovery, job, query, uc, warehouse, router, shared, visualization) | Per-domain, versioned prompt modules + Jinja env + factories | New harvested prompts as new `vN` (triage, RCA framing, review `additional_instructions`) |
| **Query packs** | `packages/starboard/starboard/discovery/query_packs/*.py` (~17) over `system.*` | Curated `SystemQuery`/`QueryPack` objects (`query_performance.py` already reads spill/cache/prune/duration from `system.query.history`) | New/enriched packs encoding harvested **framings** |
| **Diagnostic extractors** | `tools/domain/diagnostic/{spark_event_log_extractor, query_profile_extractor, evidence_extractor, root_cause_synthesizer, pattern_matcher, sql_analyzer, python_analyzer, artifact_explorer, large_artifact_processor}.py` | Extract evidence + synthesize root cause from logs/profiles | Reused wholesale by log-triage + trace-RCA harvests |
| **Report formatters** | `packages/starboard/starboard/agents/report_formatters/` | Domain report rendering | Workload-Review report layout (from elt-review synthesizer) |
| **7 domain agents + intent router + service catalog** | `agents/`, `config/service_catalog.yaml` | Route + orchestrate + cross-domain handoff | Agents become Workload-Review "reviewer harnesses" |

**No external store required** (Round-2 Asks C/D): registries are YAML files bundled in the package; prompts
are Python modules; reference knowledge is skill files read on demand. No sqlite/pgvector/redis, no
embeddings. [C]

---

## 1. Harvest #3 (logfood framings) → query packs + prompts

The internal metric *definitions* port to public `system.*` by namespace swap plus the harvested
categorical logic. Encode as `SystemQuery` entries and a shared "framings" reference.

**Example — warehouse utilization bands + auto-stop waste** (harvested from `CLUSTER_360.md` /
`DBSQL_ENDPOINT_ANALYSIS.md`, ported `centralized_system_tables.*` → `system.*`):

```python
# discovery/query_packs/warehouse.py  (new/enriched pack)
WAREHOUSE_UTILIZATION_SQL = """
WITH runs AS (
  SELECT warehouse_id, event_time, event_type,
         LEAD(event_time) OVER (PARTITION BY warehouse_id ORDER BY event_time) AS next_time,
         LEAD(event_type) OVER (PARTITION BY warehouse_id ORDER BY event_time) AS next_type
  FROM system.compute.warehouse_events            -- was main.centralized_system_tables.compute_warehouses
  WHERE event_time >= DATEADD(DAY, -{lookback_days}, CURRENT_DATE())
)
SELECT warehouse_id,
       SUM(CASE WHEN event_type='RUNNING' AND next_type='STOPPING'
                THEN UNIX_TIMESTAMP(next_time)-UNIX_TIMESTAMP(event_time) ELSE 0 END)/3600.0 AS uptime_hours
FROM runs GROUP BY warehouse_id
"""
# Utilization category (harvested framing) applied to system.query.history activity vs warehouse RUNNING time:
#   Offline | No utilization | Under utilized (<30%) | Optimal (30-80%) | Resource starved (>80%)
# Auto-stop waste = RUNNING minutes with zero query activity in window (harvested from auto-stop efficiency).
```

**Client-app mix** and **query-load buckets** become reusable CASE snippets in the pack; **T7/T28/T91**
window definitions become pack parameters. The Warehouse/Analytics agent prompts
(`prompts/warehouse/v2.py`, `prompts/analytics/`) gain a "framings" section describing the bands so the LLM
narrates results the way an expert would. Cost queries use `system.billing.usage × system.billing.list_prices`
and are **labeled list-price estimates** (governance flag #3). [C]

---

## 2. Harvest #2 (log-triage) → filter-predicate model + triage prompt + tool

Encode the logs-summariser filter taxonomy as a Pydantic model (no external store), feed a front end over
`spark_event_log_extractor.py` / `large_artifact_processor.py`:

```python
# tools/domain/diagnostic/log_triage.py  (new)
class MatchMode(StrEnum): ANY="any"; ALL="all"; NOT_ANY="not_any"; NOT_ALL="not_all"

class MessagePredicate(BaseModel):
    values: list[str] = Field(min_length=1)   # substrings, >=4 chars, case-insensitive
    match: MatchMode = MatchMode.ANY

class LogFilter(BaseModel):                    # harvested taxonomy, ANDed together
    message_filters: list[MessagePredicate] = []
    logging_levels: list[str] | None = None    # ERROR/WARN/INFO...
    logger_category_filters: list[str] | None = None
    component_filters: list[str] | None = None  # driver | executor | init-script (public analog of pod/project)
    time_window: TimeWindow                      # harvested 2h-window discipline (bounded scan)
```

**Triage prompt** (paraphrased from the analysis-question pattern, governance flag #5): *"Given these log
lines matching the filters, answer <analysis_question>. Report: dominant error(s), level histogram,
first/last occurrence, correlated Spark stage/executor, and a one-line root-cause hypothesis with a
confidence."* Output reuses the diagnostic `evidence_extractor` + `models.py` evidence types.

**Substrate mapping:** ClickHouse columns → log4j fields — `message` (line body), `level` (`ERROR|WARN|…`),
`logger` (class), `timestamp`, `component` (driver/executor from the delivered log path). Source = customer
**cluster log delivery** to DBFS/Volumes, or job-run task logs via the Jobs API. Bounded window keeps the
file scan cheap. [C/I]

---

## 3. Harvest #1 (dbr-doctor) → evidence tags, variable catalog, query-diff

Three sub-harvests, easiest first:

- **Typed evidence tags** — extend the diagnostic evidence model (`patterns/schema.py` evidence checklist,
  `tools/domain/diagnostic/models.py`) so `root_cause_synthesizer.py` emits `root_cause` vs `symptoms` vs
  `evidence_tags[]` (searchable, typed: `oom | shuffle_skew | spill | small_files | throttling | …`),
  mirroring `trace_rca`'s output contract. Pure schema + synthesizer change; reuses existing extractors. [I]
- **A/B query-diff** — new tool over `query_profile_explorer.py`: given two `statement_id`s (or the same
  query across two runs from `system.query.history`), diff per-operator metrics + duration and classify the
  delta as **workload-change vs environment-regression** (harvested `trace_rca_compare` framing). [I]
- **Variable catalog / knowledge pack** — a reference file mapping public `system.*` columns → typed
  variables with confusable notes (e.g. `warehouse_id` vs `cluster_id`, `total_duration_ms` vs
  `execution_duration_ms`), surfaced by progressive disclosure. This replaces a curated RAG corpus with a
  static reference file (Ask C/D). Defer the full semantic-observation-table layer. [I]

---

## 4. Flagship — "Workload Review" (modeled on Isaac `/review`)

Re-implement the `/review` engine shape for **workloads instead of code**, on the existing pattern-registry
machinery. Direct correspondences:

| Isaac `/review` construct | Starboard Workload-Review analog |
|---|---|
| `.isaac/review/rules/<domain>/` rule set | `rules/<domain>/` YAML rule set bundled in the package, loaded by a `RuleRegistry` cloned from `patterns/registry.py` |
| `config.yaml` (name, team, `additional_instructions`, filters, `validation`, `rule_agents`) | `config.yaml` per domain: name, `reviewer_prompt`, **selectors** (which jobs/warehouses/queries a rule targets), `validation` on/off, `agents` (which Starboard domain agent + model) |
| Rule `.md` frontmatter (`name, short_description, rationale, severity, source, filepath_filters`) | Rule YAML (`name, short_description, rationale, severity, source, selectors`) — same fields as `patterns/schema.py` already models `severity`, plus `rationale` |
| Bad/Good tables + "Suggested fix" + "Comment Placement" | Finding `current_state` + `recommended_fix` + `evidence`/target (job/query/warehouse id + metric) |
| **Validator council** (`validation` → independent re-verify, drop false positives) | **Verify-pass**: a second agent/model re-checks each finding against the evidence before it surfaces |
| **`rule_agents`** ensemble / model routing | Route rule sets to the matching Starboard domain agent (`JobAgent`, `QueryAgent`, `WarehouseAgent`, `UCAgent`, `ClusterAgent`) and pick model by cost |
| Severity gate (min = medium; high auto-posted) | `min_severity` config gate; `critical/high` surfaced first |
| **Rule of 30s / Action Rate** | **Adoption metric**: on the next scheduled review, re-scan and check whether the finding cleared (customer applied the fix); prune rules with low adoption |
| `severity × impact / effort → bucket` (from elt-review synthesizer) | Same scorer for the report's priority buckets |

**Rule YAML example** (SQL/query domain, seeded from elt-review `03-sql-query-auditor.md` + query-perf pack):

```yaml
# rules/query/non_sargable_partition_filter.yaml
version: "1.0.0"
rules:
  - id: non_sargable_partition_filter
    name: "Non-SARGable predicate on partition/filter column"
    domain: query
    severity: high
    rationale: >
      Applying a function to a filter/partition column prevents partition pruning and file skipping,
      forcing full scans. Detectable at runtime as low pruning_ratio with high read_files.
    selectors:                       # which workloads this rule reviews (harvested filter-grammar shape)
      statement_types: ["SELECT"]
      min_read_gb: 5
    evidence_query: query_performance.C_Q02   # reuse existing pack query (pruning_ratio, read_files)
    detect:
      pruning_ratio_lt: 0.2
    recommended_fix: >
      Rewrite `WHERE fn(col) = x` as a range predicate on the raw column so pruning applies.
    source: null                     # strip internal go/ links (governance flag #4)
```

**Flow:** `RuleRegistry.load()` (fail-fast, same as diagnostic) → select applicable rules by selectors →
each domain agent runs its rule set against `system.*` evidence (via query packs) → candidate findings →
**verify-pass** (second agent confirms evidence supports the finding, drops false positives) → severity gate
→ scorer/buckets → report via `report_formatters/`. Output is a bucketed **workload-review report**
(exec summary, finding index table, detailed findings with current-state + fix + evidence, roadmap) — the
elt-review `docs/findings.md` layout. Optionally emit fixes as **DABs/Terraform suggestions** rather than a
PR comment (no diff exists for a running workload — fidelity gap from Source 4). [C on mapping, I on details]

**Reviewer domains at launch** (seeded from elt-review sub-agents + logfood framings):
`query` (SQL anti-patterns + runtime spill/prune/cache), `warehouse` (utilization bands, auto-stop waste,
right-size), `job` (failure patterns, retries, config), `cluster` (sizing, config), `uc` (governance:
permissions, orphaned grants, lineage gaps). Each maps to an existing Starboard domain agent. [I]

---

## 5. Encoding summary (native, no external store)

| Harvested artifact type | Encoded as | Repo home | External store? |
|---|---|---|---|
| Triage/RCA/review prompts | Versioned prompt module | `prompts/<domain>/vN.py` | none |
| Diagnostic patterns / workload rules | Fail-fast YAML registry | `patterns/catalog/*.yaml`, new `rules/<domain>/*.yaml` | none |
| Evidence / finding / filter schemas | Pydantic models | `patterns/schema.py`, `diagnostic/models.py`, new `log_triage.py` | none |
| Metric framings | `SystemQuery` in packs | `discovery/query_packs/*.py` | none |
| Variable glossary / decision trees / sizing tables / RCA template | Skill reference files (progressive disclosure) | `starboard-skills/.../resources/` | none (replaces RAG corpus + vector DB) |

This directly advances Round-2 Ask C (drop external stores) and Ask D (native context): the curated RAG
corpus + embeddings that today back the Analytics agent's system-table knowledge are replaced by bundled
registries + reference files read on demand. The internal tools are touched **only at authoring time**; at
customer runtime Starboard reads its own bundled IP + the customer's public `system.*` / delivered logs. [I]

## 6. Open technical questions (see open_questions.md)

- Should `RuleRegistry` be a generalization of the existing `PatternRegistry` (one loader, two domains) or a
  sibling? Leaning generalize — schemas overlap heavily. [U]
- Verify-pass cost: one extra model call per candidate finding — batch per rule set to bound cost. [U]
- Adoption metric requires state across review runs — store in the Databricks-native state adapter
  (`adapters/state/databricks/`) per Round-2 Ask C, not a new store. [I]
