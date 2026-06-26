# Build RAG Vector Store

Complete guide for building the RAG vector store for Analytics Agent V2.

---

## Quick Start

```bash
# 1. Set environment variables
export DATABRICKS_HOST="your-workspace.cloud.databricks.com"
export DATABRICKS_TOKEN="dapi..."
export OPENAI_API_KEY="<your-api-key>"

# 2. Run the build script
python scripts/build_rag_vector_store.py

# 3. Wait 2-3 minutes for completion
# Output: data/rag_vectors.db
```

---

## Prerequisites

### Required Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABRICKS_HOST` | Databricks workspace URL | `my-workspace.cloud.databricks.com` |
| `DATABRICKS_WAREHOUSE_ID` | SQL Warehouse ID| `abc123` |
| `DATABRICKS_TOKEN` | Personal access token | `dapi...` |
| `OPENAI_API_KEY` | OpenAI API key | `<your-api-key>` |

### Required Permissions

**Databricks**:
- Read access to system schemas:
  - `system.billing.*`
  - `system.compute.*`
  - `system.storage.*`
  - `system.catalog.*`
  - `system.query.*`
  - `system.access.*`

**OpenAI**:
- Access to GPT-4 for enrichment
- Access to `text-embedding-3-small` for embeddings

### Python Dependencies

All dependencies are managed by `uv`. The script will use the existing virtual environment.

---

## What Gets Built

The script creates a multi-collection vector store with:

### Collections

1. **Tables** (~300 chunks from 50 tables)
   - Semantic chunks: summary, use_cases, relationships, columns
   - Domain-duplicated: finops_billing, infrastructure_compute, etc.
   - Automatically deduplicated during retrieval

2. **Nuance** (~25 entries)
   - Platform concepts and best practices
   - Domain-tagged for filtering
   - Source: `changes/analytics_agent_v2/src/data/nuance_pack.json`

3. **Facets** (~80 entries)
   - Exploded categorical values
   - Field-level metadata (warehouse_size, sku_name, etc.)
   - Source: `changes/analytics_agent_v2/src/data/codebook_pack.json`

4. **Learnings** (empty initially)
   - Dynamically populated during agent execution
   - Reflexion feedback and patterns

### Output

```
data/rag_vectors.db          # SQLite database with all collections
checkpoints/rag/             # Intermediate checkpoints
  ├── 01_extracted_metadata.json
  ├── 02_enriched_metadata.json
  └── 03_domain_chunks.json
```

---

## Usage

### Basic Usage

```bash
python scripts/build_rag_vector_store.py
```

**Expected Output**:
```
Building RAG Vector Store for Analytics Agent V2

→ Initializing clients...
✓ Clients initialized

⠋ Extracting metadata...     ████████████████ 100% 00:02
⠋ Enriching metadata...      ████████████████ 100% 00:45
⠋ Chunking and duplicating... ████████████████ 100% 00:01
⠋ Embedding and ingesting...  ████████████████ 100% 01:23
⠋ Ingesting nuance...         ████████████████ 100% 00:05
⠋ Ingesting facets...         ████████████████ 100% 00:10

✓ Build Complete!

Summary:
  Tables extracted: 47
  Tables enriched: 47
  Domain chunks: 342
  Nuance entries: 25
  Facet entries: 83

Vector store: data/rag_vectors.db
```

**Duration**: 2-3 minutes (depending on API rate limits)

### Resume from Checkpoint

If the script fails or is interrupted, just re-run it:

```bash
python scripts/build_rag_vector_store.py
```

The script will automatically resume from the last successful checkpoint:

```
✓ Using cached extracted metadata
✓ Using cached enriched metadata
→ Chunking and duplicating...
```

### Force Full Rebuild

To ignore checkpoints and rebuild from scratch:

```bash
# Remove checkpoints
rm -rf checkpoints/rag/

# Remove existing database
rm -f data/rag_vectors.db

# Run build
python scripts/build_rag_vector_store.py
```

### Custom Database Path

Edit the script to change the output path:

