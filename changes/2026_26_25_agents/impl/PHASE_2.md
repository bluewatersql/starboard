# Phase 2 — Native Architecture + Capability Depth: Detailed Implementation Plan

> Execution-ready plan for the Phase-2 items (C1, C2, C3, C4, the **C5 Phase-2 slice**, D4, D5)
> from [`../UNIFIED_PLAN.md`](../UNIFIED_PLAN.md) § Phase 2. Design detail is drawn from each topic's
> `technical.md`; this plan turns it into ordered tasks with file targets, TDD test plans, acceptance
> criteria, and back-compat rules. **Baseline: starboard 0.1.1; Phase 0 (A1–A5) is landed on `main`
> (`091ab2ed`); Phase 1 (B1/B2/B3/B4/B6 + D2/D3) is the plan of record and its deliverables
> — the kernel carve-out, the `starboard_x` middle tier, the extras taxonomy, and the shared `Finding`
> schema — are **prerequisites for D4** (see §11 deps).**
>
> Repo anchors below were verified against current code on 2026-08-26. Databricks Vector Search,
> Statement Execution, UC Volumes, and the D5 system tables were re-verified against live docs
> (URLs in §3) on 2026-08-26.

## 0. Goal & definition of done (phase-level)

**Goal:** remove the last external stores from the default and durable-server paths, deepen analysis
depth, and express internal-augmentable capabilities as **ports with working public adapters behind a
closed-by-default gate** — with **no capability regression** and the **public path free of internal
data** (the gate becomes the enforced governance boundary, UNIFIED_PLAN §3.5/§7).

Phase 2 runs as **two independent workstreams** (UNIFIED_PLAN §4):
*2a native* (C1 · C2 · C3 · C4) and *2b depth* (C5-slice · D4 · D5). B6 (optional-MCP toggle) is
tracked under Phase 1 in this repo (PHASE_1 PR5) and is **not** re-planned here.

**Phase-2 exit criteria (all must hold):**
1. The analytics agent builds context from **reference files + query packs on disk** — no embedding
   round-trip, no `sqlite-vec`, no `.npz` bootstrap on the default path; `build_analytics_context`
   resolves domains → files deterministically. *(C1)*
2. `vector_backend="none"` (reference-file path) is the **default**; embeddings/ANN move behind
   `starboard[vectorsearch]` and, when enabled, use **managed Databricks Vector Search** (not a
   self-managed store). *(C1)*
3. `database_backend="uc"` builds Protocol-compliant `UCStateStore` / `UCMemoryStore` /
   `UCUserStore` / `UCFeedbackRepository` over the (previously orphaned) `UCStorageAdapter`/
   `UCRepository`, reusing the **same `WorkspaceClient` the auth resolver (A1) builds** — no new
   credentials. The Phase-0/1 `_uc_not_implemented()` stubs are gone. *(C2)*
4. The CLI session store runs with **no `aiosqlite` on the hot path**: `SessionManager` persists a
   JSON session index + per-conversation transcript files (or defers to the agent host). *(C3)*
5. Dormant memory/reflexion is **retired by default**: reflexion + episodic vector recall are off and
   gated behind `[memory]`/`[vectorsearch]`; the semantic cache is **TTL-only** (exact-key) by default
   with no vector dependency. *(C4)*
6. Four **ports** (`LogRetrievalPort`, `DiagnosticBackendPort`, `NLQueryPort`, `FleetSqlPort`) exist
   with **working PUBLIC adapters** and a **closed-by-default employee-context detection hook** on the
   auth resolver. The additive invariant holds (closing the gate leaves a fully-functional public
   path); **internal adapters are explicitly Phase 3.** *(C5 slice)*
7. Progressive-helper depth ships as `starboard_x` sub-commands on the Phase-1 extras taxonomy:
   `discovery run --data-only`, `sparklog parse`, and **pure** `warehouse analyze` / `uc analyze`
   analyzers — each emitting the Phase-0 JSON envelope + exit codes. *(D4)*
8. New data packs land on public `system.*`: **compute reliability/right-sizing** and
   **column-lineage**; **discovery result caching** dedupes hot-table scans within a run (and across
   runs with TTL). *(D5)*
9. **Governance grep** of all shipped public artifacts (wheel content, reference files, packs, ports +
   public adapters) finds **no** internal namespaces (`centralized_system_tables`, `fin_live_gold`,
   logfood workspace, ClickHouse, `hmr_stack_hash`, `go/…`, team keys). Internal identifiers appear
   only inside gated internal-adapter code paths — of which **none ship in Phase 2**. *(§3.5/§7)*
10. Repo-wide gates green: `ruff`, `mypy`, `pytest`, **import-linter** (kernel boundary from Phase-1
    B1 stays green — reference-file loaders and ports must not drag `databricks-sdk` into the kernel).

**Phase 2 is unblocked by Phase 0** and gated on three owner/validation inputs (UNIFIED_PLAN §6):
the RAG-fidelity validation (C1), the UC-table latency/concurrency validation (C2), and the
**employee-context detection signal** for the gate (C5, tied to the open OWNER gate — see D-2.7).

## 1. Guardrails (apply to every task)

- **TDD:** write the failing test(s) first, then implement to green. Each task lists its tests.
- **Additive / back-compat:** every existing import path, config value, flag, and store backend keeps
  working. `database_backend=sqlite|postgres|databricks` still resolve *iff* their extra is installed
  (Phase-0 A3 lazy-import guard). `vector_backend=inmemory|sqlite` stay selectable. Adding `uc` state
  and `none` vector paths is **additive**; the RAG context-handle downstream contract is unchanged.
- **No capability regression** — the UNIFIED_PLAN gate invariant (§3.5). For C5, closing the gate must
  never remove or degrade a capability; the public adapter is the complete, universal path.
- **Public path stays clean** — internal namespaces never enter shipped artifacts (governance §7);
  every `$` on the public adapter is a **list-price estimate**. No internal adapters ship this phase.
- **Kernel boundary holds** — the Phase-1 import-linter contract must stay green: reference-file
  loaders, ports, and pure analyzers must not import `databricks-sdk`/`openai`/`fastapi`/`mcp`.
- **Verification per task:** `ruff check`, `mypy`, `lint-imports`, and the task's pytest selection must
  pass before the task is "done".
