# SQLite Storage Adapters

Embedded database solution for development, testing, and single-instance deployments.

## Overview

SQLite adapters provide zero-dependency storage with full async support and vector similarity search capabilities. Ideal for local development, automated testing, and small single-instance deployments.

## Features

- **Zero External Dependencies**: No PostgreSQL, Redis, or other services required
- **Full Async Support**: Native async/await via `aiosqlite`
- **Vector Similarity Search**: Powered by `sqlite-vec` extension
- **Flexible Persistence**: File-based (dev) or in-memory (test)
- **PostgreSQL-Compatible Schema**: Easy migration path to production
- **WAL Mode**: Better concurrency with Write-Ahead Logging

## Architecture

```
SQLite Adapters
├── SQLiteStateStore       # Conversation state (messages, metadata)
├── SQLiteMemoryStore      # Long-term memory (episodes, facts, profiles)
└── Schema Migrations      # Embedded in code (auto-applied on connect)
```

## Usage

### Development (File-Based)

```python
from starboard.adapters.state.sqlite import SQLiteStateStore, SQLiteMemoryStore

# Create stores with file persistence
state_store = SQLiteStateStore("./dev_data/starboard_state.db")
memory_store = SQLiteMemoryStore("./dev_data/starboard_memory.db")

# Connect (initializes schema)
await state_store.connect()
await memory_store.connect()

# Use like any other store
conversation = Conversation(...)
await state_store.save_conversation(conversation)

# Close when done
await state_store.close()
await memory_store.close()
```

### Testing (In-Memory)

```python
# In-memory databases for isolated tests
state_store = SQLiteStateStore(":memory:")
memory_store = SQLiteMemoryStore(":memory:")

await state_store.connect()
await memory_store.connect()

# Each test gets isolated database
# No cleanup needed - garbage collected when closed
```

### Factory Pattern (Recommended)

```python
from starboard.infra.config import AppConfig
from starboard.infra.state_factory import create_state_store, create_memory_store

# Configuration-driven store creation
config = AppConfig(
    environment="dev",
    database_backend="sqlite",
    sqlite_state_path="./dev_data/state.db",
    sqlite_memory_path="./dev_data/memory.db",
)

state_store = create_state_store(config)
memory_store = create_memory_store(config)

await state_store.connect()
await memory_store.connect()
```

## Environment Configuration

### Development with Persistence

```bash
export ENVIRONMENT=dev
export DATABASE_BACKEND=sqlite
export SQLITE_STATE_PATH=./dev_data/starboard_state.db
export SQLITE_MEMORY_PATH=./dev_data/starboard_memory.db
```

### Testing with Isolation

```bash
export ENVIRONMENT=test
# Automatically uses :memory: databases
```

### Default Configuration (No Persistence)

```bash
export ENVIRONMENT=dev
# Uses in-memory stores by default
```

## Vector Similarity Search

SQLite memory store supports vector embeddings via the `sqlite-vec` extension.

```python
# Store episode with embedding
episode = Episode(
    id="ep_123",
    user_id="user_456",
    summary="User optimized query performance",
    embedding=[0.1, 0.2, 0.3, ...],  # 1536 dimensions
    created_at=datetime.now(UTC),
)
await memory_store.store_episode(episode)

# Semantic search (when vector extension available)
query_embedding = [0.15, 0.25, 0.35, ...]
episodes = await memory_store.recall_episodes(
    user_id="user_456",
    query_embedding=query_embedding,
    limit=5
)
```

**Note**: Vector similarity search automatically falls back to recency-based retrieval if `sqlite-vec` extension is not available.

## Schema

### State Store (Conversations)

```sql
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    data TEXT NOT NULL,           -- JSON conversation data
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    title TEXT,
    tags TEXT,                    -- JSON array
    archived INTEGER DEFAULT 0    -- Boolean (0/1)
);

-- Indexes for performance
CREATE INDEX idx_conversations_user_id ON conversations(user_id);
CREATE INDEX idx_conversations_updated_at ON conversations(updated_at DESC);
CREATE INDEX idx_conversations_user_updated ON conversations(user_id, updated_at DESC);
CREATE INDEX idx_conversations_archived ON conversations(archived, user_id, updated_at DESC);
```

