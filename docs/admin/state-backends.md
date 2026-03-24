# State Backends

This guide covers the configuration and management of Starboard's pluggable state backend system. The server uses a **repository pattern** with multiple storage backends for conversation state, long-term memory, and caching, allowing you to choose the right backend for each deployment environment.

---

## Architecture Overview

Starboard manages three distinct storage concerns, each with its own backend selection:

| Concern | Purpose | Interface | Backends |
|---|---|---|---|
| **State Store** | Conversation persistence (messages, metadata) | `StateStore` | SQLite, Postgres, Databricks Lakebase, InMemory |
| **Memory Store** | Long-term memory (episodes, facts, user profiles) | `MemoryStore` | SQLite, Postgres, Databricks Lakebase, InMemory |
| **Cache Store** | Key-value caching (tool results, sessions) | `CacheStore` | Redis, InMemory |

The `Container` class in `infra/core/container.py` manages the lifecycle of all stores. On startup it calls the factory functions in `infra/core/state_factory.py` to create the appropriate implementations based on your environment configuration.

```
Container.initialize()
    |
    +-- create_state_store(config)   --> SQLiteStateStore | PostgresStateStore | ...
    +-- create_memory_store(config)  --> SQLiteMemoryStore | PostgresMemoryStore | ...
    +-- create_cache_store(config)   --> RedisCacheStore | InMemoryCacheStore
    +-- _initialize_foundation_components()
            +-- Vector store (sqlite-vec or in-memory)
            +-- Reflexion store
            +-- Semantic cache
```

---

## Backend Selection Matrix

| Backend | Environment | Persistence | Vector Search | Scaling | Use Case |
|---|---|---|---|---|---|
| **InMemory** | `dev`, `test` | None | No | Single process | Unit tests, quick prototyping |
| **SQLite** | `dev` | File-based | sqlite-vec | Single instance | Local development, demos |
| **PostgreSQL** | `staging`, `production` | Full | pgvector | Horizontal | Standard production |
| **Databricks Lakebase** | `staging`, `production` | Full | pgvector | Horizontal | Databricks-native deployments |
| **Redis** | Any | TTL-based | No | Clusterable | Session cache, rate limiting |

!!! tip "Quick rule of thumb"
    Use **SQLite** for local development, **Postgres** for standard production deployments, and **Databricks Lakebase** when running inside a Databricks workspace with OAuth authentication.

---

## Environment Variables Reference

### Core Backend Selection

| Variable | Values | Default | Description |
|---|---|---|---|
| `ENVIRONMENT` | `dev`, `test`, `staging`, `production` | `dev` | Determines which factory path is used |
| `DATABASE_BACKEND` | `sqlite`, `postgres`, `databricks` | `sqlite` | Primary state/memory backend |
| `DATABASE_URL` | Connection string | -- | Required for `postgres` and `databricks` backends |
| `CACHE_BACKEND` | `memory`, `redis`, `postgres` | `memory` | Cache layer backend |

### SQLite Configuration

| Variable | Default | Description |
|---|---|---|
| `SQLITE_STATE_PATH` | `./dev_data/starboard_state.db` | Conversation state database file |
| `SQLITE_MEMORY_PATH` | `./dev_data/starboard_memory.db` | Long-term memory database file |
| `SQLITE_VECTOR_PATH` | `./dev_data/starboard_vectors.db` | Vector embeddings database file |
| `SQLITE_REFLEXION_PATH` | `./dev_data/starboard_reflexion.db` | Agent reflexion/learnings database file |

### PostgreSQL Configuration

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | -- | Connection string: `postgres://user:pass@host:port/db` |
| `POSTGRES_MIN_POOL_SIZE` | `5` | Minimum connections in the pool |
| `POSTGRES_MAX_POOL_SIZE` | `20` | Maximum connections in the pool |
| `POSTGRES_COMMAND_TIMEOUT` | `60` | SQL command timeout in seconds |

### Databricks Lakebase Configuration

| Variable | Default | Description |
|---|---|---|
| `LAKEBASE_INSTANCE_NAME` | -- | Lakebase instance name (required) |
| `LAKEBASE_DATABASE_NAME` | -- | Database name within the instance (required) |
| `DATABRICKS_CLIENT_ID` | -- | OAuth client ID (optional, falls back to current user) |
| `DATABRICKS_DATABASE_PORT` | `5432` | PostgreSQL port |
| `DB_POOL_SIZE` | `5` | Connection pool size |
| `DB_MAX_OVERFLOW` | `10` | Maximum overflow connections beyond pool size |
| `DB_POOL_TIMEOUT` | `10` | Pool connection timeout in seconds |
| `DB_POOL_RECYCLE_INTERVAL` | `3600` | Connection recycle interval in seconds |
| `DB_COMMAND_TIMEOUT` | `30` | SQL command timeout in seconds |

