"""
SQLite-based vector store using sqlite-vec extension.

This module provides a production-ready vector similarity search implementation
using SQLite with the sqlite-vec extension for efficient cosine similarity.

Key features:
- Async operations with aiosqlite
- Cosine similarity search
- Metadata filtering
- Batch upsert operations
- Connection pooling for performance
- Loop-safe resource management

Example:
    >>> store = SQLiteVectorStore("vectors.db")
    >>> await store.initialize()
    >>>
    >>> # Store vectors
    >>> vectors = [
    ...     VectorRecord(
    ...         id="vec_1",
    ...         embedding=[0.1, 0.2, ...],
    ...         metadata={"source": "docs"},
    ...         content="How to optimize clusters"
    ...     )
    ... ]
    >>> await store.upsert(vectors)
    >>>
    >>> # Search
    >>> results = await store.search(query_embedding, top_k=5)
"""

import asyncio
import json
import re
import struct
from pathlib import Path
from typing import Any, ClassVar

import aiosqlite
from starboard_core.foundations.models import VectorRecord, VectorSearchResult


def _get_vec_extension_path() -> str:
    """Get the path to the sqlite-vec extension.

    Returns:
        Path to vec0 extension file

    Raises:
        RuntimeError: If sqlite-vec package is not installed
    """
    try:
        import sqlite_vec

        # Get the package directory
        package_dir = Path(sqlite_vec.__file__).parent

        # Try common extension names based on platform
        for ext_name in ["vec0.dylib", "vec0.so", "vec0.dll"]:
            ext_path = package_dir / ext_name
            if ext_path.exists():
                return str(ext_path)

        raise RuntimeError(
            f"sqlite-vec extension file not found in {package_dir}. "
            f"Expected one of: vec0.dylib, vec0.so, vec0.dll"
        )
    except ImportError as e:
        raise RuntimeError(
            "sqlite-vec package not installed. Install with: pip install sqlite-vec"
        ) from e


