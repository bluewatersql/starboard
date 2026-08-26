# Native Simplification — Technical Design (Topics C + D)

> Architecture for a zero-external-store default that preserves the `starboard_core/ports/*`
> Protocols. Grounded in current code (`file:line`) and verified native APIs.
> Inline `[DOC:key]` tags resolve to verified URLs in the References section.

## 0. Current wiring (what we are changing)

```
Container.initialize()                         # infra/core/container.py:100
  ├─ create_state_store(config)   ─┐           # state_factory.py:34  → SQLite | Postgres | Lakebase | InMem
  ├─ create_cache_store(config)    │           # state_factory.py:116 → Redis | InMem
  ├─ create_memory_store(config)  ─┘           # state_factory.py:140 → SQLite | Postgres | Lakebase | InMem
  ├─ CacheFactory(namespaced caches)           # container.py:125-134
  └─ _initialize_foundation_components()        # container.py:146  (try/except, skipped in test)
        ├─ LLMClientEmbeddingProvider
        ├─ create_vector_store()  → SQLite-vec | InMem   # vector_store_factory.py
        ├─ SQLiteReflexionStore  (sqlite-vec)
        └─ SemanticCache (TTL; vector optional)
```

Protocols (keep all): `StateStore` (`ports/state_store.py:10` — `get/set/delete` +
`get_conversation/save_conversation/list_conversations/update_metadata`), `MemoryStore`
(`ports/memory_store.py:10` — `store_episode/recall_episodes/get_recent_episodes/store_fact/
query_facts/get_profile/update_profile/delete_user_data`), `CacheStore`
(`ports/cache_store.py`). Selection is by `EnvConfig` (`config.py`). Nothing below changes
these signatures — only which adapter the factory returns and what deps that adapter needs.

## 1. Protocol-preserving default swap

**Config precedence.** Resolution order stays `env var > EnvConfig field default`. Change the
*defaults*, add a native `uc` backend, and gate absent drivers:

| Field | Today (`config.py`) | Proposed default | Notes |
|---|---|---|---|
| `database_backend` | `sqlite` (`:128`) | `memory` (dev) / `uc` (server) | add `"uc"` and `"memory"` literals; rename current `databricks`→`lakebase` |
| `vector_backend` | `sqlite` (`:145`) | `none` | reference-file RAG needs no vector store; `vectorsearch`/`sqlite` opt-in |
| `cache_backend` | `memory` (`:141`) | `memory` (unchanged) | already store-free by default |
| `redis_url` | `None` | `None` | Redis only when set |

**Factory change (illustrative), `state_factory.py`:**

```python
def create_state_store(config: EnvConfig) -> StateStore:
    backend = config.database_backend
    if backend in ("memory", None):
        return InMemoryStateStore()                     # zero deps
    if backend == "uc":
        return UCStateStore(UCStorageConfig.from_env())  # native, WorkspaceClient only
    if backend == "sqlite":
        _require("aiosqlite", extra="sqlite")            # lazy import guard
        return SQLiteStateStore(config.sqlite_state_path)
    if backend in ("postgres", "lakebase"):
        _require("asyncpg", extra="postgres")
        return (LakebaseStateStore(DatabricksLakebaseConfig.from_env())
                if backend == "lakebase" else PostgresStateStore(config.database_url))
    raise ValueError(f"unknown database_backend={backend}")

def _require(mod: str, *, extra: str) -> None:
    try: __import__(mod)
    except ImportError as e:
        raise RuntimeError(f"backend needs `pip install starboard[{extra}]`") from e
```

The `Container` capability switch for `user_store`/`feedback_repo` (`container.py:511-596`)
today `isinstance`-dispatches on the store. Generalize to capability dispatch so `UCStateStore`
supplies its own `UCUserStore`/`UCFeedbackRepository` (e.g. an optional
`state_store.get_user_store()` hook) rather than extending the `isinstance` ladder.

