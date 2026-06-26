# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Integration tests for Redis cache store (requires running Redis)."""

import asyncio
import os

import pytest
from starboard_server.adapters.state.redis import RedisCacheStore


@pytest.fixture(scope="module")
async def redis_store():
    """
    Create Redis store for testing.

    Requires:
        TEST_REDIS_URL environment variable with Redis connection string
    """
    redis_url = os.environ.get("TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("TEST_REDIS_URL not set")

    store = RedisCacheStore(redis_url)
    await store.connect()
    yield store
    await store.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_connection(redis_store):
    """Should connect to Redis successfully."""
    # If we got here, connection succeeded
    assert redis_store is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_set_and_get(redis_store):
    """Should set and get value."""
    await redis_store.set("test-key-1", "test-value-1")
    result = await redis_store.get("test-key-1")
    assert result == "test-value-1"

    # Cleanup
    await redis_store.delete("test-key-1")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_set_with_ttl(redis_store):
    """Should expire value after TTL."""
    await redis_store.set("test-key-ttl", "value", ttl=1)  # 1 second TTL

    # Immediate get should work
    result = await redis_store.get("test-key-ttl")
    assert result == "value"

    # Wait for expiration
    await asyncio.sleep(1.5)

    # Should be expired
    result = await redis_store.get("test-key-ttl")
    assert result is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_key(redis_store):
    """Should delete existing key."""
    await redis_store.set("test-key-delete", "value")
    deleted = await redis_store.delete("test-key-delete")
    assert deleted is True

    result = await redis_store.get("test-key-delete")
    assert result is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_nonexistent_key(redis_store):
    """Should return False for non-existent key."""
    deleted = await redis_store.delete("nonexistent-key")
    assert deleted is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_exists(redis_store):
    """Should check if key exists."""
    await redis_store.set("test-key-exists", "value")
    assert await redis_store.exists("test-key-exists") is True
    assert await redis_store.exists("nonexistent") is False

    # Cleanup
    await redis_store.delete("test-key-exists")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_complex_values(redis_store):
    """Should store complex JSON values."""
    complex_value = {"nested": {"key": "value"}, "list": [1, 2, 3]}
    await redis_store.set("test-key-complex", complex_value)

    result = await redis_store.get("test-key-complex")
    assert result == complex_value

    # Cleanup
    await redis_store.delete("test-key-complex")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_batch_get(redis_store):
    """Should get multiple keys in batch."""
    await redis_store.set("batch-1", "value-1")
    await redis_store.set("batch-2", "value-2")
    await redis_store.set("batch-3", "value-3")

    result = await redis_store.get_many(
        ["batch-1", "batch-2", "batch-3", "nonexistent"]
    )
    assert result == {"batch-1": "value-1", "batch-2": "value-2", "batch-3": "value-3"}

    # Cleanup
    await redis_store.delete("batch-1")
    await redis_store.delete("batch-2")
    await redis_store.delete("batch-3")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_batch_set(redis_store):
    """Should set multiple keys in batch."""
    items = {"batch-set-1": "value-1", "batch-set-2": "value-2"}
    await redis_store.set_many(items, ttl=300)

    result1 = await redis_store.get("batch-set-1")
    result2 = await redis_store.get("batch-set-2")

    assert result1 == "value-1"
    assert result2 == "value-2"

    # Cleanup
    await redis_store.delete("batch-set-1")
    await redis_store.delete("batch-set-2")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_increment_counter(redis_store):
    """Should increment counter."""
    # Set initial value
    await redis_store.set("counter", 0)

    # Increment
    result = await redis_store.increment("counter", 5)
    assert result == 5

    result = await redis_store.increment("counter", 3)
    assert result == 8

    # Cleanup
    await redis_store.delete("counter")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_decrement_counter(redis_store):
    """Should decrement counter."""
    # Set initial value
    await redis_store.set("counter-dec", 10)

    # Decrement
    result = await redis_store.decrement("counter-dec", 3)
    assert result == 7

    result = await redis_store.decrement("counter-dec", 2)
    assert result == 5

    # Cleanup
    await redis_store.delete("counter-dec")