- **Evidence:** cite `file:line`; reference the topic `technical.md` rather than re-deriving design.

## 2. Branch & PR strategy

Off `main` (Phase-0 landed; Phase-1 assumed merged before D4). Seven reviewable PRs; sizes follow §11
ordering. Workstreams **2a** and **2b** are independent and parallelizable.

| PR | Item | Workstream | Branch | Rough size |
|----|------|-----------|--------|-----------|
| 1 | C1 RAG → reference files + query packs; Vector Search behind `[vectorsearch]` | 2a | `phase2/rag-reference-files` | M–L |
| 2 | C4 retire dormant memory/reflexion; semantic cache TTL-only | 2a | `phase2/retire-memory-reflexion` | S |
| 3 | C2 native UC-table state (`UCStateStore`/`UCMemoryStore`/`UCUserStore`/`UCFeedbackRepository`) + `database_backend="uc"` | 2a | `phase2/uc-native-state` | M |
| 4 | C3 JSON/agent-host CLI sessions (drop `aiosqlite`) | 2a | `phase2/json-cli-sessions` | M |
| 5 | C5 port interfaces + PUBLIC adapters + employee-context gate hook | 2b | `phase2/ports-public-adapters` | M |
| 6 | D5 new packs (compute reliability/right-sizing, column-lineage) + discovery result caching | 2b | `phase2/new-packs-caching` | M |
| 7 | D4 progressive-helper depth (`discovery data_only`, `sparklog`, `warehouse`/`uc` analyzers) | 2b | `phase2/progressive-helper-depth` | M–L |

Dependency edges (see §11): C1↔C4 both touch the RAG/foundation init (sequence C1→C4 or coordinate);
C2 needs the A1 resolver (landed) + reuses the orphaned UC storage layer; C3 is independent; C5 needs
A1 (gate hook) + reuses the log-parser/diagnostic substrate; D5 independent; **D4 needs Phase-1 B1/B2
(`starboard_x` + extras taxonomy) merged first**. Each PR: reviewed with `/review`, gates green, merged.

## 3. Decisions to lock before coding

Format/API facts below are **verified** against the live docs (fetched 2026-08-26):
- Databricks Vector Search (managed delta-sync index, `VectorSearchClient`):
  <https://docs.databricks.com/aws/en/generative-ai/vector-search> ·
  PyPI `databricks-vectorsearch` **0.75** (2026-06-10): <https://pypi.org/project/databricks-vectorsearch/> ·
  Python client API: <https://api-docs.databricks.com/python/vector-search/databricks.vector_search.html>
- Statement Execution API (`wait_timeout` default 10s / `0s` or `5s–50s`; inline ≤ **25 MiB** else
  `EXTERNAL_LINKS`): <https://docs.databricks.com/aws/en/dev-tools/sql-execution-tutorial>
- UC Volumes files API (`w.files.upload_from/download_to/upload/download`, `/Volumes/<cat>/<sch>/<vol>/…`;
  SDK ≥ 0.72 supports any size): <https://databricks-sdk-py.readthedocs.io/en/stable/workspace/files/files.html>
  · <https://docs.databricks.com/aws/en/volumes/>
- D5 system tables: column lineage `system.access.column_lineage` (1-yr retention):
  <https://docs.databricks.com/aws/en/admin/system-tables/lineage> · compute
  `system.compute.{node_timeline,instance_events (Public Preview),warehouse_events}`:
  <https://docs.databricks.com/aws/en/admin/system-tables/compute> ·
  <https://docs.databricks.com/aws/en/admin/system-tables/warehouse-events>
- Agent-Skills progressive disclosure (reference files load on demand):
  <https://code.claude.com/docs/en/skills>

