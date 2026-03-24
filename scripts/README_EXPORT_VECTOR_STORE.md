# Vector Store Export Script

This script exports a curated subset of the production vector store (`starboard_vector.db`) to JSON + compressed NumPy format for bundling with the `starboard-server` package.

## Purpose

The exported data is used to bootstrap the **in-memory vector store** in CLI and development environments where SQLite vector extensions are unavailable. This enables the Analytics Agent to work out-of-the-box without requiring users to:

1. Install SQLite with vector extension support
2. Build and populate their own vector store
3. Configure external vector databases

## Usage

### 1. Prerequisites

Ensure you have a populated `starboard_vector.db` in the project root:

```bash
# Build the vector store if not already done
python scripts/build_rag_vector_store.py
```

### 2. Export Bootstrap Data

Run the export script:

```bash
python scripts/export_vector_store_snapshot.py
```

This will create:

```
packages/starboard-server/starboard_server/infra/rag/data/bootstrap/
├── tables.json              # Core system table metadata (~30 KB)
├── tables_embeddings.npz    # Precomputed embeddings (~100 KB)
├── nuance.json              # SQL patterns and best practices (~20 KB)
├── nuance_embeddings.npz    # Precomputed embeddings (~60 KB)
├── codebook.json            # Field definitions (~10 KB)
├── codebook_embeddings.npz  # Precomputed embeddings (~20 KB)
└── manifest.json            # Export metadata (~2 KB)
```

**Total size:** ~240 KB (acceptable for package distribution)

### 3. Commit to Repository

The exported files are designed to be committed to the repository:

```bash
git add packages/starboard-server/starboard_server/infra/rag/data/bootstrap/
git commit -m "Update in-memory vector store bootstrap data"
```

## Export Strategies

The script supports different export strategies:

### Essential (Default)

Exports a curated subset of high-value data:

- **Tables:** Core system.billing, system.compute, system.query tables (15 tables)
- **Nuance:** Performance tips, join patterns, aggregation patterns (30 entries)
- **Codebook:** Important field definitions for billing and compute (10 entries)
- **Facets:** Skipped (not critical for basic queries)

### Random Sample

Export random samples across all collections:

```python
exporter.export_all(
    strategy="random",
    config={"tables": 20, "nuance": 30, "codebook": 10, "facets": 5},
)
```

### Custom Configuration

Specify exact counts per collection:

```python
exporter.export_all(
    strategy="essential",
    config={
        "tables": 25,   # More tables
        "nuance": 50,   # More best practices
        "codebook": 15, # More field definitions
        "facets": 10,   # Include some facets
    },
)
```

## Output Format

### JSON Files

Human-readable metadata for each record:

```json
[
  {
    "id": "system.billing.usage_table_summary",
    "content": "Table: system.billing.usage\nDescription: ...",
    "metadata": {
      "table_name": "system.billing.usage",
      "rag_resource_domain": "finops_billing",
      "doc_type": "table_summary"
    },
    "embedding_ref": "tables_system.billing.usage_table_summary"
  }
]
```

### NPZ Files (Embeddings)

Compressed NumPy arrays containing precomputed embeddings:

```python
embeddings = np.load("tables_embeddings.npz")
embedding_vector = embeddings["tables_system.billing.usage_table_summary"]
# Shape: (1024,) - OpenAI ada-002 embedding dimension
```

### Manifest

Export metadata and statistics:

```json
{
  "export_timestamp": "2026-01-30T10:30:00Z",
  "source_database": "starboard_vector.db",
  "strategy": "essential",
  "source_stats": {
    "tables": 1250,
    "nuance": 450,
    "codebook": 180,
    "facets": 3500
  },
  "collections": [...],
  "total_records": 55,
  "total_size_kb": 240.5
}
```

## How It's Used

When the in-memory vector store is initialized:

1. **Try Package-Managed Data:** Load from `starboard_server/infra/rag/data/bootstrap/`
2. **Fall Back to Hardcoded:** If exports unavailable, use minimal hardcoded tables/nuance
3. **Bootstrap Complete:** Store is ready for RAG queries

See `bootstrap_loader.py` for implementation details.

## When to Re-Export

Re-export bootstrap data when:

1. **New System Tables Added:** Databricks releases new system tables worth including
2. **Best Practices Updated:** New SQL patterns or performance tips identified
3. **Quality Improvements:** Better table descriptions or metadata enrichment
4. **Major Version Updates:** Significant changes to RAG corpus

**Recommended frequency:** Quarterly or after major system table additions

## Size Considerations

Current export sizes:

| Collection | Records | JSON | Embeddings | Total |
|-----------|---------|------|------------|-------|
| Tables | 15 | ~30 KB | ~100 KB | ~130 KB |
| Nuance | 30 | ~20 KB | ~60 KB | ~80 KB |
| Codebook | 10 | ~10 KB | ~20 KB | ~30 KB |
| **Total** | **55** | **~60 KB** | **~180 KB** | **~240 KB** |

**Guidelines:**
- Keep total size < 500 KB (acceptable for package distribution)
- Prioritize quality over quantity (15 great tables > 50 mediocre ones)
- Focus on system.billing, system.compute, system.query (most common use cases)

## Troubleshooting

### "Vector store not found"

Ensure `starboard_vector.db` exists:

```bash
ls -lh starboard_vector.db
```

If missing, build it:

```bash
python scripts/build_rag_vector_store.py
```

### "No records exported"

Check source database stats:

```bash
sqlite3 starboard_vector.db "SELECT COUNT(*) FROM vectors_tables;"
```

If empty, rebuild the vector store with fresh data.

### Large File Sizes

If export files exceed 500 KB:

1. Reduce `max_items` in config
2. Use `strategy="essential"` (more selective)
3. Skip facets collection (can be large)

## Related Files

- `build_rag_vector_store.py` - Builds production vector store
- `inmemory_vector_store.py` - In-memory vector store implementation
- `bootstrap_loader.py` - Loads exported data into in-memory store
- `vector_store_factory.py` - Factory with automatic fallback

## Support

For issues or questions, see:
- Design spec: `/changes/inmemory_vector_store_design.md`
- Architecture docs: `/docs/TOOL_ARCHITECTURE.md`