### Memory Store (Episodes, Facts, Profiles)

```sql
-- Episodic memory
CREATE TABLE episodes (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    conversation_id TEXT,
    summary TEXT NOT NULL,
    key_points TEXT,              -- JSON array
    embedding BLOB,               -- Vector embedding
    created_at TEXT NOT NULL,
    metadata TEXT                 -- JSON object
);

-- Semantic memory
CREATE TABLE facts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    statement TEXT NOT NULL,
    category TEXT NOT NULL,
    confidence REAL NOT NULL,
    source TEXT,
    verified INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata TEXT
);

-- User profiles
CREATE TABLE user_profiles (
    user_id TEXT PRIMARY KEY,
    data TEXT NOT NULL,           -- JSON profile data
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

## Performance Characteristics

- **Write Throughput**: ~1000 conversations/sec (single writer)
- **Read Throughput**: ~10,000 conversations/sec (multiple readers)
- **Concurrency**: Good for single-instance (WAL mode)
- **Database Size**: ~1KB per conversation, ~500B per episode
- **Startup Time**: <10ms (in-memory), <100ms (file-based)

## Limitations

1. **Single Instance**: Not designed for multi-instance deployments
2. **Write Concurrency**: Limited compared to PostgreSQL
3. **No Replication**: No built-in replication/backup
4. **Vector Search**: Simpler than pgvector (but sufficient for dev/test)

## Migration Path

SQLite schema is intentionally PostgreSQL-compatible for easy migration:

```bash
# Development with SQLite
export DATABASE_BACKEND=sqlite

# Switch to PostgreSQL for production
export DATABASE_BACKEND=postgres
export DATABASE_URL=postgresql://user:pass@host:5432/db

# No code changes needed!
```

## Testing

Comprehensive test coverage in `tests/`:

- **Unit Tests**: `tests/unit/adapters/test_sqlite_*.py`
- **Integration Tests**: `tests/integration/adapters/test_sqlite_integration.py`

Run tests:

```bash
# Unit tests only
pytest tests/unit/adapters/test_sqlite_*.py -v

# Integration tests
pytest tests/integration/adapters/test_sqlite_integration.py -v

# All SQLite tests
pytest -k sqlite -v
```

## Dependencies

```toml
# pyproject.toml
dependencies = [
    "aiosqlite>=0.19.0",    # Async SQLite driver
    "sqlite-vec>=0.1.1",    # Vector similarity search
]
```

## FAQ

**Q: Should I use SQLite in production?**  
A: SQLite is suitable for single-instance deployments with moderate load. For multi-instance or high-concurrency deployments, use PostgreSQL.

**Q: How do I backup SQLite databases?**  
A: For file-based databases, simply copy the `.db` files. For running instances, use SQLite's backup API or stop the server first.

**Q: Can I use SQLite with Docker?**  
A: Yes! Mount a volume for persistence:
```bash
docker run -v ./data:/app/data -e SQLITE_STATE_PATH=/app/data/state.db ...
```

**Q: What if `sqlite-vec` extension fails to load?**  
A: Vector search automatically falls back to recency-based retrieval. All other functionality works normally.

**Q: How do I migrate from SQLite to PostgreSQL?**  
A: 
1. Export data from SQLite
2. Set up PostgreSQL and run migrations
3. Import data to PostgreSQL
4. Update `DATABASE_BACKEND=postgres`
5. Restart server

See `docs/MIGRATION.md` for detailed steps.

## References

- [aiosqlite Documentation](https://aiosqlite.omnilib.dev/)
- [sqlite-vec Documentation](https://github.com/asg017/sqlite-vec)
- [SQLite WAL Mode](https://www.sqlite.org/wal.html)
- [SQLite Best Practices](https://www.sqlite.org/bestpractice.html)

---

**Created**: November 21, 2025  
**Version**: 1.0.0