| # | Decision | Recommendation |
|---|----------|----------------|
| D-2.1 | **C1 reference-file format & location** | **Ship curated Markdown, one file per `RagResourceDomain`, as package data** under `packages/starboard-core/starboard_core/rag/knowledge/domains/<domain>.md` (kernel-tier so both the server and `starboard_x` can read it; keeps the import-linter clean — plain file reads, no SDK). Body carries the Tables/Nuance/Facets/Codebook sections the collections held today; front-matter names the domain + the system tables it covers. Reuse `discovery/query_packs/*` in-place as the SQL corpus (no copy). This is the verified progressive-disclosure pattern ([DOC:agent-skills]). |
| D-2.2 | **C1 domain-mapping source** | Reuse the existing `map_system_table_to_rag_resource_domains` (`starboard_core/rag/resource_domains.py:128`) + the already-present `rag_resource_domains` param (`rag_tools.py:60`). No new taxonomy — the file lookup is keyed by the same `RagResourceDomain` enum used today. |
| D-2.3 | **Vector Search opt-in boundary** | Default analytics path is **reference files (`vector_backend="none"`)**. Keep `sqlite-vec` selectable under `starboard[sqlite]` for local/offline ANN; **re-point the `[vectorsearch]` extra from `sqlite-vec` to `databricks-vectorsearch>=0.75,<1`** (managed delta-sync index over a UC Delta table, same `WorkspaceClient`). Vector Search is the escape hatch (large corpus / cross-domain fuzzy recall / per-tenant corpora) — never on the default path. **Lock the pin at 0.75** (latest, 2026-06-10). |
| D-2.4 | **Does `database_backend="uc"` become a default anywhere?** | **No — stays opt-in.** Default remains `memory` (dev). `uc` is the **recommended durable server backend** for low-write governed state (users, feedback, periodic conversation snapshots) but is never auto-selected. Document it as the "durable, zero-external-DB" server choice; per-turn high-concurrency chat still points at Lakebase/Postgres (extra). Rationale: Statement Execution writes are seconds-latency, low-concurrency ([DOC:stmt-exec]). |
| D-2.5 | **`databricks`→`lakebase` rename (deferred from Phase-0 D-0.5)** | **Do it in C2's PR:** rename the `databricks` backend literal to `lakebase`, keep `databricks` as a deprecated alias (map + one-time warning) so no config hard-breaks. This disambiguates from the new `uc` (Statement-Execution) backend, which is the *actual* Databricks-native option. |
| D-2.6 | **Which state maps to UC vs. Lakebase** | UC (Statement Execution, seconds-latency): **users, feedback, cross-session facts/prefs, periodic conversation snapshots**. Lakebase/Postgres (extra): **high-concurrency per-turn conversation state**. `UCMemoryStore` is **recency-only, no vectors** (semantic recall stays behind `[vectorsearch]`). UC Volumes ([DOC:uc-volumes]) is the blob store for large artifacts/exports, not row state. |
| D-2.7 | **C5 gate — employee-context detection signal** (ties to the open OWNER gate) | Default **closed** (public path). Recommend a **three-signal detector on the auth resolver**: (1) resolved workspace host in an **internal allowlist** (e.g. `e2-demo-field-eng`, configurable, never hard-coded to a customer host), (2) **Isaac-managed identity** present, (3) **presence of internal MCP tools / entitlements** (`mcp__logs-summariser__*`, `mcp__dbr-doctor__*`). Open only when **≥1 context signal AND authorized (employee)**. Reuse `describe_auth()` (`infra/auth/resolver.py:154`) — it already exposes `host`/`user`. **Flag to OWNER:** the exact allowlist + entitlement check is a policy decision; ship the hook + a config-driven allowlist, default empty ⇒ closed. **No internal adapter is wired this phase**, so a wrong signal cannot leak data — it only decides which (currently public-only) adapter is chosen. |
| D-2.8 | **C3 JSON session schema & location** | Index at `~/.starboard/sessions/index.json` (`{version, sessions: [{session_name, conversation_id, user_id, created_at, updated_at, turn_count, last_message_preview}]}`); per-conversation transcript at `~/.starboard/sessions/<conversation_id>.json` (`{conversation_id, user_id, messages: [...], metadata}`). Atomic writes (temp-file + `os.replace`). When embedded in an agent host, **defer to the host session** and skip the file store entirely (host owns memory — [DOC:cc-memory]). Keep `SessionManager`'s public API (`get_or_create/list_sessions/delete_session/update_session_activity`) byte-for-byte. |
| D-2.9 | **C4 retirement mechanism** | `enable_reflexion` already defaults `False` (`config.py:179`) — finish the job: (a) flip `enable_semantic_cache` to a **TTL-only exact-key** implementation with **no vector store** (drop the `similarity_threshold` path from the default); (b) gate the reflexion store + episodic vector recall + semantic-similarity cache behind `[memory]`/`[vectorsearch]`, lazy-imported so a no-extras install never touches `sqlite-vec`. Keep the `MemoryStore` Protocol and all adapters — only defaults + wiring change. |
| D-2.10 | **C5 port home** | Put the four Protocols in **`starboard_core/ports/`** (kernel-tier, alongside `state_store.py`/`memory_store.py`) so they stay SDK-free (public adapters live in `starboard`/`starboard_x`, internal adapters attach in Phase 3). This keeps the import-linter boundary intact and lets the diagnostic trio consume `LogRetrievalPort`/`DiagnosticBackendPort` outputs. |

---

## 4. Task C1 — RAG → progressive-disclosure reference files + query packs

**Source design:** `native_simplification/technical.md` §3, §5, §6. **Objective:** replace the embedding
round-trip in the default analytics path with deterministic, on-disk reference-file lookup keyed by
`RagResourceDomain`; keep the context-handle downstream contract; move Vector Search behind an extra.

**Repo grounding (verified):**
- `build_analytics_context` (`tools/adapters/rag_tools.py:57`) embeds the query and calls
  `vector_store.search_multi_collection(collections=[Tables,Nuance,Facets,Codebook], domains=…)`
  (`:133`), truncates per-collection (`:154-158`), stores a **context handle** returning a summary
  (`:161-174`), and already **degrades to empty `RAGContext()`** on `AdapterError|ValueError`
  (`:139-149`) — the escape hatch the file path formalizes.
- Domain mapping already exists: `map_system_table_to_rag_resource_domains`
  (`starboard_core/rag/resource_domains.py:128`); `rag_resource_domains` is already a param (`:60`).
- `vector_backend` literal (`config.py:150`) is `inmemory|sqlite|chroma|databricks|postgres`, default
  `inmemory` — **no `none` yet** (Phase-0 D-0.3 deferred it here).
- `[vectorsearch]` extra currently resolves to **`sqlite-vec`** (`packages/starboard/pyproject.toml:107-108`)
  — wrong target; D-2.3 re-points it to managed Vector Search.
- Vector store creation: `infra/rag/services/vector_store_factory.py` (SQLite-vec → in-memory → None).

**Files:**
| File (anchor) | Change |
|---|---|
| `packages/starboard-core/starboard_core/rag/knowledge/domains/<domain>.md` (new, ×N `RagResourceDomain`) | curated Markdown reference files (Tables/Nuance/Facets/Codebook sections) per D-2.1; shipped as package data |
| `packages/starboard-core/starboard_core/rag/reference_loader.py` (new) | pure, SDK-free loader: `load_domain_references(domains, sections) -> RAGContext`; reads the `knowledge/` files + the relevant `query_packs/*` SQL; deterministic, no embeddings |
| `tools/adapters/rag_tools.py:57-181` | `build_analytics_context` maps query→domains (`resource_domains.py:128`) or takes `rag_resource_domains`; loads reference files via the new loader; stores the **same context handle** (`:162`) — unchanged downstream contract; keep the empty-context escape hatch |
| `infra/core/config.py:150-152` | add `"none"` to the `vector_backend` literal; **default → `"none"`** (D-2.3); keep `inmemory`/`sqlite` selectable |
| `infra/rag/services/vector_store_factory.py` | `none` → return `None` (reference-file path, no vector store); `vectorsearch` → managed `VectorSearchClient` adapter (new, behind extra); `sqlite` still lazy-guarded |
| `infra/rag/adapters/storage/databricks_vector_store.py` (new) | managed Vector Search adapter (`create_delta_sync_index`, query via `WorkspaceClient`), behind `[vectorsearch]`, lazy-imported |
| `packages/starboard/pyproject.toml:107-108` | re-point `vectorsearch = ["databricks-vectorsearch>=0.75,<1"]`; move `sqlite-vec` under `[sqlite]` only |
| `infra/core/container.py:146-203` | when `vector_backend="none"`, skip vector-store/embedding init in `_initialize_foundation_components` (coordinate with C4) |