```python
# In main() function, line ~450
vector_store = SQLiteMultiCollectionStore(
    db_path="path/to/your/vectors.db",  # Change this
    embedding_dim=1536
)
```

---

## Configuration

### System Schemas

By default, the script processes these schemas:

```python
SYSTEM_SCHEMAS = [
    "system.billing",
    "system.compute",
    "system.storage",
    "system.catalog",
    "system.query",
    "system.access",
]
```

**To modify**: Edit the `SYSTEM_SCHEMAS` list in `scripts/build_rag_vector_store.py` (line 43)

### Checkpoint TTL

Checkpoints expire after 24 hours by default:

```python
CHECKPOINT_TTL_HOURS = 24
```

**To modify**: Edit `CHECKPOINT_TTL_HOURS` in the script (line 40)

### Embedding Batch Size

Embeddings are processed in batches of 100:

```python
batch_size = 100  # Line ~267
```

**To modify**: Edit `batch_size` in `embed_and_ingest_tables_step()` function

### LLM Settings

**Enrichment Model**: GPT-4
```python
model="gpt-4o"  # Line ~91
```

**Embedding Model**: text-embedding-3-small
```python
model="text-embedding-3-small"  # Line ~271
```

**Concurrency & Rate Limiting**:
```python
enrichment = EnrichmentService(
    llm_client,
    max_concurrent=5,        # Max parallel LLM calls
    rate_limit_per_min=50,   # Rate limit
)
```

---

## Pipeline Steps

The build process consists of 6 steps:

### Step 1: Extract Metadata (5-15 seconds)

**Phase 1: Extract Tables & Columns**
- Connects to Databricks SQL warehouse
- Extracts table and column metadata from system schemas
- Uses parallel processing (ThreadPoolExecutor)
- **Checkpoint**: `01_extracted_metadata.json`

**Phase 2: Discovery by Example** (NEW)
- Analyzes query history from `system.query.history` (last 90 days)
- Uses `QueryAnalyzer` to parse SQL queries with sqlglot
- Discovers real-world usage patterns:
  - **Predicates**: Common filter values from WHERE clauses
  - **Aggregations**: Frequently used aggregation functions (SUM, AVG, COUNT)
  - **Join Patterns**: Common join columns and relationships
- Enriches column metadata with discovered patterns
- Architecture:
  ```
  MetadataExtractor
  ├─ extract_tables() → get raw metadata
  └─ discover_by_example() → enrich with usage patterns
      ├─ Load query history (system.query.history)
      ├─ QueryAnalyzer.analyze_queries() → parse with sqlglot
      ├─ Cache AnalysisResult
      └─ Apply patterns to each table
  ```
- **Benefits**:
  - Columns show example filter values (e.g., `sku_name: ['JOBS_COMPUTE', 'SERVERLESS']`)
  - Columns show common aggregations (e.g., `usage_quantity: ['SUM', 'AVG']`)
  - Tables show frequently joined columns (e.g., `['workspace_id', 'sku_name']`)

### Step 2: Enrich with LLM (30-60 seconds)
- Enriches tables with LLM-generated context
- Adds: business_context, grain, common_use_cases
- Enhances column metadata with business_meaning, cardinality
- Uses async batch processing with rate limiting
- **Checkpoint**: `02_enriched_metadata.json`

### Step 3: Chunk & Duplicate (1-2 seconds)
- Breaks tables into semantic chunks (summary, use_cases, relationships, columns)
- Duplicates chunks across multiple domains
- Example: `system.billing.usage` → finops_billing + finops_usage
- **Checkpoint**: `03_domain_chunks.json`

### Step 4: Embed & Ingest Tables (60-90 seconds)
- Generates embeddings for all domain chunks
- Batch processing (100 chunks at a time)
- Upserts to Tables collection in vector store
- **No checkpoint** (final ingestion step)

### Step 5: Ingest Nuance (5-10 seconds)
- Loads nuance from JSON file
- Generates embeddings
- Upserts to Nuance collection

### Step 6: Ingest Facets (10-20 seconds)
- Loads codebook from JSON file
- Explodes categorical values into individual facets
- Generates embeddings
- Upserts to Facets collection

