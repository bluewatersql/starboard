# Native Simplification — Per-Store Teardown (Topics C + D)

> Envisioning study, 2026-08-26. Research/documentation only — no code changes.
> Evidence cited as `file:line` against commit `b927dfaa` (starboard 0.1.1).
> Reason from first principles; the current impl is evidence, not a constraint.

## TL;DR

Starboard's external-store dependence is **shallow**: state/memory/cache already sit
behind Protocols (`starboard_core/ports/{state_store,memory_store,cache_store}.py`) with
swappable adapters (`adapters/state/{inmemory,sqlite,postgres,redis,databricks}/`) chosen
by a factory (`infra/core/state_factory.py`). Three facts reframe the whole task:

1. **The `databricks` state backend is NOT UC-native.** `DatabricksLakebaseStateStore`
   *extends* `PostgresStateStore` and speaks `asyncpg` to Lakebase (managed Postgres)
   — `adapters/state/databricks/state_store.py:14,24,136`. Selecting `database_backend=databricks`
   today still pulls `asyncpg`/`pgvector`. So "use Databricks-native state" is **not yet built**.
2. **A truly native UC-table storage layer already exists but is orphaned.**
   `infra/storage/uc_adapter.py` (`UCStorageAdapter`: Delta CRUD via SQL-warehouse
   `statement_execution`, using a bare `WorkspaceClient`), `infra/storage/repository.py`
   (`UCRepository[T]` typed CRUD), `table_registry.py`, `warehouse_tables.py`. **Zero
   consumers** — it is not wired into `state_factory`/`Container`. This is the missing native
   state adapter, ~80% built.
3. **RAG is retrieval over a FIXED curated corpus** (`starboard-core/.../rag/resource_domains.py`
   maps ~30 `system.*` tables → domains; bootstrap packs in `infra/rag/data/bootstrap/`).
   The only implemented vector backends are `sqlite` and `inmemory`
   (`infra/rag/services/vector_store_factory.py:63,105`) — `chroma`/`databricks`/`postgres`
   from the config enum (`config.py:145`) are **not implemented**. A static corpus is a prime
   candidate for progressive-disclosure reference files, dropping embeddings + the vector DB.

Net: reaching a **zero-external-store default** is a *defaults + packaging + one new adapter
+ CLI-session swap*, not a rewrite. Heavy backends become optional extras or are deleted.

---

## Store → native-replacement map

| Store (dep) | Used for | Today (file:line) | Native replacement | Tier where it applies |
|---|---|---|---|---|
| **`aiosqlite` / SQLite** | dev/default conversation state, memory, users, feedback; **CLI durable named sessions** | `state_factory.py:63,79,169,185`; `cli/sessions/session_manager.py:12,76` | In-memory (ephemeral run) + **JSON session files** / agent-host session (CLI) + **UC tables** (durable server) | thin CLI, default |
| **`sqlite-vec`** | RAG vector store, reflexion, semantic cache (SQLite path) | `vector_store_factory.py:63`; `container.py:181,199` | Progressive-disclosure **reference files / query packs** (RAG); in-proc dict (semantic cache); drop reflexion by default | default |
| **`asyncpg` / Postgres** | staging/prod conversation state + memory | `state_factory.py:104,201`; `adapters/state/postgres/*` | **UC tables** via `UCStorageAdapter` for durable state; keep Postgres as **optional extra** for high-concurrency multi-user App | server / optional |
| **`pgvector`** | vector similarity in Postgres/Lakebase memory | `pyproject.toml:53`; `adapters/state/postgres/memory_store.py`, `databricks/memory_store.py` | **Databricks Vector Search** (managed) only if semantic memory is truly needed; else drop | optional / escape-hatch |
| **`redis`** | distributed cache + rate-limit storage | `state_factory.py:130-132`; `config.py:141,160,328` | In-process `InMemoryCacheStore` (single instance) + **Databricks SQL result cache** (query results); Redis **optional extra** for multi-replica | optional |
| **Lakebase (managed PG, via `asyncpg`)** | `database_backend=databricks` durable state | `adapters/state/databricks/state_store.py:24,136` | **UC tables** for most workloads; **keep Lakebase** as the honest OLTP option for high-concurrency multi-user Apps | optional |
| **Embedded RAG vector DB (sqlite-vec/in-mem)** | Analytics-agent system-table SQL context | `tools/adapters/rag_tools.py:133`; `vector_store_factory.py` | **Reference files** shipped in package + query packs; **Databricks Vector Search** only if corpus grows/needs fuzzy recall | default |