### Redis Configuration

| Variable | Default | Description |
|---|---|---|
| `REDIS_URL` | -- | Redis connection URL: `redis://host:port/db` |
| `CACHE_TTL` | `300` | Default cache TTL in seconds (5 minutes) |

### Vector Store Configuration

| Variable | Values | Default | Description |
|---|---|---|---|
| `VECTOR_BACKEND` | `sqlite`, `chroma`, `databricks`, `postgres` | `sqlite` | Vector store backend |
| `EMBEDDING_DIMENSION` | Integer | `1024` | Embedding vector dimensionality |
| `EMBEDDING_MODEL` | Model name | `databricks-bge-large-en` | Embedding model for vector generation |
| `EMBEDDING_BASE_URL` | URL | `` | Separate base URL for embedding API (uses LLM_BASE_URL when empty) |
| `EMBEDDING_CACHE_TTL` | Seconds | `86400` | Embedding cache TTL (24 hours) |

### Semantic Cache Configuration

| Variable | Default | Description |
|---|---|---|
| `ENABLE_SEMANTIC_CACHE` | `true` | Enable/disable semantic caching |
| `SEMANTIC_CACHE_THRESHOLD` | `0.95` | Minimum cosine similarity for cache hit (0.0-1.0) |

---

## Backend Details

### 1. InMemory

The in-memory backend stores all data in Python dictionaries. Data is lost when the process exits.

**Implementation:** `adapters/state/inmemory/state_store.py` (InMemoryStateStore)

**When to use:**

- Unit tests requiring isolation between test cases
- Quick local prototyping without file system setup
- CI/CD pipelines where persistence is not needed

**Configuration:**

```bash
ENVIRONMENT=test
# No additional configuration needed -- InMemory is the default for test
```

The factory automatically selects InMemory when `ENVIRONMENT=test` (using in-memory SQLite for the state store) or when `ENVIRONMENT=dev` with a non-sqlite `DATABASE_BACKEND`.

!!! note "Test environment behavior"
    When `ENVIRONMENT=test`, the state store uses `SQLiteStateStore(":memory:")` -- an in-memory SQLite database that provides full SQL functionality with test isolation. The memory store also uses `SQLiteMemoryStore(":memory:")`.

---

### 2. SQLite

SQLite provides file-based persistence suitable for single-instance local development. The implementation uses `aiosqlite` for async operations with WAL mode for improved concurrency.

**Implementation:** `adapters/state/sqlite/state_store.py` (SQLiteStateStore)

**Features:**

- WAL (Write-Ahead Logging) mode for concurrent reads
- Foreign key enforcement
- Automatic schema initialization on first connection
- PostgreSQL-compatible schema for easy migration
- JSON columns for flexible metadata storage

**Configuration:**

```bash
ENVIRONMENT=dev
DATABASE_BACKEND=sqlite

# Optional: customize file locations (defaults shown)
SQLITE_STATE_PATH=./dev_data/starboard_state.db
SQLITE_MEMORY_PATH=./dev_data/starboard_memory.db
SQLITE_VECTOR_PATH=./dev_data/starboard_vectors.db
SQLITE_REFLEXION_PATH=./dev_data/starboard_reflexion.db
```

**Schema (conversations table):**

```sql
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    data TEXT NOT NULL,        -- JSON: messages and metadata
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    title TEXT,
    tags TEXT,                 -- JSON array
    archived INTEGER DEFAULT 0
);
```

The schema also includes `users`, `user_sessions`, and `user_feedback` tables, all created automatically on first connection.

!!! warning "Not for production"
    The configuration validator will emit a warning if `DATABASE_BACKEND=sqlite` is used with `ENVIRONMENT=staging` or `ENVIRONMENT=production`. SQLite does not support concurrent writes from multiple processes, making it unsuitable for horizontally scaled deployments.

---

### 3. PostgreSQL

PostgreSQL is the standard production backend. It uses `asyncpg` for high-performance async database access with connection pooling.

**Implementation:** `adapters/state/postgres/state_store.py` (PostgresStateStore)

**Features:**