---

## Troubleshooting

### Error: "DATABRICKS_HOST required"

**Cause**: Missing environment variable

**Solution**:
```bash
export DATABRICKS_HOST="your-workspace.cloud.databricks.com"
export DATABRICKS_WAREHOUSE_ID="xxxxx"
export DATABRICKS_TOKEN="dapi..."
```

### Error: "Failed to load sqlite-vec extension"

**Cause**: sqlite-vec extension not installed

**Solution**:
```bash
# Install sqlite-vec
pip install sqlite-vec

# Or use uv
uv pip install sqlite-vec
```

### Error: "Rate limit exceeded" (OpenAI)

**Cause**: Too many API requests

**Solutions**:
1. Wait a few minutes and re-run (will resume from checkpoint)
2. Reduce `max_concurrent` in the script (line ~210):
   ```python
   enrichment = EnrichmentService(
       llm_client,
       max_concurrent=3,  # Reduce from 5
       rate_limit_per_min=30,  # Reduce from 50
   )
   ```

### Error: "Permission denied" (Databricks)

**Cause**: Insufficient permissions to read system tables

**Solution**: Request access to system schemas from your Databricks admin

### Warning: "Nuance file not found"

**Cause**: Optional data files don't exist yet

**Impact**: Script continues, just skips nuance/facet ingestion

**Solution** (optional):
1. Create `changes/analytics_agent_v2/src/data/nuance_pack.json`
2. Create `changes/analytics_agent_v2/src/data/codebook_pack.json`
3. See "Data File Formats" below for structure

### Slow Performance

**Symptoms**: Build takes >5 minutes

**Causes**:
1. Slow Databricks SQL warehouse (cold start)
2. OpenAI API rate limits
3. Network latency

**Solutions**:
1. Use a larger/warmer SQL warehouse
2. Reduce `max_concurrent` to avoid rate limits
3. Check network connectivity

### Checkpoint Corruption

**Symptoms**: 
```
Error reading checkpoint: json.JSONDecodeError
```

**Solution**:
```bash
# Remove corrupted checkpoint
rm -rf checkpoints/rag/

# Re-run build
python scripts/build_rag_vector_store.py
```

---

## Data File Formats

### Nuance File

**Location**: `changes/analytics_agent_v2/src/data/nuance_pack.json`

**Format**:
```json
[
  {
    "id": "nuance_billing_best_practices",
    "content": "Best practice: Always filter system.billing.usage by workspace_id to reduce query costs.",
    "domain": "finops_billing",
    "category": "best_practices"
  },
  {
    "id": "nuance_warehouse_sizing",
    "content": "Warehouse sizing rule: Start with 2X-Small for development, Small for production queries.",
    "domain": "infrastructure_warehouses",
    "category": "sizing_rules"
  }
]
```

### Codebook File

**Location**: `changes/analytics_agent_v2/src/data/codebook_pack.json`

**Format**:
```json
[
  {
    "field": "warehouse_size",
    "domain": "infrastructure_warehouses",
    "description": "SQL warehouse size options",
    "values": ["2X-Small", "X-Small", "Small", "Medium", "Large", "X-Large", "2X-Large"]
  },
  {
    "field": "sku_name",
    "domain": "finops_billing",
    "description": "Databricks SKU names for billing",
    "values": [
      "STANDARD_ALL_PURPOSE_COMPUTE",
      "PREMIUM_ALL_PURPOSE_COMPUTE",
      "JOBS_COMPUTE",
      "SERVERLESS_SQL"
    ]
  }
]
```

**Note**: The codebook is "exploded" - each value becomes a separate facet entry in the vector store.

---

## Performance

### Typical Build Times

| Step | Duration | Bottleneck |
|------|----------|------------|
| Extract metadata (50 tables) | 5-10s | Databricks SQL (parallel) |
| Discovery by example | 3-8s | Query history analysis |
| Enrich metadata | 30-60s | OpenAI API (rate limited) |
| Chunk & duplicate | 1-2s | CPU |
| Embed & ingest tables (300 chunks) | 60-90s | OpenAI Embeddings API |
| Ingest nuance (25 entries) | 5-10s | OpenAI Embeddings API |
| Ingest facets (80 entries) | 10-20s | OpenAI Embeddings API |
| **Total** | **2-3 min** | **API rate limits** |

