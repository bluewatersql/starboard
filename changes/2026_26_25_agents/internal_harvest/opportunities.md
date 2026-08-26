# Harvest Internal-Tool IP → Public/Customer Data — Opportunity Catalog

> Round-2 Topic B. **Not** wiring internal tools as live backends (that was Round-1 Topic 3 / I1–I4).
> This harvests the *intellectual property* — methodology, heuristics, prompts, taxonomies, evidence
> schemas, severity/confidence models — from internal Databricks tools and re-implements it so it runs
> on **PUBLIC / customer-facing** data (`system.*` tables, public REST/SDK, log delivery to DBFS/Volumes).
> Output = customer-shippable capability that captures how Databricks experts diagnose/review internally.
>
> Confidence tags: **[C]** confirmed from a source I inspected · **[I]** inferred from evidence ·
> **[U]** uncertain / needs validation.
> Sources: Glean docs (cited by URL), internal MCP/skill definitions in this environment, repo `file:line`.

---

## How to read this

Each source below is scored on the required (a)–(f) structure:
**(a)** what IP it embodies · **(b)** the concrete pattern/heuristic/prompt/schema to harvest ·
**(c)** the PUBLIC data it can run on · **(d)** the resulting Starboard capability ·
**(e)** fidelity gap vs the internal original · **(f)** confidence.

A key structural fact underpins the whole exercise: **Starboard already owns the vehicles** to encode
harvested IP. It has a validated YAML *pattern registry* with a severity / category / responsibility /
confidence-factors / evidence-checklist schema
(`packages/starboard/starboard/tools/domain/diagnostic/patterns/schema.py:24-327`,
loaded by `.../patterns/registry.py:52-362`, catalog at `.../patterns/catalog/*.yaml`), a versioned
*prompt library* (`packages/starboard/starboard/prompts/<domain>/v{1,2}.py`), and ~17 *query packs* over
public `system.*` tables (`packages/starboard/starboard/discovery/query_packs/`). Harvesting is therefore
mostly **content authoring into existing structures**, not new infrastructure. [C]

---

## Source 1 — dbr-doctor (semantic observation layer)

**What it is (evidence).** dbr-doctor exposes a *semantic observation layer* over internal debug telemetry
(`main.eng_dp_debug_tools`). Analysis types: `dbr_cluster / qpl_query / job / dbsql / hmr_stack_hash /
notebook / workspace`. Workflows I enumerated via `mcp__dbr-doctor__list_workflow_definitions`:
`generic_data_slice` (slice an observation table by **entity + observation_type + variable transforms**,
written to a Delta UC table), `query_plan` (curated operator-tree / per-operator metrics view),
`query_diff` (A-vs-B plan/metric regression comparison), `dimension_expansion` (resolve identifiers from
concrete values), `trace_rca` (cross-dataset RCA: QPL + frame profiler + delta events + cluster events +
runtime metrics → **"root cause vs symptoms, a recommendation, and typed searchable evidence tags"**),
and `trace_rca_compare` (A = bad run, B = good baseline, reads the delta directly to separate
*workload change* vs *environment regression*). Discovery is driven by two `knowledge://` catalogs:
`entities/{entity_id}` (entity → its observation types) and `variables/{var_name}` (a **variable glossary**:
meanings, source columns, and *confusable look-alikes* e.g. `cluster_id_dbr` vs `cluster_id_k8`). [C]

