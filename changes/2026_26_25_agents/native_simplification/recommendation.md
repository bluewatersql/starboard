# Native Simplification — Recommendation (Topics C + D)

> Ranked plan to reach a **zero-external-store default** while preserving the Protocol
> layer so nothing hard-breaks. Evidence in `opportunities.md`; APIs in `technical.md`.

## Guiding principle

Keep every `starboard_core/ports/*` Protocol. Change **defaults, packaging, and one new
adapter family** — not the abstraction. A deployment should run the CLI and MCP server with
**no dependency beyond `databricks-sdk` + `mcp`**, and *opt into* heavier stores only when a
real constraint (concurrency, multi-replica, semantic recall) demands it.

Two independent axes:
- **Axis A — remove hard deps (packaging):** move `redis`/`asyncpg`/`pgvector`/`aiosqlite`/
  `sqlite-vec` out of the unconditional block (`pyproject.toml:51-57`) into extras.
- **Axis B — provide native durability (code):** wire the orphaned `UCStorageAdapter` as
  Protocol-compliant state/memory/user/feedback adapters, and replace RAG embeddings with
  reference files.

Ship Axis A first (fast, low-risk), then Axis B (unlocks durable zero-store server).

## Ranked plan

### Rank 1 — Flip defaults to in-memory + make cache/rate-limit store-free (LOE: S)
- `config.py`: keep `cache_backend="memory"` (already default `:141`); ensure `redis_url=None`
  path is the documented default; leave `rate_limit_storage="memory://"` (`:160`).
- No code risk: `create_cache_store` already falls back to `InMemoryCacheStore`
  (`state_factory.py:135-137`).
- **Outcome:** single-instance server needs no Redis. Cache remains Protocol-based so a
  Databricks-SQL-result-cache adapter can slot in later behind `CacheStore`.

### Rank 2 — Move heavy backends to optional extras (LOE: S, packaging only)
- New extras: `starboard[postgres]` (`asyncpg`), `starboard[redis]`, `starboard[memory]`
  (`pgvector`), `starboard[sqlite]` (`aiosqlite`,`sqlite-vec`), `starboard[vectorsearch]`,
  optionally `starboard[lakebase]`.
- Guard imports in `state_factory.py`/`vector_store_factory.py` with lazy import + a clear
  "install `starboard[postgres]`" error when a backend is selected but its extra is absent.
- **Outcome:** default `pip install starboard` wheel carries none of the five stores. This
  directly closes Ask C for the *default* install.

### Rank 3 — RAG corpus → progressive-disclosure reference files (LOE: M–L)
- Author per-domain reference files keyed to `RagResourceDomain` (`resource_domains.py:23-41`)
  from the existing bootstrap packs + `discovery/query_packs/` (~17 packs).
- Rewrite `build_analytics_context` (`tools/adapters/rag_tools.py`) to map query→domains
  (`map_system_table_to_rag_resource_domains`) and load those reference files instead of
  `search_multi_collection`. Keep the token-efficient context-*handle* return (`:161-174`).
- Delete `sqlite-vec` from the default path; embedding provider + vector store become
  `starboard[vectorsearch]`-only.
- **Outcome:** the marquee win — removes embeddings + vector DB from the default analytics
  path. Highest effort, highest payoff. Do this as its own workstream.

### Rank 4 — Wire the native UC-table state adapter family (LOE: M)
- Implement `UCStateStore`/`UCMemoryStore`/`UCUserStore`/`UCFeedbackRepository` over the
  existing `UCStorageAdapter` (`infra/storage/uc_adapter.py`) + `UCRepository` (`repository.py`),
  register conversation/memory/user/feedback `TableDef`s alongside `warehouse_tables.py`.
- Add a `database_backend="uc"` (or repurpose `databricks` → UC, and rename the Lakebase path
  to `lakebase`) branch in `state_factory.py`; generalize the store-type switch in
  `container.py:511-596` (feedback/user repos) so it dispatches on a capability, not `isinstance`.
- Reuses the **same `WorkspaceClient`** as the auth resolver (ties into Topic-4 auth).
- **Outcome:** durable state with **no external DB and no new credentials** — the Databricks-native
  answer to Ask D. Best for low-write-rate durable data (users, feedback, fingerprints,
  periodic conversation snapshots).