## 2. Databricks-native UC-table state adapter

**The building blocks already exist and are unused** (zero consumers found):
- `UCStorageAdapter` (`infra/storage/uc_adapter.py:83`) — Delta CRUD via SQL-warehouse
  `statement_execution` using a bare `WorkspaceClient` (`:527-533`); auto-creates catalog/schema/
  tables (`:130-201`); MERGE-based `upsert` (`:412-446`); async via `run_databricks_sync`.
  SQL-injection defense: identifier allowlist + value escaping (`:489-512,650-678`).
- `UCRepository[T]` (`infra/storage/repository.py:19`) — typed `get/list/save/delete` over the
  adapter, handles dataclass + Pydantic (`:152-194`).
- `TableRegistry`/`TableDef`/`ColumnDef` (`table_registry.py`) + a worked example set
  (`warehouse_tables.py` registers SLO/fingerprint/health/scenario Delta tables with
  partitioning + `delta.autoOptimize`).

**Design:** add state tables to a registry and thin Protocol adapters over `UCRepository`:

```python
# new: adapters/state/uc/tables.py  — register alongside warehouse_tables.py
register(TableDef("conversations", columns=(
    ColumnDef("conversation_id","STRING",nullable=False),
    ColumnDef("user_id","STRING",nullable=False),
    ColumnDef("messages","STRING"),          # JSON blob (Delta has no native JSON type)
    ColumnDef("metadata","STRING"),
    ColumnDef("updated_at","TIMESTAMP",nullable=False)),
    primary_key=("conversation_id",), partition_by=("user_id",),
    properties={"delta.autoOptimize.optimizeWrite":"true"}))
# + users, user_feedback, memory_episodes (recency, no vector), memory_facts

# new: adapters/state/uc/state_store.py
class UCStateStore:                          # satisfies ports.StateStore
    def __init__(self, cfg: UCStorageConfig):
        self._adapter = UCStorageAdapter(WorkspaceClient(), cfg, UC_STATE_REGISTRY)
    async def connect(self):  await self._adapter.initialize()
    async def save_conversation(self, conv):
        await self._adapter.upsert("conversations", _to_row(conv))   # MERGE
    async def get_conversation(self, cid, uid=None):
        return _to_conv(await self._adapter.read_one("conversations", {"conversation_id": cid}))
```

**Why this is the native answer to Ask D:** it reuses the **same `WorkspaceClient`** the auth
resolver already builds (no new credentials, no new network dep), writes governed UC data
(auditable/shareable/lineage-tracked), and needs a running SQL warehouse — infra Databricks
users already have. **Caveat (see open_questions):** SQL-warehouse `statement_execution` writes
are **seconds-latency, low-concurrency** — fit for low-write-rate durable data (users, feedback,
periodic conversation snapshots), NOT per-turn chat at high concurrency. For that, keep
Lakebase/Postgres as an extra.

**UC Volumes** (files API) are the native store for **blobs/artifacts** (large attachments,
exported reports, `.npz` if ever regenerated) — not row state. Use `w.files.upload/download`
against `/Volumes/<catalog>/<schema>/<volume>/…`. `[DOC:uc-volumes]`

## 3. RAG corpus as reference files / query packs

**Today:** `build_analytics_context` (`tools/adapters/rag_tools.py:57`) embeds the query and
does `vector_store.search_multi_collection(collections=[Tables,Nuance,Facets,Codebook], domains)`
(`:133`), truncates per-collection (`:154-158`), and stores a **context handle** returning only a
summary (`:161-174`). It already degrades to empty `RAGContext()` on embedding failure (`:139-149`).

**Native design (deterministic, embedding-free):**

```
knowledge/                                   # shipped in package (progressive disclosure)
  domains/
    finops_billing.md        # curated Tables + Nuance + Facets for this RagResourceDomain
    compute_warehouses.md
    query.md ... (one per RagResourceDomain, resource_domains.py:23-41)
  query_packs/  → reuse discovery/query_packs/*  (~17 packs of correct system-table SQL)
```