| Field | Content |
|---|---|
| **(a) IP embodied** | (i) A **semantic layer** that names raw telemetry columns as typed *variables* with a disambiguation glossary; (ii) per-analysis-type **evidence schemas** (each type slices a curated observation table); (iii) **root-cause-vs-symptom** separation with **typed searchable evidence tags**; (iv) **A/B diff** as the primary regression method (workload-change vs environment-regression); (v) **stack-hash fingerprinting** (`hmr_stack_hash`) to cluster recurring failures by normalized stack signature. |
| **(b) Harvest target** | The **variable glossary + entity catalog** as a data model (map public `system.*` columns → typed variables with confusable notes); the **evidence-tag taxonomy** emitted by `trace_rca`; the **A-vs-B diff framing**; and a **fingerprint hash** for query plans / error stacks (Starboard already has `cluster/fingerprint` + diagnostic `pattern_matcher`). |
| **(c) Public data** | `system.query.history` (per-query profile fields — Starboard already reads spill/cache/prune/duration, `discovery/query_packs/query_performance.py:16-78`), query-profile JSON via the SQL/queries API, `system.compute.node_timeline` + `clusters` (node/cluster metrics), `system.lakeflow.job_run_timeline`, cluster **log delivery** to DBFS/Volumes (Spark event logs, log4j), `system.access.audit`. |
| **(d) Starboard capability** | A **customer-facing entity/variable catalog** ("knowledge pack") + a **trace-RCA** that ingests query profile + job-run timeline + cluster events and emits *root-cause / symptoms / recommendation / evidence-tags* — reusing existing `root_cause_synthesizer.py`, `evidence_extractor.py`, `query_profile_extractor.py`, `spark_event_log_extractor.py`. Plus a **query-diff** ("why did this query regress vs last week's run?") built on `query_profile_explorer.py`. |
| **(e) Fidelity gap** | High on the *method*, medium on the *data*. Public tables lack the sub-minute JVM/GC/Hydra series and the HMR stack-hash corpus that back internal cluster/stack RCA; `hmr_stack_hash` has no public equivalent (would degrade to log4j-stack fingerprinting from delivered logs). Query-plan operator trees are obtainable per-query (profile API) but not the curated `main.eng_dp_debug_tools` semantic view. [I] |
| **(f) Confidence** | **[C]** on the workflow set, evidence-tag/RCA framing, entity/variable catalog design (inspected). **[I]** on exact public-column mapping fidelity. |

---

## Source 2 — logs-summariser (ClickHouse log triage)

**What it is (evidence).** MCP server (`mcp__logs-summariser__analyse_logs`) that runs "Isaac Lite (Claude)"
over ClickHouse logs. From the server instructions: it takes an **`analysis_question`** (free-text triage
prompt) plus a rich **structured filter taxonomy** — `message_filters` (list of predicates ANDed together,
each `{"values":[…substrings ≥4 chars…], "match": any|all|not_any|not_all}`, case-insensitive, non-regex),
`logging_levels`, `logger_category_filters`, `pod_name_filters`, `project_filters`, `container_filter`,
`system_filters`, `namespace_filters`, and id-scoped filters (`request_id / trace_id / workspace_id /
span_id`). Constraints: **max 2-hour window**; `kube_context` pattern `{env}-{cloud}-{region}[-suffix]`;
at least one of request/trace/workspace/system/namespace filter required. [C]

| Field | Content |
|---|---|
| **(a) IP embodied** | A **log-triage prompt pattern** ("ask a question, let the model summarize matching lines") married to a **structured predicate filter taxonomy** with precise boolean semantics (any/all/not_any/not_all) and a **bounded-window discipline** (2h) that keeps triage cheap and focused. |
| **(b) Harvest target** | (i) The **filter-predicate schema** (a Pydantic model of `message / level / logger / component / id-scope` predicates with any/all/not_any/not_all match modes); (ii) the **analysis-question → structured-summary prompt**; (iii) the **required-anchor rule** (must pin to an id or scope before triage) and **windowing** discipline. |
| **(c) Public data** | Customer **cluster log delivery** (driver/executor `log4j`, `stdout/stderr`, event logs) to DBFS/Volumes; `system.compute.node_timeline`; job-run/task logs via the Jobs API; `system.access.audit`. The *log lines* are the analog of ClickHouse rows; level/logger/message/timestamp fields exist in log4j output. |
| **(d) Starboard capability** | A **log-triage tool/skill**: point it at a delivered log path (or a job run), supply an analysis question + filter predicates, and get a structured summary (top errors, level histogram, first/last occurrence, correlated stages). Reuses `spark_event_log_extractor.py` + `large_artifact_processor.py` + `artifact_explorer.py`, adding a filter-predicate front end and a triage prompt. |
| **(e) Fidelity gap** | Medium. ClickHouse gives indexed, cross-service, structured columns; customer logs are semi-structured files (must parse log4j) and per-cluster (no fleet view, no pod/kube context, no trace/span correlation across services). The **prompt + predicate schema harvest is lossless**; the *substrate* is weaker (file scan vs indexed store). [I] |
| **(f) Confidence** | **[C]** filter taxonomy + prompt pattern (from MCP server instructions). **[I]** log4j field-mapping fidelity. |