### Rank 5 — Replace CLI durable sessions with JSON files / agent-host session (LOE: M)
- `cli/sessions/session_manager.py` is the one hard `aiosqlite` import in the CLI hot path
  (`:12,:76,:108`). Reimplement `cli_sessions` as a JSON index under `~/.starboard/sessions/`
  and per-conversation JSON transcripts (or defer entirely to the agent host's native session
  when embedded in Claude Code — see technical.md §native memory).
- **Outcome:** the thin CLI runs with **no DB driver at all**.

### Rank 6 — Retire dormant memory/reflexion by default (LOE: S)
- `memory_consolidation_enabled=False` (`config.py:155`) and no live consumer; reflexion/semantic
  cache already optional + self-degrading (`container.py:143,195-231`). Make `recall_episodes`
  degrade to `get_recent_episodes` when no vector backend; ship semantic cache TTL-only by default.
- **Outcome:** removes the remaining `sqlite-vec`/`pgvector` pull from the server default.

## What becomes an optional extra vs deleted

| Component | Verdict | Rationale |
|---|---|---|
| `asyncpg` / Postgres adapters | **Extra** `[postgres]` | Real OLTP for high-concurrency multi-user Apps (§ open questions). |
| Lakebase adapter | **Extra** `[lakebase]` (or in `[postgres]`) | Databricks-native OLTP + OAuth already built; keep it. |
| `redis` | **Extra** `[redis]` | Multi-replica cache / rate limiting. |
| `pgvector` + semantic memory | **Extra** `[memory]` | Currently dormant; keep opt-in. |
| `aiosqlite` / `sqlite-vec` | **Extra** `[sqlite]` | Nice local-dev durability; not default. |
| RAG embeddings + vector store factory | **Extra** `[vectorsearch]` | Default path uses reference files; embeddings only for scale. |
| `.npz` bootstrap embeddings | **Delete from default wheel** | Regenerated only when `[vectorsearch]` in use. |
| Orphaned `UCStorageAdapter`/`UCRepository` | **Promote to core** | Becomes the native durable-state backbone. |

## The RAG-to-native-context call (explicit)

**Recommendation: default to reference files + query packs; make Databricks Vector Search the
opt-in escape hatch. Do NOT keep embedded sqlite-vec as a default.**

Why: the corpus is *static, curated, small, and already domain-partitioned*
(`resource_domains.py`), the query packs already encode correct system-table SQL, the agent
already degrades gracefully to empty context (`rag_tools.py:139-149`), and returns handles not
raw text (`:161-174`). Deterministic domain-keyed file lookup gives comparable quality for a
static corpus while removing embeddings, the vector DB, the `.npz` bootstrap, and the compiled
`sqlite-vec` extension (a documented support cost, `container.py:209-223`). Reach for Vector
Search only when the corpus grows past what fits in a per-domain reference file or when fuzzy
cross-domain recall demonstrably improves SQL accuracy.

## Sequencing (dependency-ordered)

```
Rank 1 (defaults) ─┐
Rank 2 (extras)   ─┼─► ship "zero-store single-instance" (Asks C, mostly D)
Rank 6 (dormant)  ─┘
        │
Rank 5 (CLI JSON sessions) ──► thin CLI needs no driver
        │
Rank 4 (UC-table adapters) ──► durable zero-store SERVER
        │
Rank 3 (RAG reference files) ──► removes embeddings from default analytics path  [parallel workstream]
```

Ranks 1/2/6 are a single small PR. Rank 5, 4, 3 are independent follow-on workstreams (3 can
run in parallel since it touches `infra/rag`, not `adapters/state`).

## Tie-ins
- **Topic 4 tiers:** thin CLI (no driver) ↔ default MCP (in-mem + reference files) ↔ durable
  server (UC tables) ↔ scaled App (Postgres/Redis/Vector Search extras).
- **Auth resolver:** the UC-table adapter and Lakebase adapter both reuse the same
  `WorkspaceClient` the auth layer already builds — one credential path.