### Query Performance

Once built, the vector store provides fast queries:

| Query Type | Latency |
|------------|---------|
| Tables (no filter) | 10-20ms |
| Tables (with domain filter) | 5-10ms |
| Nuance | 5-10ms |
| Facets | 10-15ms |
| Learnings | 5-10ms |

### Scalability

**Current Capacity**:
- 50 tables → 300 domain chunks
- 25 nuance entries
- 80 facet values

**Expected Growth**:
- 200 tables → 1,500 domain chunks
- 100 nuance entries
- 500 facet values

**Bottleneck**: OpenAI API rate limits (build time only)

---

## Architecture

### Multi-Collection Design

```
┌─────────────────────────────────────┐
│   SQLite Database (single file)    │
├─────────────────────────────────────┤
│                                     │
│  Tables Collection                  │
│  - vectors_tables (data)            │
│  - vec_index_tables (embeddings)    │
│                                     │
│  Nuance Collection                  │
│  - vectors_nuance (data)            │
│  - vec_index_nuance (embeddings)    │
│                                     │
│  Facets Collection                  │
│  - vectors_facets (data)            │
│  - vec_index_facets (embeddings)    │
│                                     │
│  Learnings Collection               │
│  - vectors_learnings (data)         │
│  - vec_index_learnings (embeddings) │
│                                     │
└─────────────────────────────────────┘
```

### Pipeline Flow

```
Databricks System Tables
  ↓ (MetadataExtractor.extract_tables)
TableMetadata[] (raw tables + columns)
  ↓ (MetadataExtractor.discover_by_example)
  │
  ├─ Load query history (system.query.history + table_lineage)
  │   ↓
  ├─ QueryAnalyzer.analyze_queries()
  │   ├─ parse_predicates() → PredicateRecord[]
  │   ├─ parse_aggregations() → AggregationRecord[]
  │   └─ parse_joins() → JoinRecord[]
  │   ↓
  └─ AnalysisResult (cached)
      ↓
TableMetadata[] (enriched with usage patterns)
  ↓ (checkpoint)
  ↓ (EnrichmentService + LLM)
TableMetadata[] (LLM-enriched)
  ↓ (checkpoint)
  ↓ (ChunkingService)
Chunk[] (summary, use_cases, relationships, columns)
  ↓ (DomainService)
DomainChunk[] (duplicated across domains)
  ↓ (checkpoint)
  ↓ (OpenAI Embeddings)
VectorRecord[] (with embeddings)
  ↓ (SQLiteMultiCollectionStore)
Tables Collection in Vector Store
```

### Discovery by Example Architecture (NEW)

The build script now includes intelligent usage pattern discovery:

```
┌───────────────────────────────────────────────────────┐
│ MetadataExtractor                                     │
├───────────────────────────────────────────────────────┤
│                                                       │
│  discover_by_example(tables: list[TableMetadata])    │
│  ├─ Phase 1: Load & Analyze (once)                   │
│  │   ├─ _load_query_history()                        │
│  │   │   Query: system.query.history (90 days)       │
│  │   │   Join: system.access.table_lineage           │
│  │   │   Returns: [(table_name, query_text), ...]    │
│  │   │                                                │
│  │   └─ QueryAnalyzer.analyze_queries()              │
│  │       ├─ Parse with sqlglot                       │
│  │       ├─ Extract predicates (WHERE clauses)       │
│  │       ├─ Extract aggregations (SUM, AVG, etc.)    │
│  │       ├─ Extract joins (ON clauses)               │
│  │       └─ Return AnalysisResult (cached)           │
│  │                                                    │
│  └─ Phase 2: Apply Patterns (per table)              │
│      └─ _apply_patterns_to_table()                   │
│          ├─ get_column_predicates()                  │
│          ├─ get_column_aggregations()                │
│          └─ get_join_columns()                       │
│                                                       │
└───────────────────────────────────────────────────────┘
                    │
                    │ uses
                    ▼
┌───────────────────────────────────────────────────────┐
│ QueryAnalyzer (Pure SQL Parsing)                     │
├───────────────────────────────────────────────────────┤
│  - No database dependencies                           │
│  - Uses sqlglot for SQL parsing                       │
│  - 100% test coverage (33 unit tests)                 │
│                                                       │
│  Methods:                                             │
│  ├─ parse_predicates(query, table)                   │
│  ├─ parse_aggregations(query, table)                 │
│  ├─ parse_joins(query, table)                        │
│  ├─ analyze_queries(queries)                         │
│  ├─ get_column_predicates(result, table, column)     │
│  ├─ get_column_aggregations(result, table, column)   │
│  └─ get_join_columns(result, table)                  │
│                                                       │
└───────────────────────────────────────────────────────┘
```

