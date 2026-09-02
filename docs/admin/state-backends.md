# State Management

This guide covers how Starboard manages conversation state, sessions, and caching.

!!! info "Memory-only state"
    Starboard uses `database_backend="memory"` — the **only** supported value. All conversation state is held in Python dictionaries for the lifetime of the process. There is no external database to provision. Durable session persistence across CLI runs is provided by the **JSON-file `SessionManager`** (`starboard.cli.sessions`), which writes session data to `~/.starboard/sessions.db` by default. Source of truth: `infra/core/config.py` (`EnvConfig`).

---

## Architecture Overview

Starboard manages two runtime concerns:

| Concern | Purpose | Backend |
|---|---|---|
| **State Store** | In-process conversation state (messages, metadata) | `InMemoryStateStore` (only option) |
| **Cache Store** | Key-value caching (tool results, sessions) | In-memory (default) or Redis (opt-in) |

CLI session durability across process restarts is handled separately by the `SessionManager` in `starboard.cli.sessions`, which persists named sessions as JSON under `~/.starboard/sessions.db` (configurable via `--session-db`).

!!! note "UC-native storage"
    A UC-native storage layer exists in `infra/storage/uc_adapter.py` (`UCStorageAdapter`) for the durable cluster-observation tool. This is **not** a selectable `database_backend`; it is an internal implementation detail of one specific tool and is not configurable as a state backend.

---

## Environment Variables Reference

### Core Configuration

| Variable | Values | Default | Description |
|---|---|---|---|
| `ENVIRONMENT` | `dev`, `test`, `staging`, `production` | `dev` | Deployment environment |
| `CACHE_BACKEND` | `memory`, `redis` | `memory` | Cache layer backend (Redis selected when `REDIS_URL` is set) |

### Redis Configuration (Cache Only)

| Variable | Default | Description |
|---|---|---|
| `REDIS_URL` | -- | Redis connection URL: `redis://host:port/db` |
| `CACHE_TTL` | `300` | Default cache TTL in seconds (5 minutes) |

---

## State Store: InMemory (default and only option)

The in-memory backend stores all conversation state in Python dictionaries. State is lost when the process exits. It is the **only** supported backend and carries **no external driver**, so it works on a bare `pip install starboard`.

**Implementation:** `adapters/state/inmemory/state_store.py` (InMemoryStateStore)

**When to use:**

- All deployments — this is the only option
- CLI, notebooks, single-process usage
- Unit tests requiring isolation between test cases

**Configuration:**

```bash
# No configuration required — memory is the only backend.
```

---

## CLI Session Persistence

The `SessionManager` (`starboard.cli.sessions`) writes named CLI sessions to a local JSON file so you can resume a conversation across process restarts. State is stored locally on the machine running the CLI; it is never written to a shared database.

```bash
# Resume or continue a named session
starboard --goal "..." --session my-project
starboard --goal "Follow-up question" --session my-project

# Custom session file location
starboard --session-db /path/to/sessions.db --goal "..."
```

The session file path defaults to `~/.starboard/sessions.db`.

---

## Redis (Cache Only)

Redis serves as an optional cache backend for tool results and session data. It does not store conversations or long-term memory.

**Implementation:** `adapters/state/redis/cache_store.py` (RedisCacheStore)

**Features:**

- Async operations via `redis.asyncio`
- JSON serialization for complex values
- TTL support for automatic expiration
- Batch operations (`MGET`, pipeline `MSET`) for performance
- Atomic counters for rate limiting
- Connection pooling built into the Redis client
- Automatic retry on timeout

**Configuration:**

```bash
REDIS_URL=redis://localhost:6379/0
CACHE_BACKEND=redis
CACHE_TTL=300
```

**Connection URL formats:**

```
redis://localhost:6379/0                       # No authentication
redis://:password@localhost:6379/0             # Password authentication
redis://user:password@redis.example.com:6379/0 # Full authentication
rediss://redis.example.com:6380/0              # TLS connection
```

!!! note "Fallback behavior"
    If `REDIS_URL` is not set, the cache factory automatically falls back to `InMemoryCacheStore`. This allows development and CLI usage without a Redis dependency.

---

## Analytics Context (RAG)

Analytics context is built from **on-disk curated reference files** (`starboard_core/rag/knowledge/domains/*.md`) plus query packs. There is no vector store, no embeddings pipeline, and no vector database. The `vector_backend` configuration knob has been removed; on-disk reference files are the only RAG path.

---

## Troubleshooting

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

If Redis becomes unavailable after the initial connection, cache operations will fail. The cache layer falls back to in-memory caching only when Redis is unavailable **at startup**.

### Configuration validation errors

**Symptom:** `ValueError: Configuration validation failed` at startup.

**Common validations:**

- `cache_ttl` must be non-negative
- `REDIS_URL` required when `CACHE_BACKEND=redis`

Run validation manually:

```python
from starboard.infra.core.config import EnvConfig

config = EnvConfig.from_env()
config.validate_config()  # Raises ValueError with all issues listed
```

### Container not initialized

**Symptom:** `RuntimeError: Container not initialized. Call initialize() first.`

**Fix:** Ensure you access the container only after `lifespan()` has completed startup. In route handlers, use `get_container()` from `main.py`.

---

## Source Files

| File | Description |
|---|---|
| `infra/core/config.py` | `EnvConfig` dataclass with all environment variables |
| `infra/core/state_factory.py` | Factory functions: `create_state_store`, `create_cache_store` |
| `infra/core/container.py` | `Container` DI class managing all store lifecycles |
| `adapters/state/inmemory/state_store.py` | `InMemoryStateStore` (dict-backed) |
| `adapters/state/redis/cache_store.py` | `RedisCacheStore` with batch operations |
| `starboard/cli/sessions.py` | `SessionManager` — JSON-file durable CLI sessions |
| `infra/storage/uc_adapter.py` | `UCStorageAdapter` — cluster-observation tool storage (internal) |

All paths are relative to `packages/starboard/starboard/`.