---

## Source 3 — logfood-querier (curated internal metric queries)

**What it is (evidence).** Skill (`fe-internal-tools:logfood-querier`,
`~/.claude/plugins/cache/fe-vibe/fe-internal-tools/1.3.0/skills/logfood-querier/`) that curates the SQL
behind popular internal Lakeview dashboards. Inspected resources: **Cluster 360 V2**
(driver/executor JVM metrics — CPU/heap/GC/thread-sleep, executor-loss & TaskReaper kills, crash detection,
Hydra node HW metrics, SAFEr config-exposure check, query tracking, Spark task-slot utilization) and
**DBSQL Endpoint Analysis V2** (warehouse **uptime**, **utilization %** = `activeTasks/totalTaskSlots` with
categories *Offline / No-utilization / Under-utilized / Optimal / Resource-starved*, **auto-stop efficiency**
= running-with-no-queries waste, **query-load buckets** 0-10/10-100/…/1000+, queue/exec/fetch time, spill,
cache-hit %, **client-app mix** dashboards/jobs/dbt/qlik, SKU breakdown, **T7/T28/T91 windows**, finance-grade
$ via `main.fin_live_gold.paid_usage_metering`). Plus a **schema-selection guide** and regional-scoping rules.
**Crucially:** its DBSQL queries hit `main.centralized_system_tables.{billing_usage, compute_warehouses,
query_history}` — which the `centralized-system-tables-translator` skill confirms is the **cross-account
mirror of the public `system.*` schema**. So the metric *definitions* are namespace-portable to public
`system.*` with near-zero change. [C]

| Field | Content |
|---|---|
| **(a) IP embodied** | Expert **metric definitions & analytical framings**: utilization categories, auto-stop waste, query-load bucketing, client-app classification, T7/T28/T91 trend windows, and a **schema-selection decision guide** (which table answers which question) — i.e. how a Databricks expert *frames* a warehouse/cluster/cost question, not just the raw SQL. |
| **(b) Harvest target** | The **framings, not the tables**: the utilization-category CASE logic, the auto-stop-waste computation, the query-load histogram buckets, the client-app CASE map, the trend-window definitions, and the schema-selection guide (as a reference file). Port `centralized_system_tables.*` → `system.*`. |
| **(c) Public data** | `system.compute.warehouse_events` (≡ `compute_warehouses`), `system.query.history` (≡ `query_history`), `system.billing.usage` (≡ `billing_usage`) + `system.billing.list_prices`, `system.compute.node_timeline`/`clusters` (node metrics). |
| **(d) Starboard capability** | Enrich the **warehouse** + **finops** + **compute** query packs and the Warehouse/Analytics agent prompts with the harvested framings. Starboard already queries `system.query.history` for spill/cache/prune/duration (`query_packs/query_performance.py:16-78`); it is **missing** the *categorical* framings (utilization bands, auto-stop waste, load buckets, client-app mix, trend windows) — those are the harvest. |
| **(e) Fidelity gap** | Low for DBSQL/warehouse/cost framings (public `system.*` carries the same columns). **High** for Cluster 360's JVM/GC/heap/crash detail and Hydra node HW metrics — those come from `main.eng_time_series_metrics` / `eng_lumberjack` with **no public equivalent** (public `node_timeline` is coarse, minute-grain node CPU/mem only). **Finance-grade $** differs: public `system.billing` gives list-price × usage, not contract net-of-discount rates (internal `fin_live_gold`), so Starboard $ are *list-price estimates*, not finance-grade. [C] |
| **(f) Confidence** | **[C]** on framings, table mirror, and gaps (inspected the skill + resources + Starboard pack). |

