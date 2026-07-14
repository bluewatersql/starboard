# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""SQLite storage adapters for development and testing.

This module provides SQLite-backed implementations for state, memory, and cache stores.
SQLite offers an embedded database solution with no external dependencies, ideal for:

- Local development (file-based persistence)
- Testing (in-memory for isolation)
- Small deployments (single-instance servers)

Features:
- Full async support via aiosqlite
- Vector similarity search via sqlite-vec extension
- Schema migrations embedded in code
- PostgreSQL-compatible SQL for easy migration
- WAL mode for better concurrency

Architecture:
    SQLiteStateStore: Conversation state and messages
    SQLiteMemoryStore: Long-term memory with vector embeddings
    SQLiteCacheStore: TTL-based caching (optional, in-memory also works)

Example:
    ```python
    # File-based for development
    store = SQLiteStateStore("./dev_data/starboard.db")
    await store.connect()

    # In-memory for testing
    store = SQLiteStateStore(":memory:")
    await store.connect()
    ```

References:
    - aiosqlite: https://aiosqlite.omnilib.dev/
    - sqlite-vec: https://github.com/asg017/sqlite-vec
"""

from starboard.adapters.state.sqlite.memory_store import SQLiteMemoryStore
from starboard.adapters.state.sqlite.state_store import SQLiteStateStore

__all__ = ["SQLiteStateStore", "SQLiteMemoryStore"]
