# Grounding Brief — Round 2 Addendum (Feedback-Driven Deep Dives)

> Extends `_grounding_brief.md` with evidence for the four Round-2 asks (2026-08-26 feedback).
> Same rules: reason from first principles, evidence-based, don't anchor to current impl.
> All facts below verified from the codebase (commit `b927dfaa`, starboard 0.1.1).

## Round-2 asks (from user feedback)

- **A. Dep-ful progressive-disclosure helper scripts.** Repackage existing heavy capabilities as
  helper scripts that MAY install starboard deps, surfaced via progressive disclosure — a *middle
  tier* between the ultra-thin `starboard-helper` (no deps) and the full MCP server (heavy). Goal:
  move away from the heavy server approach while keeping depth.
- **B. Harvest internal-tool IP for public/customer data.** Extract patterns, approaches,
  heuristics, prompts, context from `dbr-doctor`, `logfood`, `logs-summariser`, Isaac skills like
  `/review`, and others — then apply that IP to PUBLIC/customer-facing data sources. (Distinct from
  Topic 3's I1–I4, which *wired the tools as backends*; this harvests the *methodology* to run on
  public data.)
- **C. Remove external-store dependencies** — sqlite / postgres / redis / pgvector / RAG vector DBs.
- **D. Use native capabilities** for memory, context handling, etc. (agent-host + Databricks-native).

## Evidence: external stores (Ask C)

Declared deps (`packages/starboard/pyproject.toml:51-57`): `redis`, `asyncpg`, `pgvector`,
`aiosqlite`, `sqlite-vec`. Config defaults (`infra/core/config.py`):
- `database_backend: Literal["postgres","databricks","sqlite"] = "sqlite"` (`:128`)
- `vector_backend: Literal["sqlite","chroma","databricks","postgres"] = "sqlite"` (`:145`)
- `cache_backend == "redis"` needs `redis_url` (`:328-329`); sqlite path validated `:334`.

**The abstraction already exists** — a Protocol-based state layer with swappable adapters:
`adapters/state/{inmemory,sqlite,postgres,redis,databricks}/` (state_store, memory_store,
user_store, cache_store, feedback_repository), selected by `infra/core/state_factory.py:56-194`.
Repository Protocols live in `domain/repositories/` (e.g. `UserRepository`, `user_repository.py:14`).

⇒ "Remove external stores" is a **defaults + packaging** change, not a rewrite: default to
`databricks` (UC/warehouse tables, `adapters/state/databricks/`) or `inmemory`, move
postgres/redis/sqlite-vec/pgvector to optional extras or delete, keep the Protocol.

## Evidence: RAG / memory (Asks C + D)

- RAG (`infra/rag/`) is **retrieval over a FIXED curated corpus**: Databricks resource-model
  knowledge — system tables mapped to `RagResourceDomain` labels
  (`starboard-core/.../rag/resource_domains.py`) — used by the **Analytics agent** to build context
  for correct system-table SQL. Vector stores: `inmemory_vector_store.py`,
  `sqlite_vector_store.py`, `sqlite_multi_collection_store.py`; embeddings via
  `adapters/embedding/`; bootstrap corpus in `infra/rag/data/bootstrap/`.
- Conversation memory: `services/memory/{embedding_service,memory_consolidation}.py` +
  `adapters/state/*/memory_store.py` — embedding-based conversation recall.

⇒ Because the RAG corpus is **static and curated**, it is a prime candidate to replace with
**native context**: ship the knowledge as progressive-disclosure reference files / skills, or lean
on the ~17 query packs (which already encode system-table know-how), eliminating embeddings + a
vector DB. Conversation memory can defer to the agent host's native session/memory + Databricks UC
for durable state.

## Evidence: heavy capabilities repackageable as dep-ful helpers (Ask A)

Current tiers: thin `starboard-helper` (7 domains, bare `WorkspaceClient()`, no starboard deps) ↔
full MCP server (7 agents, ~45 tools, server lifecycle). The middle tier can expose, as
`python -m` helper scripts that import starboard packages:
- **Spark/Photon event-log parser** (`starboard-core/.../log_parser/`) — pure, heavy-ish (polars).
- **Diagnostic extractors** (`tools/domain/diagnostic/`: exit_code_triager, query_profile_extractor,
  spark_event_log_extractor, evidence_extractor, pattern_matcher + `patterns/registry.py`,
  root_cause_synthesizer, artifact_explorer).
- **Discovery engine** (`discovery/engine.py`) with deterministic `data_only` mode + ~17 query packs.
- **Analyzers** (`starboard-core/.../domain/analyzers/`: warehouse, uc), cluster analyzers
  (`tools/domain/cluster/`), chart renderer (`tools/services/chart_renderer.py`),
  warehouse-portfolio/query-workload services, UC lineage/storage/governance services.

Progressive disclosure = a SKILL.md names a script + reference file; Claude reads the script's
`--help`/reference only when the skill fires, then shells out (`python -m starboard_x …`). Deps are
installed once (`pip install starboard[...]`), but the *context cost* stays near-zero until used.

## Evidence: internal-tool methodology to harvest (Ask B) — where to look

From this environment's tool/skill definitions (harvest the *approach*, run on public data):
- **dbr-doctor** — semantic observation layer over `main.eng_dp_debug_tools`; analysis types
  `dbr_cluster / qpl_query / job / dbsql / hmr_stack_hash / notebook / workspace`; `knowledge://`
  entity+variable catalogs. Harvest: the **stack-hash fingerprinting**, per-analysis-type evidence
  schemas, and the entity/variable catalog structure → apply to public `system.*` + logs.
- **logs-summariser** — ClickHouse log analysis with structured `message/level/logger/pod` filters
  and an analysis-question prompt pattern. Harvest: the **log-triage prompt + filter taxonomy** →
  apply to customer cluster logs via public log delivery / DBFS.
- **logfood-querier** — curated internal metric queries (Cluster 360, DBSQL endpoint, JVM/GC).
  Harvest: the **metric definitions & dashboard query shapes** → map to public `system.compute.*`.
- **Isaac `/review`** (Databricks' CI-grade review pipeline) — harvest the **review methodology**
  (finding taxonomy, severity model, verify-pass structure, `ReportFindings` schema) → a Starboard
  "workload review" that reviews jobs/queries/warehouses the way `/review` reviews code.
- Others to scan via Glean/skill defs: `databricks-elt-review`, `dbr-doctor` workflows,
  `centralized-system-tables-translator`, FE performance-tuning / troubleshooting skills.

## Cross-links to Round-1 topics

- A extends **decomposition** (Topic 4 tiers) + **integration** (Topic 1 progressive disclosure).
- B extends **optimization** (Topic 3 I1–I4) but harvests *IP*, not backends.
- C/D extend **decomposition** (drop the heavy `starboard` deps) + **auth** (Databricks-native store
  reuses the same `WorkspaceClient`).
