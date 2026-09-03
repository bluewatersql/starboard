# Build RAG Reference Files

Guide for **`build_rag_reference_files.py`** — generates the shipped, embedding-free
Markdown reference files under `starboard_core/rag/knowledge/domains/`. This is the RAG
runtime path: reference-file only, no vector store or embeddings. (The legacy
ANN/SQLite vector-store build pipeline was removed in the native-first simplification.)

---

## Input Contract — `build_rag_reference_files.py`

The script reads two JSON corpus packs from
`packages/starboard-core/starboard_core/rag/data/`:

| File | Purpose |
|------|---------|
| `nuance_pack.json` | Curated rules, recipes, and concepts per domain |
| `codebook_pack.json` | Categorical-value codebooks and facet lists |

Both files must be a **JSON object** with a `"records"` key whose value is a **list
of record objects**.  Violations raise `PackParseError` (a `ValueError` subclass)
with a message that identifies the source file and the zero-based record index.

### Nuance pack record schema

```json
{
  "id":       "<string, required, non-empty>",
  "document": "<string, required, non-empty — the prose content>",
  "metadata": {
    "domain":   "<string, required, non-empty — raw domain label or alias>",
    "topic_id": "<string, optional — defaults to id>",
    "doc_type": "<string, optional — defaults to \"nuance\">"
  }
}
```

**Required fields:** `id`, `document`, `metadata` (dict), `metadata.domain`.  
**Optional fields:** `metadata.topic_id`, `metadata.doc_type`.

### Codebook pack record schema

```json
{
  "id":       "<string, required, non-empty>",
  "document": "<string, required, non-empty — description of the code key>",
  "metadata": {
    "domain":     "<string, required, non-empty — raw domain label or alias>",
    "code_key":   "<string, required, non-empty — used as Markdown entry header>",
    "values_csv": "<string, optional — comma-separated categorical values>"
  }
}
```

**Required fields:** `id`, `document`, `metadata` (dict), `metadata.domain`,
`metadata.code_key`.  
**Optional fields:** `metadata.values_csv` (absent or `null` → no Facets entry).

### Domain labels

`metadata.domain` may be either a canonical `RagResourceDomain` value (e.g.
`"finops_billing"`) or one of the recognised aliases:

| Alias | Resolves to |
|-------|-------------|
| `sql_policy` | `query` |
| `query_history` | `query` |
| `security_audit` | `security_access` |
| `governance_lineage` | `lineage` |

Records with unrecognised domain labels are **silently skipped** (the label may
belong to a future domain); records with a *missing* `metadata.domain` field raise
`PackParseError` immediately.

### Errors raised for malformed input

| Condition | Error message fragment |
|-----------|----------------------|
| Pack file is not a JSON object | `expected a JSON object` |
| Missing `"records"` key | `missing required key 'records'` |
| `"records"` is not a list | `'records' must be a list` |
| Record missing/empty `id` | `missing or empty required field 'id'` |
| Record missing/empty `document` | `missing or empty required field 'document'` |
| Record `metadata` absent or not a dict | `missing or invalid 'metadata'` |
| Record `metadata.domain` absent/empty | `'metadata.domain' is missing or empty` |
| Codebook record `metadata.code_key` absent/empty | `'metadata.code_key' is missing or empty` |

### Parse-roundtrip CI guard

A pytest guard lives at
`packages/starboard/tests/unit/scripts/test_build_rag_roundtrip.py`.
It verifies that:
1. Well-formed input is parsed into the typed model (`NuanceRecord`,
   `CodebookRecord`).
2. Each category of malformed input raises `PackParseError`.
3. The render→re-parse roundtrip is stable and lossless.

Run it with:

```bash
pytest packages/starboard/tests/unit/scripts/test_build_rag_roundtrip.py -v
```
