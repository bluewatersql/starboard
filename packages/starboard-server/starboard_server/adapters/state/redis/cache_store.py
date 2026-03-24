"""Redis cache store implementation."""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as redis


class RedisCacheStore:
    """

    Redis-backed cache store with connection pooling.

    Features:
    - Async operations via redis.asyncio
    - JSON serialization for complex values
    - TTL support for automatic expiration
    - Batch operations (MGET, MSET) for performance
    - Connection pooling built into client
    """

    def __init__(self, redis_url: str):
        """
        Initialize Redis cache store.

        Args:
            redis_url: Redis connection URL (redis://host:port/db)

        Example:
            redis://localhost:6379/0
            redis://:password@localhost:6379/0
        """
        self._redis_url = redis_url
        self._client: redis.Redis | None = None

    @property
    def client(self) -> redis.Redis:
        """Get the Redis client, raising if not connected."""
        if self._client is None:
            raise RuntimeError("Redis not connected. Call connect() first.")
        return self._client

    async def connect(self) -> None:
        """
        Initialize Redis client with connection pool.

        Raises:
            ConnectionError: If unable to connect to Redis
        """
        self._client = await redis.from_url(
            self._redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )

        # Test connection
        try:
            await self._client.ping()  # type: ignore[misc]
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Redis: {e}") from e

    async def close(self) -> None:
        """Close Redis connection and cleanup resources."""
        if self._client:
            await self._client.close()

    async def get(self, key: str, reset_ttl: bool = False) -> Any | None:
        """
        Retrieve cached value.

        Args:
            key: Cache key
            reset_ttl: Unused (for protocol compatibility with InMemoryCacheStore).
                      Redis doesn't support TTL reset-on-read without additional logic.

        Returns:
            Cached value if present, None otherwise
        """
        # Note: reset_ttl is accepted for protocol compatibility but not implemented
        # in Redis. Implementing would require storing original TTL and using EXPIRE.
        _ = reset_ttl  # Explicitly unused
        value = await self.client.get(key)
        if value is None:
            return None

        try:
            return json.loads(value)
        except json.JSONDecodeError:
            # If not JSON, return as string
            return value

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
    ) -> None:
        """
        Store value in cache with optional TTL.

        Args:
            key: Cache key
            value: Value to cache (will be JSON serialized)
            ttl: Time-to-live in seconds (None = no expiration)
        """
        serialized = json.dumps(value)

        if ttl is not None:
            await self.client.setex(key, ttl, serialized)
        else:
            await self.client.set(key, serialized)

    async def delete(self, key: str) -> bool:
        """
        Remove value from cache.

        Args:
            key: Cache key

        Returns:
            True if key existed and was deleted, False otherwise
        """
        result = await self.client.delete(key)
        return result > 0

    async def exists(self, key: str) -> bool:
        """
        Check if key exists in cache.

        Args:
            key: Cache key

        Returns:
            True if key exists, False otherwise
        """
        result = await self.client.exists(key)
        return result > 0

    async def clear(self) -> None:
        """
        Clear all cached values (use with caution!).

        Warning:
            This will flush the entire Redis database.
            Use only in testing or with dedicated Redis instances.
        """
        await self.client.flushdb()

    async def get_many(self, keys: list[str]) -> dict[str, Any]:
        """
        Batch get multiple keys using MGET.

        Args:
            keys: List of cache keys

        Returns:
            Dictionary of key-value pairs (only for existing keys)
        """
        if not keys:
            return {}

        values = await self.client.mget(keys)
        result = {}

        for key, value in zip(keys, values):
            if value is not None:
                try:
                    result[key] = json.loads(value)
                except json.JSONDecodeError:
                    result[key] = value

        return result

    async def set_many(
        self,
        items: dict[str, Any],
        ttl: int | None = None,
    ) -> None:
        """
        Batch set multiple keys using pipeline.

        Args:
            items: Dictionary of key-value pairs
            ttl: Time-to-live for all keys (None = no expiration)
        """
        if not items:
            return

        async with self.client.pipeline() as pipe:
            for key, value in items.items():
                serialized = json.dumps(value)
                if ttl is not None:
                    pipe.setex(key, ttl, serialized)
                else:
                    pipe.set(key, serialized)
            await pipe.execute()

    async def increment(self, key: str, amount: int = 1) -> int:
        """
        Increment a counter.

        Args:
            key: Cache key
            amount: Amount to increment by

        Returns:
            New value after increment
        """
        return await self.client.incrby(key, amount)

    async def decrement(self, key: str, amount: int = 1) -> int:
        """
        Decrement a counter.

        Args:
            key: Cache key
            amount: Amount to decrement by

        Returns:
            New value after decrement
        """
        return await self.client.decrby(key, amount)
