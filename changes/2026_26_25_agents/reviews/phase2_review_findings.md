# Phase 2 code review — findings

> Recall-oriented review (high effort). Scope: `git diff main...HEAD` on
> `phase2/foundations` (Phase 2 = A0, C1, C2, C3, C4, C5, D4, D5). Working tree
> was clean at review time. Method: 8 finder angles (3 correctness, 3 cleanup,
> altitude, conventions), deduped; focused on the substantive source changes
> (auth-resolver gate, TTL cache, config/state-factory backend rename, ports
> registry, container foundation init, vector-store factory, RAG reference-file
> path, build script) rather than the ~30 test files.
>
> **No crash-class correctness bug surfaced.** The findings are mostly
> latent bugs on the **opt-in `vector_backend="vectorsearch"` path** (not the
> `"none"` default), one intended-design recall tradeoff, one documented-but-sharp
> API, and build-script fragility. Verified clean: no stale
> `database_backend=="databricks"` comparisons remain (the `_alias_database_backend`
> validator maps the deprecated value first); the lean default path leaves
> `container._vector_store = None` and all consumers tolerate `None`.

## Disposition summary

| # | Finding | Severity | Path | Disposition |
|---|---------|----------|------|-------------|
| 1 | Managed VS `similarity_search(columns=["*"])` invalid → silent empty context | Med | opt-in `[vectorsearch]` | **Phase 3** (needs VS index schema) |
| 2 | Reference-file RAG returns empty context for un-annotated NL queries | Med | default | **Phase 3 decision** (intended per D-2.3; revisit for Workload Review) |
| 3 | Similarity semantic cache hardwired to `SQLiteVectorStore` regardless of backend | Med | opt-in `[vectorsearch]` | **Phase 3** (behavior change beyond diff) |
| 4 | `TTLSemanticCache.invalidate(tags=[...])` with no `pattern` flushes entire cache | Low | default | **Deferred** (documented clear-all-on-None; add guard when convenient) |
| 5 | Reflexion-driver error message advertised `[vectorsearch]` (can't satisfy it) | Low | opt-in `[sqlite]` | ✅ **Fixed** (`a5a298b1`) |
| 6 | RAG build-script embeds corpus bodies verbatim; fragile to `#`-leading lines | Low | build-time | **Deferred** (add CI parse-roundtrip guard) |

---

## 1. Managed Vector Search passes `columns=["*"]`, which the VS API rejects
- **File:** `packages/starboard/starboard/infra/rag/adapters/storage/databricks_vector_store.py:380`
- **Severity:** Medium · **Path:** opt-in only (`vector_backend="vectorsearch"`, `[vectorsearch]` extra)
- Every `search_multi_collection` call passes `columns=["*"]`. The Databricks
  Vector Search `similarity_search` API expects **explicit** column names, not a
  wildcard. Each per-collection query raises and is swallowed by the per-collection
  `except`, so the managed path always returns an empty `RAGContext` — the feature
  is silently non-functional.
- **Why deferred:** the correct column list depends on the managed index's actual
  schema, which can't be verified from the diff; a wrong guess could regress an
  environment where `"*"` happens to be tolerated. **→ Phase 3**, fix alongside the
  first real managed-VS deployment (validate against a live index).

## 2. Reference-file RAG returns empty context for un-annotated NL queries
- **File:** `packages/starboard/starboard/tools/adapters/rag_tools.py:114`
- **Severity:** Medium · **Path:** default (`vector_backend="none"`)
- With no `rag_resource_domains` passed and no literal `system.<schema>.<table>`
  token in the query text, domains resolve to `None` and
  `_build_context_from_reference_files` returns an empty `RAGContext()`. A query
  like "why is my Databricks bill so high" gets zero context, where the former
  `inmemory` embedding default would have retrieved it semantically. This is a
  recall regression for un-annotated natural-language queries.
- **Why deferred:** this is the **intended** C1/D-2.3 tradeoff (RAG → curated
  reference files, graceful degradation to no-context). A real remedy (lightweight
  keyword→domain mapping so NL queries still select a domain) is a **design
  decision for Phase 3**, and directly affects Workload Review's retrieval quality
  — decide there.

## 3. Similarity semantic cache is hardwired to `SQLiteVectorStore`
- **File:** `packages/starboard/starboard/infra/core/container.py:280`
- **Severity:** Medium · **Path:** opt-in only (similarity cache + `vector_backend="vectorsearch"`)
- When `_semantic_cache_uses_vector()` is true but the backend is managed
  (`vectorsearch`, no `sqlite_vec` installed), the cache branch still constructs a
  local `SQLiteVectorStore`; the init fails on the missing driver, is swallowed by
  the broad `except Exception` at the DI boundary, and the semantic cache is
  silently disabled rather than using the configured backend.
- **Why deferred:** routing the cache through the selected backend is a behavior
  change spanning more than the reviewed diff. **→ Phase 3**, with #1 (both touch
  the managed-VS path).