**Back-compat:** downstream `store_rag_context`/context-handle contract is unchanged; the empty-context
degrade path stays. `vector_backend=inmemory|sqlite` still work (opt-in). No `.npz` bootstrap on the
default path (it was already optional). Existing `rag_resource_domains` callers unaffected.

**Tests (write first)** — `packages/starboard-core/tests/unit/rag/test_reference_loader.py` +
`packages/starboard/tests/unit/tools/adapters/test_rag_tools_reference.py`:
- `load_domain_references(["finops_billing"])` returns a populated `RAGContext` from disk with **no**
  embedding call and **no** `sqlite_vec`/`databricks.vector_search` import (subprocess `sys.modules`
  assertion — proves the default path is store-free)
- every `RagResourceDomain` has a matching `knowledge/domains/<domain>.md` (parametric completeness test)
- `build_analytics_context` with `vector_backend="none"` returns a valid context handle + summary;
  an unknown domain degrades to empty context (no exception)
- packaging: `databricks-vectorsearch` present in the `[vectorsearch]` extra, `sqlite-vec` absent from
  it (parse pyproject); default install imports `rag_tools` with no vector driver
- **governance:** no internal namespace/`go/` link in any `knowledge/` file (grep in test)

**Acceptance:** default analytics runs on reference files with no embeddings/`sqlite-vec`; enabling
`[vectorsearch]` restores managed ANN; the context-handle contract is intact. **LOE: M–L** (the file
authoring + loader is the bulk; the Vector Search adapter is small and isolated). **Open validation
(UNIFIED_PLAN §6):** confirm reference files match embedding retrieval for SQL accuracy — escape hatch
is Vector Search.

---

## 5. Task C4 — Retire dormant memory/reflexion; semantic cache TTL-only

**Source design:** `native_simplification/technical.md` §4, §1. **Objective:** finish removing the
dormant learning subsystem from the default path and make the semantic cache a dependency-free TTL
cache; keep the `MemoryStore` Protocol + adapters for opt-in use.

**Repo grounding (verified):** `enable_reflexion` already defaults `False` (`config.py:179`);
`enable_semantic_cache` defaults `True` (`:180`) with a `semantic_cache_threshold=0.95` **vector**
path (`:159`). `_initialize_foundation_components` (`container.py:146`) builds a `SQLiteReflexionStore`
on a `sqlite-vec` vector store (`:160-193`) and a `SemanticCache` that **reuses the reflexion vector
store** (`:199-203`). So today, even with reflexion off, `enable_semantic_cache=True` can pull the
vector path.