- Connection pooling via `asyncpg.Pool` (configurable min/max)
- JSONB columns for efficient metadata queries
- Native array types for tags
- Full ACID transactions
- pgvector support for vector similarity search in the memory store

**Configuration:**

```bash
ENVIRONMENT=production
DATABASE_BACKEND=postgres
DATABASE_URL=postgres://starboard:secret@db.example.com:5432/starboard_db

# Connection pool tuning
POSTGRES_MIN_POOL_SIZE=5
POSTGRES_MAX_POOL_SIZE=20
POSTGRES_COMMAND_TIMEOUT=60
```

**Required PostgreSQL extensions:**

```sql
-- Required for vector similarity search (memory store)
CREATE EXTENSION IF NOT EXISTS vector;
```

**Connection pool sizing guidance:**

| Deployment Size | Min Pool | Max Pool | Timeout |
|---|---|---|---|
| Small (1-2 replicas) | 2 | 10 | 60s |
| Medium (3-5 replicas) | 5 | 20 | 60s |
| Large (6+ replicas) | 5 | 15 | 30s |

!!! tip "Pool size formula"
    A good starting point: `max_pool = (available_connections / num_replicas) - 2`. Leave headroom for maintenance connections and monitoring tools. PostgreSQL's default `max_connections` is 100.

---

### 4. Databricks Lakebase

Lakebase is Databricks' managed PostgreSQL-compatible service. The Starboard adapter extends the PostgreSQL backend and adds automatic OAuth token lifecycle management.

**Implementation:** `adapters/state/databricks/state_store.py` (DatabricksLakebaseStateStore)

**Architecture:**

The Lakebase adapter inherits all CRUD operations from `PostgresStateStore` and adds:

1. **Databricks SDK integration** -- uses `WorkspaceClient` to resolve instance endpoints
2. **OAuth token generation** -- generates database credentials via the Databricks SDK
3. **Background token refresh** -- a background `asyncio.Task` refreshes tokens every 50 minutes (tokens expire after 1 hour)
4. **SSL enforcement** -- all connections require SSL
5. **Automatic pool recreation** -- after token refresh, the connection pool is recreated with fresh credentials

**Configuration:**

```bash
ENVIRONMENT=production
DATABASE_BACKEND=databricks

# Required Lakebase settings
LAKEBASE_INSTANCE_NAME=my-starboard-lakebase
LAKEBASE_DATABASE_NAME=starboard_db

# Optional OAuth client (falls back to current workspace user)
DATABRICKS_CLIENT_ID=my-service-principal-id

# Pool settings
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
DB_COMMAND_TIMEOUT=30
```

**Token refresh lifecycle:**

```
connect()
  |-- Initialize WorkspaceClient
  |-- Get database instance details
  |-- Generate initial OAuth credentials
  |-- Build connection string (postgresql://...?ssl=require)
  |-- Create asyncpg pool
  |-- Start background refresh task (every 50 minutes)
        |
        +-- Sleep 50 minutes
        +-- Refresh credentials via SDK
        +-- Close old connection pool
        +-- Create new pool with fresh credentials
        +-- Repeat
```

!!! warning "Databricks SDK required"
    The Lakebase adapter requires the `databricks-sdk` package and valid Databricks workspace authentication (either via environment variables or a `.databrickscfg` profile). Ensure `DATABRICKS_HOST` and authentication credentials are configured for the SDK to initialize.

---

### 5. Redis (Cache Only)

Redis serves as the cache backend for session data, rate limiting, and key-value caching. It does not store conversations or long-term memory.

**Implementation:** `adapters/state/redis/cache_store.py` (RedisCacheStore)

**Features:**

- Async operations via `redis.asyncio`
- JSON serialization for complex values
- TTL support for automatic expiration
- Batch operations (`MGET`, pipeline `MSET`) for performance
- Atomic counters (`INCR`, `DECR`) for rate limiting
- Connection pooling built into the Redis client
- Automatic retry on timeout

**Configuration:**

```bash
REDIS_URL=redis://localhost:6379/0
CACHE_BACKEND=redis
CACHE_TTL=300

# Rate limiting can also use Redis
RATE_LIMIT_STORAGE=redis://localhost:6379/1
```

**Connection URL formats:**

```
redis://localhost:6379/0                    # No authentication
redis://:password@localhost:6379/0          # Password authentication
redis://user:password@redis.example.com:6379/0  # Full authentication
rediss://redis.example.com:6380/0           # TLS connection
```