## 4. `TTLSemanticCache.invalidate(tags=[...])` with no `pattern` clears everything
- **File:** `packages/starboard/starboard/infra/cache/ttl_semantic_cache.py:302`
- **Severity:** Low · **Path:** default cache
- A caller intending tag-scoped invalidation calls `invalidate(tags=["job"])`;
  because `pattern is None`, the method takes the "clear all" branch, ignores
  `tags`, and flushes every entry. The reference `SemanticCache.invalidate` is a
  no-op returning 0, so swapping in the default TTL cache turns this call from
  harmless into a full flush.
- **Why deferred:** the clear-all-on-`pattern=None` behavior is **explicitly
  documented as intended**; changing it risks breaking the documented "invalidate
  all" contract. Low-cost hardening (raise/ignore when `tags` given without a
  pattern, or honor `tags`) can land opportunistically — not blocking.

## 5. Reflexion-driver error message advertised the wrong extra — ✅ FIXED
- **File:** `packages/starboard/starboard/infra/core/container.py` (~line 179)
- **Severity:** Low · **Fixed in `a5a298b1`**
- `enable_reflexion=True` without `sqlite_vec` raised a `RuntimeError` suggesting
  `pip install 'starboard[vectorsearch]'`, but `[vectorsearch]` ships
  `databricks-vectorsearch` (not `sqlite_vec`) and the reflexion store hardcodes
  `SQLiteVectorStore`, so following the hint reproduced the same error. Message now
  recommends only `starboard[sqlite]` and states that `[vectorsearch]` does not
  satisfy reflexion. Verified: `test_foundation_lean.py` 9 passed, ruff clean.

## 6. RAG build-script embeds corpus bodies verbatim under `###` entries
- **File:** `scripts/build_rag_reference_files.py:253`
- **Severity:** Low · **Path:** build-time (generated package data)
- Corpus document bodies are written verbatim beneath `### ` entries. If a future
  nuance/codebook `document` value contains a line starting with `## ` or `### `,
  `reference_loader._parse_sections` treats it as a new section/entry header,
  splitting or dropping content. The only safeguard today is an authoring comment
  ("verified during authoring") — nothing enforces it.
- **Why deferred:** a robust fix changes the generated reference-file format and
  requires regenerating shipped package data (outside the diff). **Recommended
  follow-up:** a CI parse-roundtrip guard that regenerates the reference files and
  asserts every corpus body survives `_parse_sections` unchanged (pairs with the
  already-queued "CI schema-validation for Preview packs" follow-up).

---

## Routing into Phase 3

- **#1 + #3** → fold into the Phase-3 managed-VS / internal-adapter work (they only
  bite when someone opts into managed Vector Search). Fix against a live index.
- **#2** → a **Phase-3 design decision** for retrieval quality; the Workload Review
  flagship (D1) is the main consumer and should drive the call on NL→domain mapping.
- **#4, #6** → low-priority hardening; #6 gets a CI parse-roundtrip guard alongside
  the Preview-pack schema-validation follow-up. Neither blocks landing Phase 2.