---

## Source 4 — Isaac `/review` (Databricks' CI-grade code review) — flagship harvest

**What it is (evidence).** From the Isaac Review tech-docs
(`https://tech-docs.dev.databricks.com/engineering/ai-devtools/isaac-review/customization`) and the Code
Review SOP (`go/code-review`, Confluence `2009924716`). Isaac Review has two customization mechanisms and a
structured review engine (`devtools/ai/reviewflow`):

- **Guidelines** (`CLAUDE.md`, `.claude/rules/*.md`) — lightweight, **directory-scoped**, auto-discovered by
  which files a PR touches; describe *how things work* / provide context.
- **Rules** (`.isaac/review/rules/<domain>/`) — centralized, structured **constraints** ("never do X"). Each
  rule set = a `config.yaml` + one or more `.md` rule files:
  - **`config.yaml`**: `name`, `team` (validated against `eng-team-info.json`), `additional_instructions`
    (prompt context appended to the reviewer), **`filters`** (list of `{users, paths (glob),
    diff_patterns (regex)}` blocks with **three-level boolean nesting**: AND across entries, OR within an
    entry, OR within a value list), `opt_out` (users/paths), `enabled`, **`validation`** (route findings
    through a *validator council* for independent re-verification — invalid findings dropped before posting),
    **`rule_agents`** (override the model **council**: list of `agent / agent_model / num_runs`, e.g. swap
    `system.ai.claude-opus-4-8` → `claude-haiku-4-5`, or run an ensemble).
  - **Rule `.md` frontmatter**: `name`, `short_description`, `rationale` (the *why*, used to judge edge
    cases), **`severity`** (`low|medium|high`; **min-severity threshold default = medium**; high is
    prioritized and auto-posted), `source` (go/ link), `enabled`, `filepath_filters` /
    `filepath_exclude_filters`. Body = **Bad/Good pattern tables** + **"Suggested fix"** + a
    **"Comment Placement"** directive (where to attach the inline comment).
- **Quality governance — "Rule of 30s"**: the proxy metric is **Action Rate** (% of comments the author
  acted on). Over the last 30 days, if a rule left ≥30 comments it must hold ≥30% action rate or it is
  **auto-disabled**; tracked on a Rule Performance Dashboard. This is a closed feedback loop on finding
  quality. [C]