**Files:**
| File (anchor) | Change |
|---|---|
| `infra/core/config.py:158-159,179-180` | make the semantic cache **TTL-only** by default: keep `enable_semantic_cache=True` but route to an exact-key TTL cache (no `similarity_threshold`); keep `enable_reflexion=False`; document both as opt-in-vector behind `[vectorsearch]` |
| `infra/cache/…` (`SemanticCache`) | add/point to a TTL-only exact-key implementation (reuse the existing in-memory cache + `cache_ttl`); the vector-similarity variant is selected only when `[vectorsearch]` + a threshold is explicitly set |
| `infra/core/container.py:146-229` | lazy-import reflexion + vector paths **inside** the `enable_reflexion`/vector branches; a no-extras install must complete `_initialize_foundation_components` with **no** `sqlite-vec` import; keep the try/except degrade |
| `packages/starboard/pyproject.toml` | ensure reflexion/semantic-vector deps live only under `[memory]`/`[vectorsearch]` (coordinate with C1's `sqlite-vec` move) |

**Back-compat:** `MemoryStore` Protocol + all adapters unchanged; setting `enable_reflexion=True` (with
`[memory]`) restores the old behavior; a threshold + `[vectorsearch]` restores semantic-similarity
caching. Default behavior is strictly lighter, not different in output correctness.

**Tests (write first)** — `packages/starboard/tests/unit/infra/core/test_foundation_lean.py`:
- default config: `_initialize_foundation_components` runs with **no** `sqlite_vec` import (subprocess
  `sys.modules` assertion)
- semantic cache hit/miss works TTL-only with no vector store present; expiry honored (`cache_ttl`)
- `enable_reflexion=True` without `[memory]` raises the actionable install error (Phase-0 `_require`)
- output parity: a query that hit the cache before still hits it (exact-key) — no capability regression

**Acceptance:** fresh install initializes foundation components with no vector driver; semantic cache is
TTL-only; reflexion/vector are opt-in and actionable when absent. **LOE: S.**

---

## 6. Task C2 — Native UC-table state adapter + `database_backend="uc"`

**Source design:** `native_simplification/technical.md` §1, §2, §7. **Objective:** promote the orphaned
`UCStorageAdapter`/`UCRepository` into Protocol-compliant state/memory/user/feedback stores selected by
`database_backend="uc"`, reusing the A1 resolver's `WorkspaceClient`.

**Repo grounding (verified — the building blocks exist and are unused):**
- `UCStorageAdapter` (`infra/storage/uc_adapter.py:83`) — Delta CRUD via `statement_execution`
  (`:527-533`, `wait_timeout` 30s/60s), auto-creates catalog/schema/tables (`:130-201`), MERGE upsert
  (`:412-446`), SQL-injection defense (identifier allowlist `:489-512` + value escaping `:650-678`),
  async via `run_databricks_sync`. Builds a **bare `WorkspaceClient()`** today — must be swapped for the
  resolver's client.
- `UCRepository[T]` (`infra/storage/repository.py:19`) — typed `get/list/save/delete`, handles
  dataclass + Pydantic (`:152-194`).
- `TableRegistry`/`TableDef`/`ColumnDef` (`infra/storage/table_registry.py`) + worked example
  (`warehouse_tables.py`).
- Target Protocols: `StateStore` (`ports/state_store.py:10` — `get/set/delete` +
  `get_conversation/save_conversation/delete_conversation/list_conversations/update_metadata`),
  `MemoryStore` (`ports/memory_store.py:10`), plus the container's `user_store`/`feedback_repo`.
- Factory stubs to replace: `state_factory.py:54-60` (`_uc_not_implemented`), `:86-87` (state),
  `:221-226` (memory) — all raise "not yet implemented (Phase 2)". `database_backend` already includes
  the `"uc"` literal (`config.py:130-132`, reserved in Phase 0).
- Container dispatch is an **`isinstance` ladder** on the state store: `feedback_repo`
  (`container.py:490-534`) and `user_store` (`:536-596`) branch on `SQLiteStateStore`/
  `InMemoryStateStore`/else-Postgres — must be generalized so `UCStateStore` supplies its own
  user/feedback stores (native_simplification §1 "capability dispatch" note).

**Files:**
| File (anchor) | Change |
|---|---|
| `packages/starboard/starboard/adapters/state/uc/tables.py` (new) | register `conversations`, `users`, `user_feedback`, `memory_episodes` (recency, no vector), `memory_facts` as `TableDef`s (JSON blobs as `STRING`; `partition_by=("user_id",)`; `delta.autoOptimize.optimizeWrite`) — per native_simplification §2 sketch |
| `packages/starboard/starboard/adapters/state/uc/state_store.py` (new) | `UCStateStore` satisfying `ports.StateStore` over `UCRepository`/`UCStorageAdapter`; `connect()` → `adapter.initialize()`; MERGE-based `save_conversation`; `get_conversation`/`list_conversations`/`update_metadata`/`delete_conversation` + generic `get/set/delete`; JSON (de)serialization of `messages`/`metadata` |
| `packages/starboard/starboard/adapters/state/uc/memory_store.py` (new) | `UCMemoryStore` satisfying `ports.MemoryStore` — recency queries only (`get_recent_episodes`, `store_fact`, `query_facts`, `get_profile`, `update_profile`, `delete_user_data`); `recall_episodes` (semantic) raises/falls back unless `[vectorsearch]` (additive) |
| `packages/starboard/starboard/adapters/state/uc/user_store.py`, `feedback_repository.py` (new) | `UCUserStore` / `UCFeedbackRepository` over `UCRepository` |
| `infra/storage/uc_adapter.py:112-128` | accept an injected `WorkspaceClient` (from the resolver) rather than constructing a bare one; keep the signature back-compat (optional arg) |
| `infra/core/state_factory.py:54-60,86-87,221-226` | replace `_uc_not_implemented` with real construction: `backend=="uc"` → build via `resolve_workspace_client(WorkspaceTarget.resolve(cfg=config))` + `UCStorageConfig.from_env()`; wire `UCStateStore`/`UCMemoryStore` |
| `infra/core/container.py:490-596` | generalize the `isinstance` ladder to a capability hook (e.g. optional `state_store.get_user_store()`/`get_feedback_repo()`), so `UCStateStore` supplies its own; keep the existing SQLite/Postgres/InMemory branches |
| `infra/core/config.py` (backend literal + rename) | apply D-2.5: `databricks`→`lakebase` with a deprecated alias; document `uc` as the durable-server opt-in |

**Back-compat:** all existing backends unchanged; `uc` is additive. The `databricks` literal keeps
working via the `lakebase` alias + deprecation warning. `UCStorageAdapter`'s bare-client path stays
valid (injected client is optional). Protocol signatures unchanged.

**Tests (write first)** — `packages/starboard/tests/unit/adapters/state/uc/`:
- `UCStateStore` satisfies `StateStore` (structural/`isinstance`-Protocol check); round-trip
  `save_conversation`→`get_conversation` against a **mocked** `UCStorageAdapter` (assert MERGE SQL for
  upsert; JSON (de)serialization of messages)
- `UCMemoryStore` satisfies `MemoryStore`; `get_recent_episodes`/`query_facts` issue recency SQL;
  `recall_episodes` (semantic) degrades cleanly without `[vectorsearch]`
- `state_factory` with `database_backend="uc"` builds `UCStateStore` and calls the resolver (mock
  `resolve_workspace_client`) — **not** a bare `WorkspaceClient`; the `_uc_not_implemented` stub is gone
- container capability dispatch returns `UCUserStore`/`UCFeedbackRepository` for a UC state store (no
  `isinstance`-ladder fallthrough to Postgres)
- `databricks`→`lakebase` alias maps + warns; old configs don't break
- SQL-injection defenses still hold on the new tables (invalid column raises `InvalidColumnError`)

**Acceptance:** `DATABASE_BACKEND=uc` + a warehouse yields durable governed state over Delta with no
external DB, reusing the resolver's client. **LOE: M.** **Open validation (UNIFIED_PLAN §6):** confirm
UC-table latency/concurrency is adequate for the chosen state (D-2.6) — per-turn chat stays on Lakebase.

---

## 7. Task C3 — JSON / agent-host CLI sessions (drop `aiosqlite`)

**Source design:** `native_simplification/technical.md` §4. **Objective:** the thin CLI needs no DB
driver — replace the `aiosqlite`-backed CLI session store with a JSON session index + per-conversation
transcript files, or defer to the agent host when embedded.

**Repo grounding (verified):** `SessionManager` (`cli/sessions/session_manager.py`) imports
`aiosqlite` (`:12`), constructs a `SQLiteStateStore` + `ConversationRepository` (`:76-77`), opens a raw
`aiosqlite` connection (`:108`), and manages a `cli_sessions` table (`_CLI_SESSIONS_SCHEMA` `:32-43`).
Public API: `connect/close/get_or_create/list_sessions/delete_session/update_session_activity`.

**Files:**
| File (anchor) | Change |
|---|---|
| `cli/sessions/session_manager.py` | replace the `aiosqlite`/`SQLiteStateStore` internals with a JSON store per D-2.8: `index.json` + per-conversation transcript JSON; atomic writes; **keep the public API + `SessionInfo` shape byte-for-byte** |
| `cli/sessions/json_store.py` (new) | small JSON index/transcript reader-writer (stdlib `json` + `os.replace`); no external deps |
| `cli/sessions/__init__.py:1-` | export the JSON-backed manager; keep the import path stable |
| CLI wiring (session entry points) | when running embedded in an agent host, prefer host-owned session/memory and skip the file store (config/env flag) — [DOC:cc-memory] |

**Back-compat:** the `SessionManager` public methods + `SessionInfo` are unchanged, so CLI callers are
untouched. `ConversationRepository` remains available for callers that want the state store; the CLI
default no longer requires `aiosqlite`. (Optional: a one-shot import of an existing `sessions.db` — not
required for DoD.)

**Tests (write first)** — `packages/starboard/tests/unit/cli/sessions/test_json_session_manager.py`:
- `get_or_create` creates + returns `SessionInfo`; re-get returns the same session (JSON index round-trip)
- `list_sessions` ordered by `updated_at` DESC; `update_session_activity` increments `turn_count` +
  sets preview; `delete_session` removes index entry + transcript file
- **no `aiosqlite` import** on the CLI session path (subprocess `sys.modules` assertion)
- atomic write: an interrupted write leaves the previous index intact (temp-file + replace)
- unknown session name → `update_session_activity` raises `ValueError` (parity with today `:295-296`)

**Acceptance:** `starboard` CLI multi-turn sessions work with no `aiosqlite` on the hot path; a
no-extras install runs the session flow. **LOE: M.**

---

## 8. Task C5 (Phase-2 slice) — Port interfaces + PUBLIC adapters + gate hook

**Source design:** `starboard_optimization/technical.md` §2; UNIFIED_PLAN §3.5, §7. **Objective:**
define the four ports, ship **working public adapters**, and add a **closed-by-default employee-context
detection hook** on the auth resolver. **Internal adapters are Phase 3 (D6/D7) — none ship here.**

**Repo grounding (verified):** hexagonal seam already demonstrated by `log_parser/loaders/protocols.py`
+ concrete loaders (`dbfs/s3/https/json/local_file`). The diagnostic substrate the public
`DiagnosticBackendPort` wraps is the Phase-1 trio (`evidence_extractor`/`root_cause_synthesizer`). The
`AnalyticsSqlAdapter` backing for `NLQueryPort` is `tools/domain/analytics_sql/llm_sql_generator.py`.
The gate reuses the A1 resolver (`infra/auth/resolver.py`): `WorkspaceTarget.resolve()` (host/identity)
+ `describe_auth()` (`:154`, exposes `host`/`user`).

**Ports (kernel-tier, D-2.10) — `packages/starboard-core/starboard_core/ports/`:**
| Port (new file) | PUBLIC adapter (ships now) | Internal adapter (Phase 3 — stub only) |
|---|---|---|
| `log_retrieval.py` `LogRetrievalPort.fetch(LogQuery)->LogBundle` | `SdkDbfsLogAdapter` over existing `log_parser/loaders/dbfs.py` (cluster log-delivery paths) | `LogsSummariserAdapter` (`mcp__logs-summariser__*`) — **Phase 3** |
| `diagnostic_backend.py` `DiagnosticBackendPort.classify()/analyze()` | `NativeDiagnosticAdapter` over the Phase-1 extractors + parser | `DbrDoctorAdapter` — **Phase 3** |
| `nl_query.py` `NLQueryPort.ask(question, ctx)->NLAnswer` | `AnalyticsSqlAdapter` over `llm_sql_generator.py` | `GenieAdapter` (`ask_genie`) — **Phase 3** |
| `fleet_sql.py` `FleetSqlPort` | single-workspace `system.*` executor (existing pack path) | `CentralizedTablesAdapter` namespace-rewrite — **Phase 3** |

**Files:**
| File | Change |
|---|---|
| `starboard_core/ports/{log_retrieval,diagnostic_backend,nl_query,fleet_sql}.py` (new) | the four `Protocol`s + their DTOs (`LogQuery`/`LogBundle`, `Candidate`/`DiagnosticResult`, `NLAnswer`, fleet query ctx) — pure, SDK-free |
| `starboard/adapters/ports/{sdk_dbfs_log,native_diagnostic,analytics_sql,single_workspace_fleet}.py` (new) | the four **public** adapters wrapping existing code (no new capability, just the port surface) |
| `infra/auth/resolver.py` (extend) | add `detect_employee_context(target|client) -> EmployeeContext` (D-2.7): host-allowlist (config-driven, default empty) + Isaac-identity + internal-MCP-presence signals; **default closed**; reuse `describe_auth()` |
| `starboard/ports/registry.py` (new) | port→adapter selection: **always public** in Phase 2; a `gate_open` flag (from the detector) is threaded but only ever selects the public adapter until Phase-3 internal adapters register |
| `infra/core/config.py` | add `internal_context_host_allowlist: list[str] = []` + `enable_internal_adapters: bool = False` (closed default) |

**Additive invariant / governance (enforced):** the port registry returns the public adapter whenever
the gate is closed **or** no internal adapter is registered (always true in Phase 2). Closing the gate
can never remove a capability. No internal namespace/identifier enters any shipped file (governance
grep in tests). This makes §7 an **architectural property**, not a checklist.

**Tests (write first)** — `packages/starboard-core/tests/unit/ports/test_ports.py` +
`packages/starboard/tests/unit/adapters/ports/test_public_adapters.py`:
- each public adapter structurally satisfies its Protocol; a round-trip through
  `LogRetrievalPort`→`evidence_extractor` produces a `LogBundle` the extractor consumes
- port registry returns the **public** adapter with the gate closed (default) **and** with it open
  (no internal adapter registered) — proving the additive invariant + Phase-2 boundary
- `detect_employee_context`: closed by default (empty allowlist, no signals); opens only when a signal
  matches **and** authorized; secrets never logged (`describe_auth` redaction preserved)
- ports are **SDK-free** (import `starboard_core.ports.*` with no `databricks.sdk` in `sys.modules`;
  `lint-imports` green)
- **governance:** grep the four port files + public adapters for internal namespaces (`centralized_`,
  `fin_live_gold`, `hmr_stack_hash`, logfood, ClickHouse, `go/`) → none

**Acceptance:** four ports with working public adapters; a closed-by-default gate hook on the resolver;
disabling the gate leaves the full public path; no internal adapter or identifier ships. **LOE: M.**

---

## 9. Task D5 — New data packs (compute reliability/right-sizing, column-lineage) + discovery caching

**Source design:** `starboard_optimization/technical.md` §1 (N5), §3. **Objective:** add two public
`system.*` packs and insert result caching to dedupe hot-table scans.

**Repo grounding (verified):** the declarative pack seam — `SystemQuery`/`QueryPack`
(`starboard_core/domain/models/discovery/query.py`), `create_default_registry()`
(`discovery/query_packs/registry.py:190`), routes in `PRODUCT_TO_DOMAIN_PACKS` (`:17-51`) +
`ALWAYS_RUN_PACKS` (`:54-61`). `compute.py` already queries `system.compute.node_timeline` (`:37,96`)
and `system.compute.warehouse_events` (`:155`); `dlt_pipelines.py` queries `system.access.table_lineage`
(`:146,173`). **No `column_lineage` pack and no compute-reliability/right-sizing pack exist today.**
The result cache exists: `tools/services/query_result_cache.py`; discovery has `executor` + engine.

**Verified table facts (2026-08-26):** `system.access.column_lineage` (1-yr rolling retention);
`system.compute.instance_events` is **Public Preview** (spot/on-demand `availability_type`, state
transitions); `system.compute.node_timeline` is minute-granularity utilization;
`system.compute.warehouse_events` is warehouse lifecycle/scale.

**Files:**
| File | Change |
|---|---|
| `discovery/query_packs/compute_reliability.py` (new) | `QueryPack` over `system.compute.{instance_events,node_timeline,node_types,warehouses}`: spot-reclaim rate & MTBF from `instance_events`; oversized nodes (join `node_timeline` utilization → `node_types` capacity); warehouse config drift. `required=False` on the Preview `instance_events` queries |
| `discovery/query_packs/column_lineage.py` (new) | `QueryPack` over `system.access.column_lineage`: source→target column maps, high-fan-in/out columns, orphaned columns; `max_lookback_days` bounded to the 1-yr retention |
| `discovery/query_packs/registry.py:17-51,190+` | register both packs in `create_default_registry`; route a compute-reliability domain (extend `ALL_PURPOSE`/`INTERACTIVE`) + a lineage/governance route |
| `discovery/executor.py` (+ `tools/services/query_result_cache.py`) | insert the cache between executor and SQL client: key = `hash(sql_template + resolved_params + workspace_id + lookback)`; **dedupe identical scans within a run first** (biggest win), then across runs with TTL by table volatility; add `--no-cache` + a freshness floor |

**Design rules:** `SystemQuery`/`QueryPack` model; `required=False` for Preview/Beta tables
(Phase-0 A5 convention) so a missing table degrades the *query*, not the domain; cost via
`system.billing.usage × system.billing.list_prices`, **labeled list-price estimate**; no internal
namespaces.

**Tests (write first)** — `packages/starboard/tests/unit/discovery/test_new_packs_phase2.py` +
`test_discovery_cache.py`:
- each pack imports/constructs; `required_tables` names the intended `system.*` tables;
  `required=False` on the Preview `instance_events` queries
- SQL templates render with test params (no `{unfilled}` placeholders); pass the existing validator
- `create_default_registry()` includes both packs; the compute-reliability + lineage routes resolve
- cache: two identical scans within a run hit the cache once (assert single SQL execution); `--no-cache`
  bypasses; TTL expiry re-runs; distinct params miss
- **governance:** no internal namespace/`go/` link in either pack (grep in test)

**Acceptance:** the two products produce banded, list-price-labeled findings on public `system.*`;
graceful degrade on absent Preview tables; discovery dedupes hot-table scans. **LOE: M.**

---

## 10. Task D4 — Progressive-helper depth (`starboard_x` sub-commands + extras)

**Source design:** `progressive_helpers/technical.md` §3, §4, §7. **Objective:** extend the Phase-1
`starboard_x` middle tier with discovery `data_only`, sparklog parsing, and **pure** warehouse/uc
analyzers as `python -m starboard_x.<domain>` sub-commands on the already-locked extras taxonomy.

> **Depends on Phase-1 B1/B2** — the kernel carve-out + `starboard_x` namespace + the extras taxonomy
> (`diagnostics*`, `discovery`, `sparklog[-aws|azure|gcp]`, `warehouse`, `uc`, `cluster`, `charts`,
> `all`) locked in PHASE_1 §3 D-1.3 and stubbed there. Phase 1 implements only `diagnostics*`; **D4
> implements the remaining declared-but-empty extras.** Do not start D4 until B1/B2 are merged.

**Repo grounding (verified):** discovery already supports data-only —
`EngineConfig(data_only: bool = False)` (`discovery/engine.py:48-65`), "Skip LLM analysis and
synthesis" (`:55`). Log-parser loaders exist (`log_parser/loaders/{dbfs,s3,https,json,local_file}.py`).
The pure analyzers exist SDK-free in the kernel (per PHASE_1 B1 audit: `starboard_core/domain/
analyzers/{uc_analyzer.py,warehouse_analyzer.py}`).

**Files:**
| File | Change |
|---|---|
| `starboard_core/x/discovery/__main__.py` (new) | `run --data-only [--packs …]` wrapping `discovery/engine.py:97` with `EngineConfig(data_only=True)`; JSON envelope + exit codes; `[discovery]` extra |
| `starboard_core/x/sparklog/__main__.py` (new) | `parse --source {dbfs|s3|https|local} --path …` over the existing loaders; `[sparklog]` + cloud extras (`sparklog-aws|azure|gcp`) |
| `starboard_core/x/warehouse/__main__.py` (new) | `analyze` wrapping the **pure** `warehouse_analyzer` (no I/O); `[warehouse]` extra |
| `starboard_core/x/uc/__main__.py` (new) | `analyze` wrapping the **pure** `uc_analyzer`; `[uc]` extra |
| `starboard_core/x/__main__.py` (Phase-1) | register the new sub-modules in the dispatcher |
| `packages/starboard-core/pyproject.toml` | fill in the declared-but-empty `[discovery]`/`[sparklog*]`/`[warehouse]`/`[uc]` extras (deps per progressive_helpers §4) |
| canonical skills (`starboard-discovery`, `starboard-warehouse`, `starboard-uc`) | add the Tier-1 `scripts/run.sh` branch shelling to the new `python -m` targets (mirror PHASE_1 B2-skill) |

**Back-compat:** the diagnostic trio + envelope from Phase 1 are unchanged; new verbs are additive.
Pure analyzers stay SDK-free (import-linter). Skills keep their Tier-0 (`starboard-helper`) + Tier-2
(MCP) branches; D4 adds the Tier-1 branch.

**Tests (write first)** — `packages/starboard-core/tests/unit/x/`:
- `python -m starboard_x.discovery run --data-only` emits a valid envelope; no LLM call (mock);
  `data_only` report has no `domain_analyses`
- `python -m starboard_x.warehouse analyze` / `uc analyze` emit valid envelopes over a fixture; import
  the pure analyzers with **no** `databricks.sdk` in `sys.modules` (stdlib/polars only)
- `sparklog parse --source local --path <fixture>` parses; cloud sources gated behind their extras
  (actionable error when absent)
- extras taxonomy: `[discovery]`/`[warehouse]`/`[uc]`/`[sparklog]` resolve to the intended deps
  (parse pyproject); `[diagnostics-core]` stays stdlib-only (regression against Phase-1)
- exit-code parity: bad args → 4; simulated auth failure in an I/O verb → 1

**Acceptance:** `pip install "starboard-x[discovery|warehouse|uc|sparklog]"` gives the respective verb;
each emits the envelope; skills shell to them prompt-free; pure analyzers stay SDK-free. **LOE: M–L**
(mechanical breadth across four sub-modules + skill wiring).

---

## 11. Task ordering & dependency graph (within Phase 2)

```
Workstream 2a (native):
  C1 RAG→reference files ──┐ (both touch foundation init / vector path)
  C4 retire memory/reflex ─┘  → sequence C1 then C4 (or coordinate the container edit)
  A1 resolver (landed) ──► C2 UC-native state ──► (durable zero-external-DB server)
  C3 JSON CLI sessions ─ independent ─► (ship anytime)

Workstream 2b (depth):
  A1 resolver (landed) + log-parser/diagnostic substrate ──► C5 ports + public adapters + gate hook
  D5 new packs + discovery caching ─ independent ─► (ship anytime)
  Phase-1 B1 kernel + B2 starboard_x ──► D4 progressive-helper depth
```

**Longest pole:** Phase-1 B1/B2 → **D4**. **Fast independent value:** C3, D5, C4.
Suggested order (parallelize the two workstreams): **2a:** C1 → C4 → C2, with C3 in parallel; **2b:**
D5 + C5 in parallel from day 1, **D4 last** (after Phase-1 B1/B2 land).

## 12. Verification & Definition of Done

Per PR and for the phase:
- `uv run ruff check .` — clean
- `uv run mypy packages/…` — clean (respect existing per-module ignores; `log_parser` stays excluded)
- `uv run lint-imports` — kernel boundary (Phase-1 B1) stays green; new reference-file loaders, ports,
  and pure analyzers add no SDK import to the kernel
- `uv run pytest` for the touched package(s) — green, including the new TDD tests
- New/changed behavior documented (config help, extras, skill bodies, port docstrings)
- **Governance grep** of shipped artifacts (reference files, packs, ports + public adapters) — no
  internal namespaces (criterion 9); no internal adapter ships
- Reviewed with `/review` before merge
- Phase-2 exit criteria §0 (1–10) all demonstrably met

## 13. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Reference files lose retrieval fidelity vs. embeddings (C1) | Keep the empty-context degrade; ship Vector Search behind `[vectorsearch]` as the escape hatch (D-2.3); validate SQL accuracy before flipping the default (UNIFIED_PLAN §6) |
| Re-pointing `[vectorsearch]` from `sqlite-vec` to `databricks-vectorsearch` breaks a local ANN user | `sqlite-vec` stays under `[sqlite]`; document the move; default path uses neither |
| UC Statement-Execution latency/concurrency unfit for the chosen state (C2) | Scope `uc` to low-write governed state (D-2.6); keep Lakebase/Postgres extra for per-turn chat; validate before recommending as server default |
| `UCStorageAdapter` bare-client swap breaks existing (orphaned) callers | Injected client is an optional arg; keep the bare-client fallback; the adapter had zero consumers, so risk is contained |
| Container `isinstance` ladder generalization regresses SQLite/Postgres user/feedback stores | Add the capability hook additively; keep existing branches; test all three backends still resolve |
| C3 JSON store loses data on crash mid-write | Atomic temp-file + `os.replace`; test the interrupted-write path |
| Gate mis-detects internal context and leaks data (C5) | **No internal adapter ships in Phase 2**, so the gate only ever selects the public adapter; default closed; allowlist empty by default; OWNER confirms the signal (D-2.7) before Phase-3 adapters attach |
| D4 blocked because Phase-1 `starboard_x` isn't merged | Sequence D4 last; it is the only Phase-2 item with a Phase-1 code dependency; the rest ship independently |
| Internal methodology leaks into public packs/ports (D5/C5) | Paraphrase; `system.*` only; list-price `$`; governance grep in tests + release gate |
| Preview system tables (`instance_events`) absent in a workspace (D5) | `required=False` degrade-gracefully; covered by tests |

## 14. Explicitly out of scope for Phase 2 (deferred)

- **C5 internal adapters** — `LogsSummariserAdapter`, `DbrDoctorAdapter`, `GenieAdapter`,
  `CentralizedTablesAdapter` (D6/D7) → **Phase 3**. Phase 2 ships the ports + public adapters + the
  closed gate hook only (UNIFIED_PLAN §3.5 sequencing).
- **D1 Workload Review engine** (`RuleRegistry`, validator council, severity gate, Action-Rate loop) →
  Phase 3; it consumes the Phase-1 D3 `Finding` schema + seed rules unchanged.
- **D8 `genie ask`**, **D9 Codex/OpenCode host wiring + `.isaac/rules/`**, **D10 Apps OBO** → Phase 3.
- **B5 full layered catalog / per-domain plugins** (`starboard.mcp_tools` entry-point discovery) →
  Phase 3.
- **`starboard_x.{cluster,charts}`** beyond what Phase 1 ships (charts was a Phase-1 B2 stretch);
  `cluster` analyzers → Phase 3 unless pulled forward.
- **`starboard auth login` / `workspace list|use` subcommands** (R2/R3) — CLI auth UX, not required by
  any Phase-2 item; sequence with C2 if desired, else Phase 3.
