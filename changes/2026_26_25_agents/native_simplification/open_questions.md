# Native Simplification — Open Questions

> Unresolved risks for the zero-external-store direction. Each needs a spike/benchmark or a
> product decision before committing the corresponding rank in `recommendation.md`.

## Durability & concurrency of in-memory / native state

1. **In-memory state loss on restart.** `InMemoryStateStore` loses all conversation history
   when the process dies. Inside Databricks Apps the filesystem is ephemeral too. Is per-turn
   durability actually required for the MCP-server persona, or is agent-host session context
   (Claude Code persists the conversation) sufficient so Starboard can be stateless between
   turns? → Decides whether Rank 4 (UC state) is mandatory or optional.

2. **UC Delta tables are not OLTP.** Writes go through SQL-warehouse `statement_execution`
   (`uc_adapter.py:527-533,558-564`): each write is a Delta MERGE/INSERT with **seconds-scale
   latency** and small-file/commit-contention issues under concurrent writers. Open: what is
   the real p50/p95 for a single-row upsert on a serverless SQL warehouse? Is it acceptable for
   (a) per-turn conversation writes, (b) occasional user/feedback writes only? → Likely answer:
   UC tables for low-write-rate durable data; snapshot conversations periodically rather than
   per-turn. Needs a benchmark.

3. **Concurrent-writer semantics on UC tables.** Delta optimistic concurrency can throw
   `ConcurrentAppendException` under many simultaneous writers to the same table/partition.
   How many concurrent users before UC-table state degrades? Partition strategy
   (`partition_by=("warehouse_id",)` in `warehouse_tables.py:170`) helps for analytics tables —
   what's the right partitioning for a `conversations` table (by user_id? by date?)?

4. **Warehouse cold-start / always-on cost.** UC-table state needs a running SQL warehouse.
   Serverless warehouse cold-start adds latency to the first write; keeping one warm adds cost.
   Does this erode the "no infra" win? Compare against the cost/latency of a small Lakebase
   instance.

5. **No transactions across tables.** `UCStorageAdapter` has no multi-table transaction (Delta
   commits are per-table). Cross-entity consistency (e.g., create user + first conversation)
   must be idempotent/eventually-consistent. Is that acceptable for the state model? The current
   Postgres path can do real transactions.

## RAG-to-reference-files

6. **Retrieval quality vs. embeddings.** For a static curated corpus, does deterministic
   domain-keyed file lookup match embedding top-k on real analytics questions? Need an eval set
   (reuse `llm-evaluation`/golden queries) comparing SQL correctness with (a) current sqlite-vec
   RAG, (b) reference-file context, (c) Vector Search. → Gates Rank 3.

7. **Prompt-size blow-up.** Loading a whole domain reference file may exceed the token budget a
   top-k retrieval used. Do per-domain files need sub-chunking, or does the context-handle
   pattern (`rag_tools.py:161-174`) + progressive disclosure keep it bounded?

8. **When is Vector Search unavoidable?** Concretely: corpus size threshold, need for
   cross-domain fuzzy recall, or multi-tenant custom corpora. Define the trigger so teams know
   when to `pip install starboard[vectorsearch]` rather than guessing.

## Memory / semantic features

9. **Is long-term memory wanted at all?** `memory_consolidation_enabled=False` (`config.py:155`)
   and no live consumer of `MemoryConsolidationService` (`services/memory/memory_consolidation.py:144`).
   Is episodic/semantic memory a real roadmap feature or dead weight? If roadmap → Vector Search;
   if not → delete the memory_store embedding surface, keep recency-only.

10. **Semantic cache value.** How often does the semantic (fuzzy) LLM cache hit vs. exact-match
    TTL cache in practice? If the fuzzy uplift is small, TTL-only (already the fallback,
    `container.py:195-198`) removes the last vector dependency with negligible loss.

## Packaging & compatibility

11. **Lazy-import UX.** When a user selects `database_backend=postgres` without
    `starboard[postgres]`, the failure must be a clear actionable message, not an ImportError
    deep in `state_factory`. What's the pattern (import-guard + custom exception)?

12. **DBR 17.3 runtime alignment.** `pyproject.toml:58-77` pins cryptography/cffi/protobuf to
    match the default cluster with zero package changes. Do the extras (`asyncpg`, `redis`,
    Vector Search client) introduce transitive deps that violate those pins on DBR 17.3? Needs a
    dependency-resolution check per extra.

13. **`container.py` type-switch generalization.** `feedback_repo`/`user_store`
    (`container.py:511-596`) dispatch via `isinstance` on the state store. Adding UC adapters
    means either extending the ladder or refactoring to capability-based dispatch. Which is less
    risky given current test coverage?

## Deployment persona

14. **Multi-user App hosting is the honest external-store case.** A horizontally-scaled
    Databricks App serving many concurrent users with per-turn durable state + shared cache is
    where Postgres/Lakebase + Redis genuinely win. Confirm this persona exists on the roadmap; if
    so, the extras are load-bearing, not legacy — document the decision matrix (users, QPS,
    replicas → backend) so it's a deliberate opt-in.
