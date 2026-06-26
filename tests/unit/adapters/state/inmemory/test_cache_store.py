# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for in-memory cache store."""

import asyncio

import pytest
from starboard_server.adapters.state.inmemory import InMemoryCacheStore


@pytest.fixture
def cache():
    """Create a fresh in-memory cache for each test."""
    return InMemoryCacheStore(max_size=10)


@pytest.mark.asyncio
async def test_get_nonexistent_key(cache):
    """Should return None for non-existent key."""
    result = await cache.get("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_set_and_get(cache):
    """Should set and get value."""
    await cache.set("key1", "value1")
    result = await cache.get("key1")
    assert result == "value1"


@pytest.mark.asyncio
async def test_set_with_ttl(cache):
    """Should expire value after TTL."""
    await cache.set("key1", "value1", ttl=0.1)  # 100ms TTL

    # Immediate get should work
    result = await cache.get("key1")
    assert result == "value1"

    # Wait for expiration
    await asyncio.sleep(0.15)

    # Should be expired
    result = await cache.get("key1")
    assert result is None


@pytest.mark.asyncio
async def test_set_without_ttl(cache):
    """Should not expire value without TTL."""
    await cache.set("key1", "value1")

    # Wait a bit
    await asyncio.sleep(0.1)

    # Should still be there
    result = await cache.get("key1")
    assert result == "value1"


@pytest.mark.asyncio
async def test_delete_existing_key(cache):
    """Should delete existing key."""
    await cache.set("key1", "value1")
    deleted = await cache.delete("key1")
    assert deleted is True

    result = await cache.get("key1")
    assert result is None


@pytest.mark.asyncio
async def test_delete_nonexistent_key(cache):
    """Should return False for non-existent key."""
    deleted = await cache.delete("nonexistent")
    assert deleted is False


@pytest.mark.asyncio
async def test_exists_key(cache):
    """Should check if key exists."""
    await cache.set("key1", "value1")
    assert await cache.exists("key1") is True
    assert await cache.exists("nonexistent") is False


@pytest.mark.asyncio
async def test_exists_expired_key(cache):
    """Should return False for expired key."""
    await cache.set("key1", "value1", ttl=0.1)
    await asyncio.sleep(0.15)
    assert await cache.exists("key1") is False


@pytest.mark.asyncio
async def test_clear_cache(cache):
    """Should clear all entries."""
    await cache.set("key1", "value1")
    await cache.set("key2", "value2")
    await cache.clear()

    assert await cache.get("key1") is None
    assert await cache.get("key2") is None


@pytest.mark.asyncio
async def test_max_size_eviction(cache):
    """Should evict oldest entry when max size reached."""
    # Fill cache to max size
    for i in range(10):
        await cache.set(f"key{i}", f"value{i}")

    # Add one more (should evict first entry)
    await cache.set("key10", "value10")

    # First key should be evicted
    result = await cache.get("key0")
    assert result is None

    # Newer keys should still exist
    result = await cache.get("key9")
    assert result == "value9"


@pytest.mark.asyncio
async def test_update_existing_key(cache):
    """Should update value for existing key."""
    await cache.set("key1", "value1")
    await cache.set("key1", "value2")

    result = await cache.get("key1")
    assert result == "value2"


@pytest.mark.asyncio
async def test_store_complex_values(cache):
    """Should store complex values like dicts and lists."""
    complex_value = {"nested": {"key": "value"}, "list": [1, 2, 3]}
    await cache.set("complex", complex_value)

    result = await cache.get("complex")
    assert result == complex_value