| Field | Content |
|---|---|
| **(a) IP embodied** | A complete, battle-tested **review methodology**: (i) a **rule registry** (finding taxonomy as versioned, owned, filterable checks); (ii) a **severity model + min-severity gate**; (iii) a **validator council = verify-pass** (independent re-verification that drops false positives before surfacing); (iv) an **agent/model council** (ensemble, `num_runs`, model routing by cost); (v) a **finding comment schema** (rationale + bad/good + suggested-fix + placement); (vi) a **precise-targeting filter grammar**; and (vii) a **quality feedback loop** (Action Rate / Rule-of-30s) that self-prunes noisy checks. |
| **(b) Harvest target** | Re-implement the whole shape for **workloads instead of code**: a **workload-rule registry** (YAML), a **severity + confidence + validation council** on top of the *existing* `patterns/registry.py` + `patterns/schema.py`, the **bad/good/suggested-fix finding schema**, the **filter grammar** (which jobs/warehouses/queries a rule applies to), and an **action-rate quality metric** (did the customer adopt the recommendation?). |
| **(c) Public data** | Runtime + config, not PR diffs: `system.lakeflow.jobs` / `job_run_timeline` / `job_task_run_timeline` (jobs), `system.query.history` (queries), `system.compute.warehouse_events` / `clusters` (warehouses/clusters), `system.access.audit` + `information_schema` + `system.access.table_lineage` (UC), and the Jobs/Clusters/SQL **REST APIs** for live config. Optionally *also* the customer's code (notebooks, DABs, SQL) — where it converges with `databricks-elt-review` (Source 5). |
| **(d) Starboard capability** | **"Workload Review"** — the flagship. Reviews a workspace's jobs / queries / warehouses / UC config the way `/review` reviews code: runs a rule registry, emits severity-rated findings with rationale + current-state + suggested-fix, passes them through a validator council, gates on min-severity, and reports a bucketed action plan. Starboard's 7 domain agents become the "reviewer harnesses"; the intent router + service catalog already do cross-domain handoff. |
| **(e) Fidelity gap** | The *method* transfers almost fully. Gaps: (i) `/review` acts on a **diff in CI** with OWNERS gating and inline PR comments — a workload has **no diff, no PR, no merge gate**; the analog is a periodic/triggered review producing a report or DABs/Terraform suggestions, not a blocking comment. (ii) Action Rate needs a **feedback channel** (did the customer apply the fix?) that a workspace tool must synthesize (re-scan next run) rather than read from GitHub. (iii) The validator council needs 2+ model calls per finding (cost). [I] |
| **(f) Confidence** | **[C]** on the full methodology (customization doc inspected end-to-end + SOP). **[I]** on the workload-mapping design choices. |

---

## Source 5 — databricks-elt-review (public multi-agent code review — already shippable analog)

**What it is (evidence).** An installed skill (`~/.claude/skills/databricks-elt-review/`) that is essentially
the **public-data twin** of Isaac `/review` for Databricks ELT code. Orchestrator (`SKILL.md`) runs a 5-stage
pipeline: discovery → parallel domain sub-agents → architecture → cross-cutting → synthesis. 12 sub-agents,
each with a **domain checklist** and a JSON finding output: `spark-perf-analyst, delta-lake-inspector,
sql-query-auditor, cluster-config-reviewer, security-compliance-scanner, dlt-pipeline-reviewer,
streaming-micro-batch-auditor, notebook-dependency-mapper, pipeline-architect, test-observability-auditor,
unity-catalog-governer`. The **synthesizer** (`08-synthesizer.md`) dedups (merge same file+lines, keep
highest severity), **scores** `= (severity_weight × impact) / effort_points` with
`severity {Critical=4,High=3,Medium=2,Low=1}` and `effort {XS=1,S=2,M=3,L=4,XL=5}`, **buckets** to
*Fix Immediately (≥20) / This Sprint (≥10) / Backlog (≥4) / Nice-to-Have (<4)*, and writes `docs/findings.md`
with an exec summary, finding index table, detailed findings (current code + proposed fix + explanation),
a sprint roadmap, and a Mermaid notebook-dependency DAG. Example checklist (`03-sql-query-auditor.md`):
SELECT *, non-SARGable predicates, implicit JOIN casts, NULL-key handling, UNION vs UNION ALL, correlated
subqueries, DISTINCT masking, injection risk, etc. [C]