**Key Benefits:**
- **Separation of Concerns**: SQL parsing separated from DB extraction
- **Caching**: Query analysis result cached to avoid re-parsing
- **Testability**: Pure SQL parsing with no DB dependencies
- **Real-world Context**: Discovers actual usage patterns, not just schema

**Example Output:**

Before discovery:
```python
ColumnMetadata(
    column_name="sku_name",
    data_type="string",
    comment="SKU identifier"
)
```

After discovery:
```python
ColumnMetadata(
    column_name="sku_name",
    data_type="string",
    comment="SKU identifier",
    example_filters=["JOBS_COMPUTE", "SERVERLESS_SQL", "ALL_PURPOSE_COMPUTE"],
    common_aggregations=[]  # Not typically aggregated
)
```

---
  ↓ (ChunkingService)
TableChunk[]
  ↓ (DomainService)
DomainChunk[]
  ↓ (checkpoint)
  ↓ (EmbeddingService)
VectorRecord[]
  ↓
SQLiteMultiCollectionStore
  - Tables
  - Nuance
  - Facets
  - Learnings
```

---

## Querying the Vector Store

### Python API

```python
from starboard_server.infra.rag import SQLiteMultiCollectionStore

# Initialize
store = SQLiteMultiCollectionStore("data/rag_vectors.db")
await store.initialize()

# Generate query embedding
from openai import AsyncOpenAI
client = AsyncOpenAI()
response = await client.embeddings.create(
    model="text-embedding-3-small",
    input="Show me billing costs"
)
query_embedding = response.data[0].embedding

# Query tables
results = await store.query_tables(
    query_embedding=query_embedding,
    domains=["finops_billing"],        # Filter by domain
    n_results=20,                       # Top 20 results
    deduplicate=True,                   # Remove domain duplicates
)

# Results
for result in results:
    print(f"Table: {result.metadata['table_name']}")
    print(f"Score: {result.score:.3f}")
    print(f"Content: {result.content[:100]}...")
    print()
```

### Query Collections

```python
# Query nuance (best practices, rules)
nuance = await store.query_nuance(
    query_embedding=query_embedding,
    domains=["finops_billing"],
    n_results=25,
)

# Query facets (categorical values)
facets = await store.query_facets(
    query_embedding=query_embedding,
    domains=["compute_warehouses"],
    n_results=50,
)

# Query learnings (reflexion feedback)
learnings = await store.query_learnings(
    query_embedding=query_embedding,
    agent_domain="analytics",          # Agent-specific
    n_results=10,
)

# Close store
await store.close()
```

---

## Advanced Usage

### Checkpoint Management

Checkpoints are automatically saved to avoid re-running expensive operations:

```bash
# Location
data/checkpoints/
├── 01_extracted_metadata.json      # Extracted tables
├── 02_enriched_metadata.json       # LLM-enriched tables
└── discovery_by_example.json       # Query analysis results
```

**Clear all checkpoints** (force full rebuild):
```bash
python scripts/clean_checkpoints.py
```

**Clear specific checkpoint**:
```bash
# Clear enriched metadata (re-run LLM enrichment)
python scripts/clean_checkpoints.py enriched