## "Keep-as-optional" list (do NOT delete — gate behind extras)

| Capability | Extra | Why keep it |
|---|---|---|
| Postgres state/memory (`asyncpg`) | `starboard[postgres]` | High-concurrency, multi-user, low-latency OLTP that UC Delta tables cannot serve (see §4 open questions). |
| Lakebase adapter (`asyncpg`) | `starboard[lakebase]` (or fold into `[postgres]`) | Databricks-managed OLTP + OAuth token refresh already built (`databricks/state_store.py:199`). Best of both: Databricks-native *and* real Postgres semantics. |
| Redis cache (`redis`) | `starboard[redis]` | Shared cache / rate-limit store across horizontally-scaled App replicas. |
| pgvector / semantic memory | `starboard[memory]` | Embedding-based episodic recall + semantic cache when a deployment actually wants long-term learned memory. |
| Databricks Vector Search client | `starboard[vectorsearch]` | Managed semantic retrieval when the curated corpus outgrows static reference files. |

---

## Per-store teardown

### 1. SQLite (`aiosqlite`, `sqlite-vec`) — the default today

| Field | Detail |
|---|---|
| **Used for** | Default conversation state + memory in `dev` (`state_factory.py:56-63,161-169`), in-memory SQLite in `test` (`:79,:185`), the RAG/reflexion/semantic-cache vector stores (`vector_store_factory.py:63`, `container.py:181,199`), and **CLI durable named sessions** (`cli/sessions/session_manager.py:12` imports `aiosqlite`; `:76` instantiates `SQLiteStateStore`; `:32` `cli_sessions` DDL). |
| **What breaks if removed** | (a) Default dev state → nothing durable; multi-turn history lost on restart. (b) `starboard sessions` named-session resume (the one hard `aiosqlite` import in the CLI hot path) — `session_manager.py:108`. (c) RAG/semantic-cache degrade to in-memory (already handled — `vector_store_factory.py:96-104`; `container.py:205` swallows failures). |
| **Native replacement** | Ephemeral run state → `InMemoryStateStore`/`InMemoryMemoryStore` (already exist, `adapters/state/inmemory/`). Durable CLI sessions → **JSON files** under `~/.starboard/sessions/` (agent-host-friendly; Claude Code already persists its own session — see technical.md §native memory). Durable server state → **UC tables** (§2). |
| **Lost** | Zero-config local file durability; SQL-queryable local history; `sqlite-vec` ANN for local semantic recall. |
| **Gained** | No native-extension pain (`container.py:214-223` documents the `enable_load_extension` failure mode — a real support cost on macOS/pyenv); smaller wheel; the CLI can run with **no DB driver at all**. |
| **Strengths of keeping** | Frictionless offline dev; single-file portability. |
| **Weaknesses** | `sqlite-vec` is a compiled loadable extension → fragile across Python builds (`container.py:209-223`); not multi-writer safe; useless inside Databricks Apps (ephemeral FS). |
| **Trade-offs** | Dropping SQLite as *default* is clean; keeping it as a `starboard[sqlite]` extra preserves the nice local-dev story at ~zero cost. |
| **Complexity** | Low. |
| **LOE** | **S** for defaults flip; **M** for the JSON-session rewrite of `SessionManager`. |

### 2. Postgres (`asyncpg`) + Lakebase