class SQLiteVectorStore:
    """SQLite-based vector store using sqlite-vec extension with connection pooling.

    This implementation uses the sqlite-vec extension for efficient vector
    similarity search with cosine distance. It's suitable for:
    - Development and testing
    - Small to medium datasets (< 1M vectors)
    - Embedded deployments

    For production scale (> 1M vectors), consider PostgresVectorStore with pgvector.

    Connection Pooling:
        - Maintains a pool of reusable connections per database path
        - Max 5 connections per SQLite database (optimal for WAL mode)
        - Connections shared across all store instances with same db_path
        - Eager initialization on first use
        - Loop-safe: Handles event loop restarts gracefully

    Attributes:
        db_path: Path to SQLite database file
        dimension: Vector embedding dimension (default: 1536 for OpenAI)

    Note:
        Requires sqlite-vec extension to be available.
        Install: https://github.com/asg017/sqlite-vec
    """

    # Class-level state: db_path -> {"lock": Lock, "pool": List[Connection], "loop": AbstractEventLoop}
    _shared_state: ClassVar[dict[str, dict[str, Any]]] = {}
    _pool_max_size = 5  # Max connections per SQLite DB (optimal for WAL mode)

    # Allowlisted collection names (from CollectionType enum values + "default")
    _ALLOWED_COLLECTION_NAMES: ClassVar[frozenset[str]] = frozenset(
        {
            "default",
            "tables",
            "nuance",
            "codebook",
            "facets",
            "learnings",
        }
    )
    # Regex fallback for future collection names: alphanumeric + underscore only
    _COLLECTION_NAME_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"^[a-z][a-z0-9_]{0,63}$"
    )

    # Allowlisted ORDER BY clauses for search_by_metadata
    _ALLOWED_ORDER_BY: ClassVar[frozenset[str]] = frozenset(
        {
            "created_at ASC",
            "created_at DESC",
            "id ASC",
            "id DESC",
        }
    )

    def __init__(
        self, db_path: str, dimension: int = 1536, collection_name: str = "default"
    ):
        """Initialize SQLite vector store.

        Args:
            db_path: Path to SQLite database file
            dimension: Vector embedding dimension
            collection_name: Name for this collection (creates separate tables).
                Must be in _ALLOWED_COLLECTION_NAMES or match _COLLECTION_NAME_PATTERN.

        Raises:
            ValueError: If collection_name is not allowlisted or doesn't match safe pattern
        """
        self._validate_collection_name(collection_name)
        self.db_path = db_path
        self.dimension = dimension
        self.collection_name = collection_name
        self._initialized = False
        self._ext_path: str | None = None  # Cache the extension path

    @classmethod
    def _validate_collection_name(cls, name: str) -> None:
        """Validate collection name against allowlist and safe pattern.

        Args:
            name: Collection name to validate

        Raises:
            ValueError: If name is not safe for use in SQL identifiers
        """
        if name in cls._ALLOWED_COLLECTION_NAMES:
            return
        if not cls._COLLECTION_NAME_PATTERN.match(name):
            raise ValueError(
                f"Invalid collection name: {name!r}. "
                f"Must be one of {sorted(cls._ALLOWED_COLLECTION_NAMES)} "
                f"or match pattern {cls._COLLECTION_NAME_PATTERN.pattern}"
            )

    @classmethod
    def _validate_order_by(cls, order_by: str) -> str:
        """Validate ORDER BY clause against allowlist.

        Args:
            order_by: ORDER BY clause to validate

        Returns:
            Validated ORDER BY clause

        Raises:
            ValueError: If order_by is not in the allowlist
        """
        if order_by not in cls._ALLOWED_ORDER_BY:
            raise ValueError(
                f"Invalid ORDER BY clause: {order_by!r}. "
                f"Must be one of {sorted(cls._ALLOWED_ORDER_BY)}"
            )
        return order_by

    @classmethod
    def _get_shared_state_for_path(cls, db_path: str) -> dict[str, Any]:
        """Get shared state for a database path, ensuring loop safety.

        Returns:
            Dict containing lock, pool, and loop for the db_path

        Raises:
            RuntimeError: If no event loop is running
        """
        current_loop = asyncio.get_running_loop()

        state = cls._shared_state.get(db_path)

        # If state exists but loop mismatch, discard it (old loop is dead/invalid)
        if state and state["loop"] is not current_loop:
            state = None

        if state is None:
            state = {"lock": asyncio.Lock(), "pool": [], "loop": current_loop}
            cls._shared_state[db_path] = state

        return state

    async def _acquire_connection(self) -> aiosqlite.Connection:
        """Acquire a connection from the pool.

        Returns:
            Database connection with vec0 extension loaded

        Raises:
            RuntimeError: If extension cannot be loaded
        """
        state = self._get_shared_state_for_path(self.db_path)
        lock = state["lock"]
        pool = state["pool"]

        async with lock:
            # Try to get connection from pool
            if pool:
                return pool.pop()

            # Pool empty - create new connection
            return await self._create_connection()

    async def _create_connection(self) -> aiosqlite.Connection:
        """Create a new database connection with sqlite-vec extension loaded.

        Returns:
            Database connection with vec0 extension loaded

        Raises:
            RuntimeError: If extension cannot be loaded or extension support not available
        """
        # Connect with timeout for better concurrent access handling
        db = await aiosqlite.connect(
            self.db_path,
            timeout=30.0,  # 30 second timeout for concurrent access
        )

        try:
            # Check if enable_load_extension is available (requires sqlite3 compiled with extension support)
            if not hasattr(db, "enable_load_extension"):
                await db.close()
                raise RuntimeError(
                    "SQLite extension loading is not supported. "
                    "Your Python's sqlite3 module was not compiled with loadable extension support. "
                    "On macOS with pyenv, rebuild Python with: "
                    "PYTHON_CONFIGURE_OPTS='--enable-loadable-sqlite-extensions --enable-optimizations' "
                    "LDFLAGS='-L/opt/homebrew/opt/sqlite/lib' "
                    "CPPFLAGS='-I/opt/homebrew/opt/sqlite/include' "
                    "pyenv install <python_version>"
                )

            await db.enable_load_extension(True)

            # Get extension path (cached after first call)
            if self._ext_path is None:
                self._ext_path = _get_vec_extension_path()

            await db.load_extension(self._ext_path)
            return db
        except AttributeError as e:
            # Catch the specific AttributeError when enable_load_extension doesn't exist
            await db.close()
            raise RuntimeError(
                "SQLite extension loading is not supported. "
                "Your Python's sqlite3 module was not compiled with loadable extension support. "
                f"Error: {e}. "
                "On macOS with pyenv, rebuild Python with: "
                "PYTHON_CONFIGURE_OPTS='--enable-loadable-sqlite-extensions --enable-optimizations' "
                "LDFLAGS='-L/opt/homebrew/opt/sqlite/lib' "
                "CPPFLAGS='-I/opt/homebrew/opt/sqlite/include' "
                "pyenv install <python_version>"
            ) from e
        except Exception as e:
            await db.close()
            raise RuntimeError(
                f"Failed to load sqlite-vec extension. "
                f"Install from https://github.com/asg017/sqlite-vec. Error: {e}"
            ) from e

    async def _release_connection(self, conn: aiosqlite.Connection) -> None:
        """Return a connection to the pool.

        Args:
            conn: Connection to return to pool
        """
        state = self._get_shared_state_for_path(self.db_path)
        lock = state["lock"]
        pool = state["pool"]

        async with lock:
            # Return to pool if not at max size, otherwise close
            if len(pool) < self._pool_max_size:
                pool.append(conn)
            else:
                await conn.close()

    @classmethod
    async def close_pool(cls, db_path: str) -> None:
        """Close all connections in the pool for a specific database.

        Args:
            db_path: Database path whose pool should be closed
        """
        # Don't create new state if it doesn't exist
        if db_path not in cls._shared_state:
            return

        # Check loop safety safely
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        state = cls._shared_state[db_path]

        # If loop mismatch, we can't safely close connections. Just remove state.
        if current_loop and state["loop"] is not current_loop:
            del cls._shared_state[db_path]
            return

        # If we are here, loops match or we are optimistic.
        # Use the lock to safely close connections
        lock = state["lock"]
        pool = state["pool"]

        try:
            async with lock:
                for conn in pool:
                    await conn.close()
                pool.clear()
        except Exception:
            # If lock fails, just ignore
            pass

        # Remove state
        if db_path in cls._shared_state:
            del cls._shared_state[db_path]

    @classmethod
    async def close_all_pools(cls) -> None:
        """Close all connection pools (use on application shutdown)."""
        for db_path in list(cls._shared_state.keys()):
            await cls.close_pool(db_path)

    async def initialize(self) -> None:
        """Initialize the vector store.

        Creates tables and loads the sqlite-vec extension.
        Uses connection from pool for efficiency.

        Raises:
            RuntimeError: If sqlite-vec extension cannot be loaded
        """
        # Create directory for file-based databases
        if self.db_path != ":memory:":
            db_file = Path(self.db_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)

        db = await self._acquire_connection()
        try:
            # Enable WAL mode FIRST (persists to the database file)
            # This must be done before creating tables for optimal concurrency
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA busy_timeout=30000")  # 30s busy timeout

            # Create vectors table (collection-specific)
            vectors_table = f"vectors_{self.collection_name}"
            await db.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {vectors_table} (
                    id TEXT PRIMARY KEY,
                    embedding BLOB NOT NULL,
                    metadata TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # Create virtual table for vector search (collection-specific)
            # Note: vec0 requires explicit dimension
            vec_index_table = f"vec_index_{self.collection_name}"
            await db.execute(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS {vec_index_table} USING vec0(
                    id TEXT PRIMARY KEY,
                    embedding float[{self.dimension}]
                )
                """
            )

            # Create index on metadata for filtering
            await db.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{vectors_table}_metadata ON {vectors_table}(metadata)"
            )

            await db.commit()
            self._initialized = True
        finally:
            await self._release_connection(db)

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        """Search for similar vectors using cosine similarity.

        Args:
            query_embedding: Query vector
            top_k: Maximum number of results
            filters: Optional metadata filters (e.g., {"source": "docs"})

        Returns:
            List of search results ordered by similarity (highest first)

        Raises:
            RuntimeError: If store not initialized
            ValueError: If embedding dimension mismatch

        Example:
            >>> results = await store.search(
            ...     query_embedding=[0.1, 0.2, ...],
            ...     top_k=10,
            ...     filters={"type": "documentation"}
            ... )
        """
        if not self._initialized:
            await self.initialize()

        if len(query_embedding) != self.dimension:
            raise ValueError(
                f"Embedding dimension mismatch: expected {self.dimension}, "
                f"got {len(query_embedding)}"
            )

        db = await self._acquire_connection()
        try:
            # Convert embedding to bytes for sqlite-vec
            embedding_bytes = struct.pack(f"{len(query_embedding)}f", *query_embedding)

            # Build query with optional filters
            if filters:
                # Parse metadata JSON and filter
                filter_conditions = []
                filter_values_list = []
                for key, value in filters.items():
                    # JSON extract in SQLite
                    if isinstance(value, list):
                        # Handle IN clause for list values
                        placeholders = ",".join("?" * len(value))
                        filter_conditions.append(
                            f"json_extract(v.metadata, '$.{key}') IN ({placeholders})"
                        )
                        filter_values_list.extend(value)
                    else:
                        # Handle equality for single values
                        filter_conditions.append(
                            f"json_extract(v.metadata, '$.{key}') = ?"
                        )
                        filter_values_list.append(value)

                filter_clause = " AND " + " AND ".join(filter_conditions)
                filter_values = tuple(filter_values_list)
            else:
                filter_clause = ""
                filter_values = ()

            # Search using vec_distance_cosine
            # Lower distance = more similar, so we convert to similarity score
            vectors_table = f"vectors_{self.collection_name}"
            vec_index_table = f"vec_index_{self.collection_name}"
            cursor = await db.execute(
                f"""
                SELECT v.id, v.metadata, v.content,
                       vec_distance_cosine(vi.embedding, ?) as distance
                FROM {vectors_table} v
                JOIN {vec_index_table} vi ON v.id = vi.id
                WHERE 1=1{filter_clause}
                ORDER BY distance ASC
                LIMIT ?
                """,
                (embedding_bytes, *filter_values, top_k),
            )

            rows = await cursor.fetchall()

            results = []
            for row in rows:
                id_, metadata_json, content, distance = row
                # Convert distance to similarity score (0-1, higher is better)
                similarity_score = 1.0 - distance
                results.append(
                    VectorSearchResult(
                        id=id_,
                        score=max(0.0, similarity_score),  # Clamp to [0, 1]
                        metadata=json.loads(metadata_json),
                        content=content,
                    )
                )

            return results
        finally:
            await self._release_connection(db)

    async def search_by_metadata(
        self,
        *,
        top_k: int = 5,
        filters: dict[str, Any],
        order_by: str = "created_at DESC",
    ) -> list[VectorSearchResult]:
        """
        Return rows matching metadata filters with NO vector similarity.
        Useful for deterministic expansion like: fetch all chunks for table_fqn + doc_type.
        """
        if not self._initialized:
            await self.initialize()

        # Validate ORDER BY against allowlist to prevent SQL injection
        validated_order_by = self._validate_order_by(order_by)

        db = await self._acquire_connection()
        try:
            vectors_table = f"vectors_{self.collection_name}"

            # Build filter clause (same logic as in search())
            filter_conditions = []
            filter_values_list: list[Any] = []
            for key, value in (filters or {}).items():
                if isinstance(value, list):
                    placeholders = ",".join("?" * len(value))
                    filter_conditions.append(
                        f"json_extract(v.metadata, '$.{key}') IN ({placeholders})"
                    )
                    filter_values_list.extend(value)
                else:
                    filter_conditions.append(f"json_extract(v.metadata, '$.{key}') = ?")
                    filter_values_list.append(value)

            where_clause = ""
            if filter_conditions:
                where_clause = "WHERE " + " AND ".join(filter_conditions)

            sql = f"""
            SELECT v.id, v.metadata, v.content
            FROM {vectors_table} v
            {where_clause}
            ORDER BY {validated_order_by}
            LIMIT ?
            """

            params = (*filter_values_list, top_k)
            cursor = await db.execute(sql, params)

            rows = await cursor.fetchall()

            results: list[VectorSearchResult] = []
            for id_, metadata_json, content in rows:
                results.append(
                    VectorSearchResult(
                        id=id_,
                        score=1.0,  # no semantic score; treat as "matched"
                        metadata=json.loads(metadata_json),
                        content=content,
                    )
                )
            return results
        finally:
            await self._release_connection(db)

    async def upsert(self, vectors: list[VectorRecord]) -> None:
        """Insert or update vectors in batch.

        Args:
            vectors: List of vector records to upsert

        Raises:
            RuntimeError: If store not initialized
            ValueError: If vectors list is empty or has dimension mismatch
        """
        if not self._initialized:
            await self.initialize()

        if not vectors:
            raise ValueError("Cannot upsert empty vector list")

        # Validate dimensions
        for vec in vectors:
            if len(vec.embedding) != self.dimension:
                raise ValueError(
                    f"Vector {vec.id} has wrong dimension: "
                    f"expected {self.dimension}, got {len(vec.embedding)}"
                )

        db = await self._acquire_connection()
        try:
            vectors_table = f"vectors_{self.collection_name}"
            vec_index_table = f"vec_index_{self.collection_name}"

            # Use transaction for batch insert
            async with db.execute("BEGIN"):
                for vec in vectors:
                    embedding_bytes = struct.pack(
                        f"{len(vec.embedding)}f", *vec.embedding
                    )
                    metadata_json = json.dumps(vec.metadata)

                    # Upsert into vectors table
                    await db.execute(
                        f"""
                        INSERT OR REPLACE INTO {vectors_table} (id, embedding, metadata, content)
                        VALUES (?, ?, ?, ?)
                        """,
                        (vec.id, embedding_bytes, metadata_json, vec.content),
                    )

                    # For sqlite-vec virtual tables, we need to DELETE then INSERT
                    # (INSERT OR REPLACE doesn't work with virtual tables)
                    await db.execute(
                        f"DELETE FROM {vec_index_table} WHERE id = ?",
                        (vec.id,),
                    )
                    await db.execute(
                        f"""
                        INSERT INTO {vec_index_table} (id, embedding)
                        VALUES (?, ?)
                        """,
                        (vec.id, embedding_bytes),
                    )

            await db.commit()
        finally:
            await self._release_connection(db)

    async def delete(self, ids: list[str]) -> None:
        """Delete vectors by ID.

        Args:
            ids: List of vector IDs to delete

        Raises:
            RuntimeError: If store not initialized
        """
        if not self._initialized:
            await self.initialize()

        if not ids:
            return

        db = await self._acquire_connection()
        try:
            vectors_table = f"vectors_{self.collection_name}"
            vec_index_table = f"vec_index_{self.collection_name}"

            # Use transaction for batch delete
            async with db.execute("BEGIN"):
                # Create placeholders for IN clause
                placeholders = ",".join("?" * len(ids))

                # Delete from vectors table
                await db.execute(
                    f"DELETE FROM {vectors_table} WHERE id IN ({placeholders})", ids
                )

                # Delete from vec_index
                await db.execute(
                    f"DELETE FROM {vec_index_table} WHERE id IN ({placeholders})", ids
                )

            await db.commit()
        finally:
            await self._release_connection(db)

    async def count(self) -> int:
        """Get total number of vectors in store.

        Returns:
            Total vector count

        Raises:
            RuntimeError: If store not initialized
        """
        if not self._initialized:
            await self.initialize()

        db = await self._acquire_connection()
        try:
            vectors_table = f"vectors_{self.collection_name}"
            cursor = await db.execute(f"SELECT COUNT(*) FROM {vectors_table}")
            row = await cursor.fetchone()
            return row[0] if row else 0
        finally:
            await self._release_connection(db)

    async def close(self) -> None:
        """
        Close the vector store and release pool resources for this database.

        This closes all pooled connections for the database path.
        Other store instances using the same database will also be affected.
        """
        await self.close_pool(self.db_path)

    async def clear(self) -> None:
        """Clear all vectors from the store.

        Warning: This deletes all data!
        """
        if not self._initialized:
            await self.initialize()

        db = await self._acquire_connection()
        try:
            vectors_table = f"vectors_{self.collection_name}"
            vec_index_table = f"vec_index_{self.collection_name}"

            await db.execute(f"DELETE FROM {vectors_table}")
            await db.execute(f"DELETE FROM {vec_index_table}")
            await db.commit()
        finally:
            await self._release_connection(db)