| Field | Content |
|---|---|
| **(a) IP embodied** | A **finding schema + scoring/bucketing formula** (`severity × impact / effort` → priority bucket), a **domain sub-agent taxonomy** with concrete **per-domain checklists**, dedup/merge logic, and a **report structure** (index + detailed + roadmap + DAG). This is the *public-data* rendering of the `/review` methodology. |
| **(b) Harvest target** | (i) The **scoring/bucketing formula** and **finding schema** as the Workload-Review output contract; (ii) the **per-domain checklists** as seed content for the workload-rule registry (SQL auditor → query-review rules; cluster-config-reviewer → cluster/warehouse rules; uc-governer → UC rules); (iii) the **report layout** (already close to Starboard's `agents/report_formatters/`). |
| **(c) Public data** | Customer **code** (repos, notebooks, DABs, `.sql`, job/cluster JSON) — static files. Combine with Source 4's runtime `system.*` for a **code + runtime** review. |
| **(d) Starboard capability** | Two things: (i) directly seed the Workload-Review rule registry & finding schema from these checklists + scorer; (ii) optionally ship an ELT **code**-review skill alongside the runtime review (Starboard already has SQL/Python analyzers: `tools/domain/diagnostic/{sql_analyzer,python_analyzer}.py`). |
| **(e) Fidelity gap** | Low — it is already public-data and open. Weaker than Isaac `/review` on the *engine* side: no validator council, no model-council ensemble, no action-rate quality loop, no filter grammar (it reviews every file). Harvest the **schema/checklists**; borrow the **engine rigor** from Source 4. [C] |
| **(f) Confidence** | **[C]** (fully inspected). |

---

## Source 6 — Other IP discovered (reference-file / heuristic harvest)

Inspected or enumerated in this environment; each is a **reference-content** harvest (decision trees,
anti-pattern catalogs, runbooks) rather than an engine.

| Source | IP to harvest | Public data | Capability | Gap | Conf |
|---|---|---|---|---|---|
| **performance-tuning** (`fe-workflows`, has `decision-trees.md`, `anti-patterns.md`, `spark-config-reference.md`, `code-examples.md`) | Spark/SQL tuning **decision trees**, **anti-pattern catalog**, config reference | `system.query.history`, event logs, cluster config API | Feed the **diagnostic pattern catalog** (`patterns/catalog/*.yaml`) + query/warehouse prompt libraries; back the Workload-Review "performance" rules | Config-reference values drift with DBR versions; keep versioned | **[C]** exists / **[I]** content depth |
| **databricks-troubleshooting** (`fe-workflows`) | Symptom→cause→fix runbook structure | delivered logs, `system.*`, job-run timeline | Seed diagnostic patterns & the trace-RCA prompt | Generic; overlaps dbr-doctor RCA | **[I]** |
| **databricks-sizing** (`fe-workflows`) | Cluster/warehouse **sizing heuristics** (workload → recommended shape) | `system.compute.node_timeline`, `query.history`, `billing.usage` | Warehouse/cluster **right-sizing** recommendations (feeds Workload-Review + finops) | Heuristic, not guaranteed; needs utilization framings from Source 3 | **[I]** |
| **centralized-system-tables-translator** (`fe-internal-tools`) | The **`system.*` ⇄ `main.centralized_system_tables.*` mapping** | n/a (it *is* the map) | **Enabling asset**: lets us port any internal `centralized_*` query to public `system.*` mechanically | Internal→public only; some internal-only columns won't map | **[C]** |
| **draft-rca / fe-poc-postmortem** (`fe-workflows`) | RCA **document structure** (timeline, root cause, contributing factors, remediation, prevention) | any diagnostic output | Report template for the diagnostic agent's RCA output | Doc-shape only, low technical IP | **[I]** |

---

## Master harvest → public-capability map

Legend — LOE: S ≤ ~1 wk · M ~2–4 wk · L ~1–2 mo (one engineer, rough). Fidelity: how faithful the
public-data version is to the internal original.

| # | Internal source | IP harvested | Public data source | Starboard capability | Strengths | Weaknesses / trade-offs | Complexity | LOE | Fidelity | Conf |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **dbr-doctor** | Semantic entity/variable catalog; root-cause-vs-symptom + typed evidence tags; A/B query diff; stack-hash fingerprint | `system.query.history`, query-profile API, `node_timeline`, `job_run_timeline`, delivered logs, `access.audit` | Customer **trace-RCA** + **query-diff** + knowledge pack | Reuses existing extractors/synthesizer; evidence-tag model is clean & shippable | No public JVM/GC/Hydra series or HMR stack corpus; semantic view must be rebuilt | High | L | Med-High (method) / Med (data) | C/I |
| 2 | **logs-summariser** | Filter-predicate taxonomy (any/all/not_any/not_all) + analysis-question triage prompt + bounded window | Cluster **log delivery** (log4j/event logs) to DBFS/Volumes, job logs | **Log-triage** tool/skill over customer logs | Prompt + schema harvest is lossless; reuses artifact/event-log processors | File-scan substrate (not indexed ClickHouse); no fleet/pod/trace correlation | Med | M | Med | C/I |
| 3 | **logfood-querier** | Metric framings: utilization bands, auto-stop waste, query-load buckets, client-app mix, T7/T28/T91, schema-selection guide | `system.compute.warehouse_events`, `query.history`, `billing.usage`+`list_prices`, `node_timeline` | Enriched **warehouse / finops / compute** packs + prompts | Table mirror ⇒ near-lossless port for DBSQL/cost; low LOE, high value | Cluster-360 JVM/GC/crash detail has no public equivalent; $ is list-price est., not finance-grade | Low-Med | S-M | High (DBSQL/cost) / Low (JVM) | C |
| 4 | **Isaac `/review`** | Rule registry; severity + min-severity gate; **validator council (verify-pass)**; **agent/model council**; bad/good/suggested-fix schema; filter grammar; **Action-Rate quality loop** | `system.lakeflow.*`, `query.history`, `compute.*`, `access.audit`, `information_schema`, Jobs/SQL APIs | **Workload Review** (flagship) | Complete, proven methodology; maps onto existing `patterns/registry.py` + 7 agents; strongest differentiator | No PR/diff/merge-gate; action-rate needs synthesized feedback; validator council = extra model cost | High | L | High (method) / Med (feedback loop) | C/I |
| 5 | **databricks-elt-review** | Finding schema + `severity×impact/effort` scoring/bucketing; per-domain checklists; report layout | Customer **code** (repos/notebooks/DABs/SQL) + runtime `system.*` | Seeds Workload-Review registry + optional **code**-review skill | Already public & open; concrete seed content; scorer is drop-in | No validator/ensemble/action-rate; reviews everything (no targeting) | Low-Med | S-M | High | C |
| 6 | **perf-tuning / troubleshooting / sizing / RCA runbooks / translator** | Decision trees, anti-pattern catalog, sizing heuristics, `system.*` mapping, RCA doc structure | `system.*`, logs | Reference files feeding pattern catalog, prompts, sizing & report templates | Cheap content harvest; compounding value across capabilities | Content drifts with DBR/product; low standalone IP | Low | S each | Med | C/I |

---

## Native-context tie-in (how harvested IP stops needing the internal tool at runtime)

All six harvests land as **native, no-external-store** assets — reinforcing Round-2 Asks C/D:

1. **Prompts** (triage question patterns, RCA framing, review `additional_instructions`) →
   `packages/starboard/starboard/prompts/<domain>/v{n}.py` (versioned prompt library, already exists). [C]
2. **Heuristics / rules / patterns** (diagnostic patterns, workload-review rules, anti-pattern catalogs) →
   **YAML registries** loaded by the existing `patterns/registry.py` fail-fast loader — extend the schema
   to a `rules/` domain (Source 4/5). No DB, no embeddings. [C]
3. **Evidence schemas** (per-analysis-type evidence, evidence-tags, finding schema) → Pydantic models
   alongside `patterns/schema.py`. [C]
4. **Query shapes** (harvested metric framings) → `discovery/query_packs/*` over `system.*`. [C]
5. **Reference knowledge** (variable glossary, schema-selection guide, decision trees, sizing tables) →
   **skill reference files** surfaced by progressive disclosure (read only when the skill fires) — the
   direct replacement for the curated RAG corpus + vector DB that Round-2 Ask C targets. [I]

Net: the internal tools are consulted **once, at authoring time** (via Glean + these skill/MCP defs) to
extract the IP; at customer runtime Starboard reads only its own bundled registries/prompts/packs + the
customer's public `system.*` / logs. No live dependency on dbr-doctor, logfood, logs-summariser, or the
Isaac reviewflow service. [I]