| Field | Detail |
|---|---|
| **Used for** | staging/prod `StateStore`/`MemoryStore` (`state_factory.py:92-106,194-203`); `database_backend=databricks` routes to Lakebase which **is** Postgres-over-`asyncpg` (`databricks/state_store.py:24` `class DatabricksLakebaseStateStore(PostgresStateStore)`, `:136` `asyncpg.create_pool`). |
| **What breaks if removed** | Multi-user server deployments lose durable, concurrent, low-latency conversation/memory persistence. `Container.user_store`/`feedback_repo` type-switch on the store (`container.py:514,581-594`) and expect a `pool`. |
| **Native replacement** | New **UC-table adapters** (`UCStateStore`/`UCMemoryStore`/`UCUserStore`/`UCFeedbackRepository`) over the existing `UCStorageAdapter` (`infra/storage/uc_adapter.py`) + `UCRepository` (`repository.py`). Reuses the same `WorkspaceClient` as the auth resolver — no new credentials, no new network dependency. |
| **Lost** | Sub-10ms row reads/writes; true transactional OLTP; high write concurrency. UC Delta via `statement_execution` is **seconds-latency, low-concurrency** (see open_questions.md). |
| **Gained** | Zero external DB to provision; state is governed UC data (auditable, shareable, lineage); one auth path. |
| **Strengths** | UC tables ride existing Databricks infra + governance; Lakebase gives real Postgres semantics *and* Databricks-native OAuth (`databricks/state_store.py:172-197`). |
| **Weaknesses** | UC-table latency/concurrency unfit for chatty per-turn writes at scale; Lakebase still needs an instance provisioned + `asyncpg`. |
| **Trade-offs** | UC tables for low-write-rate durable data (users, feedback, fingerprints, occasional conversation snapshots); Postgres/Lakebase (optional extra) for high-concurrency chat state. |
| **Complexity** | Medium (adapter + repo type-switch generalization at `container.py:511-594`). |
| **LOE** | **M** (adapters exist for CRUD; wire StateStore/MemoryStore Protocol methods on top). |

### 3. pgvector

| Field | Detail |
|---|---|
| **Used for** | Vector column in Postgres/Lakebase memory stores for embedding-based episodic recall (`pyproject.toml:53`; `adapters/state/postgres/memory_store.py`, `databricks/memory_store.py`). Backs `MemoryStore.recall_episodes`/`query_facts` (`ports/memory_store.py:56,108`). |
| **What breaks if removed** | Semantic recall of past conversation episodes / facts in the Postgres path. **Note:** `memory_consolidation_enabled=False` by default (`config.py:155`) and `MemoryConsolidationService` only self-references `memory_repo` (`services/memory/memory_consolidation.py:144`) — no consumer found in `adapters/conversation/` or `agents/`. Long-term memory is effectively **dormant** today. |
| **Native replacement** | If semantic memory is genuinely wanted → **Databricks Vector Search** (managed, delta-sync). Otherwise drop it: rely on agent-host session context + recent-episode lists (`get_recent_episodes`, `ports/memory_store.py:75`) which need no vectors. |
| **Lost** | Cross-session fuzzy memory recall. |
| **Gained** | Removes a compiled Postgres extension dependency and the embedding round-trip on every recall. |
| **Strengths / weaknesses** | Powerful but unused; carrying it as a hard dep is pure cost today. |
| **Trade-offs** | Gate behind `starboard[memory]`; make `recall_episodes` degrade to recency when no vector backend. |
| **Complexity** | Low (mostly deletion + graceful-degrade). |
| **LOE** | **S**. |

### 4. Redis

| Field | Detail |
|---|---|
| **Used for** | Distributed cache when `redis_url` set (`state_factory.py:130-132`); rate-limit storage option (`config.py:160` `rate_limit_storage`, `slowapi`); `cache_backend=redis` (`config.py:141,328`). |
| **What breaks if removed** | Shared cache + rate-limit counters across multiple App replicas. Single-instance deployments are unaffected — default is already `cache_backend=memory` (`config.py:141`) and the factory falls back to `InMemoryCacheStore(max_size=1000)` (`state_factory.py:135-137`). |
| **Native replacement** | In-process `InMemoryCacheStore` for single instance; **Databricks SQL result cache / query result reuse** for repeated system-table queries (the expensive thing worth caching); `QueryResultCache` already speaks the `CacheStore` Protocol so it's backend-agnostic (`tools/services/query_result_cache.py:127-137`). Rate limiting → in-memory (`memory://`) default. |
| **Lost** | Cross-replica cache coherence + shared rate-limit windows. |
| **Gained** | No Redis to run; simplest possible cache path. |
| **Strengths / weaknesses** | Redis is the right tool *only* for horizontally-scaled hosting; otherwise it's a network hop for a dict. |
| **Trade-offs** | Keep as `starboard[redis]` extra; document "needed for multi-replica Apps." |
| **Complexity** | Low (already optional at runtime; just move the dep). |
| **LOE** | **S**. |

### 5. Embedded RAG vector DB (the marquee simplification)