`build_analytics_context` becomes:
1. Map the user query's referenced tables → domains via
   `map_system_table_to_rag_resource_domains` (`resource_domains.py:128`), or take the
   LLM-supplied `rag_resource_domains` (already a param, `:60`).
2. Load those domains' reference files + relevant query pack(s) from disk.
3. Store as the same context handle (`:162`) — unchanged downstream contract.

This is exactly the agent-host **progressive-disclosure** pattern (a `SKILL.md` names a
reference file; the model reads it only when the skill fires) — `[DOC:agent-skills]`. Deletes
`sqlite-vec`, the embedding round-trip, the vector-store factory, and the `.npz` bootstrap from
the default path. Vector Search remains the opt-in for scale (§5).

## 4. Native memory / context flow

The insight: **when Starboard runs inside an agent host, the host already owns session memory** —
Starboard need not re-implement it.

- **Ephemeral run/turn state** → `SharedContextProvider` (`services/context/provider.py:96`) is
  already a pure in-memory cache with fetchers (`:128-168`) — no store needed. Keep as-is.
- **Conversation continuity** → the agent host persists the conversation. Claude Code keeps
  session transcripts + **auto memory** (`~/.claude/projects/<project>/memory/`, `MEMORY.md`
  index loaded each session, topic files on demand) and CLAUDE.md carries durable user/project
  context `[DOC:cc-memory]`; for the Agent SDK / API, the **memory tool** (`memory_20250818`)
  gives a client-side `/memories` directory whose storage *you* choose — persisting across
  context resets `[DOC:memory-tool]`, and **context editing/compaction** manage long threads
  `[DOC:context-edit]`. So the Starboard CLI `SessionManager`
  (`cli/sessions/session_manager.py`) can drop `aiosqlite` and either (a) write a JSON session
  index + per-conversation transcript files, or (b) defer entirely to the host session when
  embedded; a hosted deployment can back the memory tool's `/memories` with a **UC Volume**
  (`[DOC:uc-volumes]`) for durable, governed, zero-extra-DB memory.
- **Durable cross-session facts/prefs** (when wanted) → UC `memory_facts`/`users` tables
  (recency queries, no vectors). Semantic recall only if `[memory]`/`[vectorsearch]` opted in.
- **Progressive disclosure** is the memory-efficiency mechanism: skills + reference files load
  into context on demand rather than living in a vector DB. `[DOC:agent-skills]`

## 5. When Vector Search is the right call (escape hatch)

Managed **Databricks Vector Search** (delta-sync index over a UC Delta table, queried via the
same `WorkspaceClient`) is the native replacement **only when** the static-file approach is
insufficient: corpus too large for per-domain files, need for fuzzy cross-domain recall, or
per-tenant custom corpora. It keeps the "no self-managed vector DB" property while restoring ANN.
Gate behind `starboard[vectorsearch]`. `[DOC:vector-search]`

## 6. `pyproject.toml` extras

Move the unconditional block (`pyproject.toml:51-57`) into extras:

```toml
[project.dependencies]           # default install: NO stores beyond these
# ... databricks-sdk, mcp, pydantic, httpx, structlog, orjson, aiofiles, otel ...
# (remove: redis, asyncpg, pgvector, aiosqlite, sqlite-vec)

[project.optional-dependencies]
sqlite       = ["aiosqlite>=0.19,<1", "sqlite-vec>=0.1.1,<1"]
postgres     = ["asyncpg>=0.29,<1"]
lakebase     = ["asyncpg>=0.29,<1"]            # or fold into `postgres`
memory       = ["pgvector>=0.3,<1", "asyncpg>=0.29,<1"]
redis        = ["redis>=5,<6"]
vectorsearch = ["databricks-vectorsearch>=0.x"]  # verify exact pkg/version
all-stores   = ["starboard[sqlite,postgres,redis,memory,vectorsearch]"]
```