# Clear extracted metadata (re-extract from Databricks)
python scripts/clean_checkpoints.py extracted
```

**When to clear checkpoints**:
- After changing system schemas or extraction logic
- After failed enrichment (all tables show `business_context=None`)
- When changing LLM prompts or models
- To force fresh data from Databricks

**Checkpoint TTL**: By default, checkpoints are considered fresh for 20 hours (1200 minutes). After that, they're automatically regenerated.

---

### Custom LLM Model

Edit the script to use a different model:

```python
# Line ~91
response = await self.client.chat.completions.create(
    model="gpt-4o-mini",  # Change to gpt-4o-mini for faster/cheaper
    messages=[{"role": "user", "content": prompt}],
    temperature=0.3,
    max_tokens=2000,
)
```

### Custom Embedding Model

Edit the script to use a different embedding model:

```python
# Line ~271 and others
embedding_response = await llm_client.client.embeddings.create(
    model="text-embedding-3-large",  # Larger, more accurate
    input=[chunk["content"] for chunk in batch],
)
```

**Note**: If you change embedding dimensions, update the `embedding_dim` parameter:

```python
vector_store = SQLiteMultiCollectionStore(
    db_path="data/rag_vectors.db",
    embedding_dim=3072,  # For text-embedding-3-large
)
```

### Selective Schema Processing

To process only specific schemas:

```python
# Line ~43
SYSTEM_SCHEMAS = [
    "system.billing",  # Only billing
    "system.compute",  # Only compute
]
```

### Parallel Enrichment

To speed up enrichment (if you have higher rate limits):

```python
# Line ~210
enrichment = EnrichmentService(
    llm_client,
    max_concurrent=10,          # Increase from 5
    rate_limit_per_min=100,     # Increase from 50
)
```

---

## Related Documentation

- **Design Documents**: `changes/analytics_agent_v2/preloading/`
  - `EXECUTIVE_SUMMARY.md` - High-level overview
  - `VECTOR_STORE_DESIGN_AND_IMPLEMENTATION.md` - Detailed design
  - `ANTI_PATTERNS_AND_ISSUES.md` - Known issues
  
- **Implementation Tracking**: `changes/analytics_agent_v2/preloading/`
  - `PHASE1_COMPLETE.md` - Foundation components
  - `PHASE2_COMPLETE.md` - Multi-collection store
  - `PHASE3_COMPLETE.md` - Orchestration script
  - `PROJECT_COMPLETE.md` - Complete project summary

- **POC Code**: `changes/analytics_agent_v2/demos/`
  - `demo_0_build_vector_store.py` - Original POC
  - `demo_1_simple_rag.py` - Simple RAG example
  - `demo_7_rag_extended.py` - Agentic RAG example

---

## Support

### Common Questions

**Q: How often should I rebuild the vector store?**  
A: Rebuild when:
- System tables have significant changes
- New tables are added to system schemas
- You update nuance or codebook data
- You want to refresh LLM enrichments

**Q: Can I update specific collections without rebuilding everything?**  
A: Currently no, but you can:
- Delete specific checkpoints to re-run those steps
- Manually upsert to collections using the Python API

**Q: What if I only want to process some tables?**  
A: Modify the `SYSTEM_SCHEMAS` list in the script to include only desired schemas.

**Q: How much does a full build cost?**  
A: Approximate OpenAI costs:
- Enrichment (50 tables × GPT-4): ~$0.50-$1.00
- Embeddings (400 items × text-embedding-3-small): ~$0.01-$0.02
- **Total**: ~$0.50-$1.02 per build

**Q: Is the vector store production-ready?**  
A: Yes! The implementation has:
- 180+ tests with 98%+ coverage
- Comprehensive error handling
- Checkpoint-based resumability
- Production-grade code quality

### Getting Help

1. Check troubleshooting section above
2. Review error messages in terminal output
3. Check checkpoint files in `checkpoints/rag/`
4. Review logs (structured logging with `structlog`)
5. Consult design documents in `changes/analytics_agent_v2/preloading/`

---

## License

Part of the Starboard AI Agent project.