| Field | Detail |
|---|---|
| **Used for** | The **Analytics/FinOps agent** builds system-table SQL context by semantic search over a curated corpus: `AnalyticsContextTools.build_analytics_context` → `vector_store.search_multi_collection` over `Tables/Nuance/Facets/Codebook` collections (`tools/adapters/rag_tools.py:57-138`). Corpus is **static + curated**: `resource_domains.py` maps `system.*` tables → domains; bootstrap packs `infra/rag/data/bootstrap/{codebook,facets}.json` + `*_embeddings.npz`; `starboard-core/.../rag/data/{codebook,nuance}_pack.json`. Vector store = sqlite-vec or in-memory only (`vector_store_factory.py:63,105`). |
| **What breaks if removed** | The agent loses embedding-ranked retrieval. But it **already degrades to empty context** on embedding failure without crashing (`rag_tools.py:139-149`), and returns a token-efficient context *handle*, not raw text (`:161-174`). So removal is a *quality* change, not a *breakage*. |
| **Native replacement** | Ship the corpus as **progressive-disclosure reference files** (markdown/JSON) the agent reads on demand — a `SKILL.md`-style "system-tables reference" keyed by the same `RagResourceDomain` labels (`resource_domains.py:23-41`), plus the ~17 **query packs** (`discovery/query_packs/`) which already encode correct system-table SQL. Retrieval becomes deterministic domain-keyed file lookup (map query → domains via `map_system_table_to_rag_resource_domains`, load that domain's reference). **Escape hatch:** Databricks Vector Search if the corpus grows or needs fuzzy recall. |
| **Lost** | Fuzzy semantic ranking within a domain; ability to surface a nuance the LLM didn't name. Mitigated because the corpus is small, curated, and domain-partitioned. |
| **Gained** | Drop `sqlite-vec` + embeddings + `.npz` bootstrap + embedding round-trip latency + the whole `infra/rag/adapters/storage` + `services/vector_store_factory` complexity. Context becomes inspectable/versioned files; edits need no re-embedding. Aligns with agent-host progressive disclosure (see technical.md). |
| **Strengths** | Static corpus ⇒ retrieval quality is mostly a function of *coverage*, which files give directly; the model reads curated text instead of top-k chunks. |
| **Weaknesses** | Larger prompt if a whole domain file is loaded (mitigate with per-domain files + the existing context-handle pattern); loses ANN if corpus scales to thousands of entries. |
| **Trade-offs** | Reference-file default; Vector Search extra for scale. |
| **Complexity** | Medium (author reference files from existing packs; rewrite `build_analytics_context` to file-lookup). |
| **LOE** | **M–L** (corpus authoring dominates). |

### 6. Reflexion store + semantic cache (SQLite-vector foundation components)

| Field | Detail |
|---|---|
| **Used for** | `SQLiteReflexionStore` (agent learnings) + `SemanticCache` (LLM-response cache), both on a dedicated SQLite vector DB (`container.py:180-204`). Referenced by `agents/tools/tool_factory.py`, schemas `rag.py`/`analytics_sql.py`. |
| **What breaks if removed** | Learned-reflexion retrieval + semantic (fuzzy) LLM cache hits. Both are **already optional**: initialized only outside `test` env and wrapped in try/except that logs and continues (`container.py:143,205-231`); `enable_reflexion=False` and note at `:195-198` says semantic cache runs TTL-only without vectors. |
| **Native replacement** | Semantic cache → exact-match TTL cache (in-proc), which the code already falls back toward. Reflexion → defer to agent-host memory (CLAUDE.md / Memory tool) or drop by default; optional UC-table or Vector Search backing if wanted. |
| **Lost / Gained** | Lost: fuzzy cache hits + cross-run learnings. Gained: removes the last hard `sqlite-vec` need in the server path. |
| **Complexity / LOE** | Low / **S** (flip defaults off; they already degrade). |

---

## Cross-cutting: what a zero-external-store default deployment looks like

| Concern | Default (zero-store) | Durable server | High-concurrency multi-user |
|---|---|---|---|
| Run/session state | in-memory + JSON files / agent-host session | **UC tables** | Postgres/Lakebase (extra) |
| Users / feedback | in-memory (ephemeral) or UC tables | **UC tables** | Postgres/Lakebase (extra) |
| Long-term memory | agent-host session (off by default) | UC tables (recency) | Vector Search (extra) |
| RAG knowledge | **reference files + query packs** | reference files | Vector Search (extra) |
| Cache | in-process dict + Databricks result cache | in-process | Redis (extra) |
| Hard deps beyond `databricks-sdk`+`mcp` | **none** | none (UC via WorkspaceClient) | `asyncpg`/`redis` |