!!! note "Fallback behavior"
    If `REDIS_URL` is not set, the cache factory automatically falls back to `InMemoryCacheStore` with a maximum of 1000 entries. This allows development without a Redis dependency.

---

## Vector Search Setup

Starboard supports vector similarity search for semantic memory recall and semantic caching. The vector search backend is independent of the primary state backend.

### sqlite-vec (Development)

The SQLite memory store uses the `sqlite-vec` extension for vector similarity search with cosine distance.

**Installation:**

```bash
pip install sqlite-vec
```

**Prerequisites:**

Python must be compiled with loadable SQLite extension support. If you use `pyenv`:

```bash
PYTHON_CONFIGURE_OPTS='--enable-loadable-sqlite-extensions' pyenv install 3.12.0
```

**Behavior when unavailable:**

If `sqlite-vec` is not installed or extension loading is not supported, the memory store degrades gracefully:

- Episodes are stored with embeddings serialized as JSON text (instead of BLOB)
- Recall falls back to chronological ordering (most recent episodes)
- A warning is logged: `sqlite_vec_extension_not_available`
- The system continues to function without vector search

### pgvector (Production)

The PostgreSQL memory store uses the `pgvector` extension for native vector operations.

**Setup:**

```sql
-- Enable the extension (requires superuser or rds_superuser)
CREATE EXTENSION IF NOT EXISTS vector;

-- The memory store creates tables with vector columns automatically
-- Example: episodes.embedding is stored as a native vector type
```

**Vector search query pattern (used by `PostgresMemoryStore.recall_episodes_by_embedding`):**

```sql
SELECT id, summary, embedding,
       1 - (embedding <=> $1::vector) AS similarity
FROM episodes
WHERE user_id = $2 AND embedding IS NOT NULL
ORDER BY embedding <=> $1::vector
LIMIT $3;
```

The `<=>` operator computes cosine distance. Results are ranked by cosine similarity (1 - distance).

### In-Memory Vector Store (Fallback)

When neither sqlite-vec nor pgvector is available, the system uses an in-memory vector store:

- Limited to approximately 10,000 vectors
- Ephemeral (lost on restart)
- Auto-bootstrapped with essential data on startup
- Suitable for development and CLI usage

---

## Migration Between Backends

### SQLite to PostgreSQL

1. **Provision PostgreSQL** with pgvector extension:

    ```sql
    CREATE DATABASE starboard_db;
    \c starboard_db
    CREATE EXTENSION IF NOT EXISTS vector;
    ```

2. **Create the schema.** The PostgreSQL state store expects the same table structure. You can use the SQLite schema as reference -- the column types map as follows:

    | SQLite | PostgreSQL |
    |---|---|
    | `TEXT` (JSON) | `JSONB` |
    | `TEXT` (datetime) | `TIMESTAMPTZ` |
    | `INTEGER` (boolean) | `BOOLEAN` |
    | `TEXT[]` (JSON array) | `TEXT[]` |
    | `BLOB` (vector) | `vector(1024)` |

3. **Export data from SQLite:**

    ```bash
    sqlite3 ./dev_data/starboard_state.db \
      ".mode json" \
      "SELECT * FROM conversations;" > conversations.json
    ```

4. **Import into PostgreSQL** using your preferred method (psql `\copy`, a migration script, or application-level export/import).

5. **Update environment variables:**

    ```bash
    ENVIRONMENT=production
    DATABASE_BACKEND=postgres
    DATABASE_URL=postgres://starboard:secret@db.example.com:5432/starboard_db
    ```

6. **Restart the server.** The container will initialize with the PostgreSQL backend.

### PostgreSQL to Databricks Lakebase

Since Lakebase is PostgreSQL-compatible, migration is straightforward:

1. **Create a Lakebase instance** in your Databricks workspace.

2. **Migrate the schema and data** using standard PostgreSQL tools (`pg_dump`/`pg_restore`) since Lakebase speaks the PostgreSQL wire protocol.

3. **Update environment variables:**

    ```bash
    DATABASE_BACKEND=databricks
    LAKEBASE_INSTANCE_NAME=my-starboard-lakebase
    LAKEBASE_DATABASE_NAME=starboard_db
    ```

4. **Remove `DATABASE_URL`** -- the Lakebase adapter builds its own connection string using the SDK.

!!! tip "Test with a staging environment"
    Always test backend migrations in a staging environment first. The configuration validator will reject `DATABASE_BACKEND=sqlite` for staging/production, helping prevent accidental misconfigurations.