**DBR 17.3 alignment (`pyproject.toml:58-77`):** the crypto/cffi/protobuf pins that keep the
default wheel installable on the default cluster must be re-validated against each extra's
transitive deps before release (see open_questions #12). Default wheel gets *smaller*, so the
core stays clean; the risk is confined to opt-in extras.

## 7. Migration & backward-compat

- Keep all Protocols and existing adapters; deletions are limited to *default* deps + the `.npz`
  bootstrap from the default wheel.
- Existing `database_backend=sqlite/postgres/databricks` configs keep working **iff** the
  matching extra is installed; the lazy-import guard (§1) yields an actionable error otherwise.
- Rename `databricks`→`lakebase` with an alias that maps the old value + a deprecation warning,
  so no config hard-breaks.
- Ship UC state behind `database_backend=uc`; it is additive.

## References (verified doc URLs)

| Key | Source | Load-bearing fact |
|---|---|---|
| `[DOC:cc-memory]` | https://code.claude.com/docs/en/memory | Two cross-session mechanisms: **CLAUDE.md** (project/user/enterprise scopes, `@import`, loaded every session) + **auto memory** (Claude writes notes to `~/.claude/projects/<project>/memory/`, `MEMORY.md` index — first 200 lines/25KB loaded each session, topic files read on demand). The host, not Starboard, carries durable user/project context. |
| `[DOC:memory-tool]` | https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool | API/Agent-SDK **memory tool** (`memory_20250818`): client-side `/memories` file directory, **you control storage** (disk, DB, cloud), just-in-time retrieval, persists across sessions/context resets. A Starboard host could back `/memories` with UC Volumes or a local dir — no bespoke memory DB. |
| `[DOC:context-edit]` | https://platform.claude.com/docs/en/build-with-claude/context-editing | Context editing + compaction manage long conversations server/client-side — the native answer to "conversation memory/context" that Starboard's `memory_store` was reimplementing. |
| `[DOC:ctx-eng]` | https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents | Just-in-time / progressive-disclosure context pattern (load references on demand, not up front). |
| `[DOC:agent-skills]` | https://code.claude.com/docs/en/skills | **Progressive disclosure**: "a skill's body loads only when it's used, so long reference material costs almost nothing until you need it." Direct grounding for RAG-corpus-as-reference-files (§3). |
| `[DOC:uc-tables]` | https://docs.databricks.com/aws/en/dev-tools/sql-execution-tutorial | **Statement Execution API**: sync waits up to 10s (configurable 5–50s, or 0 for async+poll); results <25 MiB inline else external S3 URL. Confirms UC-table writes are **seconds-latency**, not OLTP — fine for low-write-rate durable state, not per-turn chat at scale. |
| `[DOC:uc-volumes]` | https://docs.databricks.com/aws/en/volumes/ | UC Volumes: governed path-based file storage `/Volumes/<catalog>/<schema>/<volume>/…` for non-tabular data (blobs/artifacts). Managed vs external; cannot be registered as tables. |
| `[DOC:lakebase]` | https://docs.databricks.com/aws/en/oltp/ | **Lakebase** = fully-managed Postgres in Databricks: low-latency OLTP, scale-to-zero, branching; explicitly recommended as an **agent state store / online feature store**. The honest external-store option for high-concurrency multi-user state. |
| `[DOC:vector-search]` | https://docs.databricks.com/aws/en/generative-ai/vector-search | **Vector Search**: managed delta-sync index over a UC Delta table (Databricks-managed or self-managed embeddings), HNSW ANN + keyword RRF. The opt-in escape hatch when reference files don't scale. |

> Note: `docs.claude.com`/`docs.databricks.com` URLs 301/302-redirect to `code.claude.com`,
> `platform.claude.com`, and `www.databricks.com/<cloud>/en/...` respectively; the URLs above are
> the stable entry points verified 2026-08-26.