---

## Troubleshooting

### SQLite: "extension loading not supported"

**Symptom:** Warning log `sqlite_extension_loading_not_supported` and vector search falls back to chronological ordering.

**Cause:** Python's `sqlite3` module was compiled without `--enable-loadable-sqlite-extensions`.

**Fix:**

```bash
# Using pyenv
PYTHON_CONFIGURE_OPTS='--enable-loadable-sqlite-extensions' pyenv install 3.12.0
pyenv local 3.12.0

# Using system Python (macOS with Homebrew)
brew install sqlite3
export LDFLAGS="-L/opt/homebrew/opt/sqlite/lib"
export CPPFLAGS="-I/opt/homebrew/opt/sqlite/include"
```

### PostgreSQL: "DATABASE_URL required"

**Symptom:** `ValueError: DATABASE_URL required for environment: production`

**Cause:** The `DATABASE_BACKEND` is set to `postgres` but `DATABASE_URL` is not set.

**Fix:** Set the `DATABASE_URL` environment variable:

```bash
DATABASE_URL=postgres://user:password@host:5432/dbname
```

### Lakebase: Token refresh failures

**Symptom:** Log entries with `databricks_token_background_refresh_error`.

**Cause:** The Databricks SDK cannot generate new credentials, often due to expired workspace authentication or network issues.

**Fix:**

- Verify `DATABRICKS_HOST` is set and reachable
- Ensure the service principal or user has permissions to generate database credentials
- Check that the Lakebase instance is running in the workspace
- The background task will automatically retry on the next 50-minute cycle

### Redis: Connection refused

**Symptom:** `ConnectionError: Failed to connect to Redis`

**Cause:** Redis is not running or the URL is incorrect.

**Fix:**

```bash
# Check Redis is running
redis-cli ping
# Should return: PONG

# Verify the URL format
REDIS_URL=redis://localhost:6379/0
```

The cache layer will automatically fall back to in-memory caching if Redis is unavailable at startup, but if Redis becomes unavailable after the initial connection, cache operations will fail.

### Configuration validation errors

**Symptom:** `ValueError: Configuration validation failed` with a list of errors at startup.

**Common validations:**

- `postgres_min_pool_size` must be <= `postgres_max_pool_size`
- `cache_ttl` must be non-negative
- `REDIS_URL` required when `CACHE_BACKEND=redis`
- SQLite backend produces a warning for staging/production environments

Run validation manually to check your configuration:

```python
from starboard_server.infra.core.config import EnvConfig

config = EnvConfig.from_env()
config.validate()  # Raises ValueError with all issues listed
```

### Container not initialized

**Symptom:** `RuntimeError: Container not initialized. Call initialize() first.`

**Cause:** Attempting to access stores before the application lifespan has completed initialization.

**Fix:** Ensure you access the container only after `lifespan()` has completed startup. In route handlers, use `get_container()` from `main.py`, which will raise a clear error if the container is not yet ready.

---

## Source Files

| File | Description |
|---|---|
| `infra/core/config.py` | `EnvConfig` dataclass with all environment variables |
| `infra/core/state_factory.py` | Factory functions: `create_state_store`, `create_memory_store`, `create_cache_store` |
| `infra/core/container.py` | `Container` DI class managing all store lifecycles |
| `adapters/state/sqlite/state_store.py` | `SQLiteStateStore` implementation |
| `adapters/state/sqlite/memory_store.py` | `SQLiteMemoryStore` with sqlite-vec support |
| `adapters/state/postgres/state_store.py` | `PostgresStateStore` with asyncpg pooling |
| `adapters/state/postgres/memory_store.py` | `PostgresMemoryStore` with pgvector |
| `adapters/state/databricks/state_store.py` | `DatabricksLakebaseStateStore` with OAuth refresh |
| `adapters/state/databricks/memory_store.py` | `DatabricksLakebaseMemoryStore` with OAuth refresh |
| `adapters/state/databricks/config.py` | `DatabricksLakebaseConfig` dataclass |
| `adapters/state/inmemory/state_store.py` | `InMemoryStateStore` (dict-backed) |
| `adapters/state/redis/cache_store.py` | `RedisCacheStore` with batch operations |
| `infra/rag/services/vector_store_factory.py` | Vector store factory with automatic fallback |
| `infra/cache/semantic_cache.py` | `SemanticCache` using vector similarity |

All paths are relative to `packages/starboard-server/starboard_server/`.
