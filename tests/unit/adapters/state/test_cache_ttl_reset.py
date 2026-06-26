# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for cache TTL reset-on-hit functionality.

Tests that:
- By default, cache entries expire at their original TTL (no implicit reset)
- TTL reset is opt-in via reset_ttl=True parameter
- Frequently accessed data can be kept warm when explicitly requested
"""

import asyncio

import pytest
from starboard_server.adapters.state.inmemory.cache_store import (
    CacheEntry,
    InMemoryCacheStore,
)


class TestCacheEntryTTL:
    """Tests for CacheEntry TTL tracking."""

    def test_cache_entry_stores_ttl(self):
        """CacheEntry should store original TTL for reset."""
        entry = CacheEntry(value="test", expires_at=100.0, ttl=60)
        assert entry.ttl == 60

    def test_cache_entry_ttl_optional(self):
        """CacheEntry TTL should be optional for backwards compatibility."""
        entry = CacheEntry(value="test", expires_at=100.0)
        assert entry.ttl is None


class TestCacheStoreResetOnHit:
    """Tests for InMemoryCacheStore TTL reset on hit."""

    @pytest.mark.asyncio
    async def test_ttl_does_not_reset_by_default(self):
        """Cache TTL should NOT reset by default (opt-in behavior).

        This ensures predictable cache expiration. Developers set a TTL
        expecting data to expire at that time, not silently extend forever.
        """
        cache = InMemoryCacheStore()

        # Set with 1 second TTL
        await cache.set("key", "value", ttl=1)

        # Access without explicit reset_ttl (uses default False)
        await asyncio.sleep(0.5)
        result = await cache.get("key")  # Uses default reset_ttl=False
        assert result == "value"

        # Wait remaining TTL plus buffer
        await asyncio.sleep(0.7)

        # Entry should be expired (TTL was NOT reset)
        result = await cache.get("key")
        assert result is None

    @pytest.mark.asyncio
    async def test_ttl_resets_when_explicitly_enabled(self):
        """Cache TTL should reset when reset_ttl=True is explicitly passed."""
        cache = InMemoryCacheStore()

        # Set with 2 second TTL
        await cache.set("key", "value", ttl=2)

        # Wait 1 second
        await asyncio.sleep(1.0)

        # Explicitly request TTL reset
        result = await cache.get("key", reset_ttl=True)
        assert result == "value"

        # Wait another 1.5 seconds (total 2.5s since last access)
        # Entry should still be valid because TTL was explicitly reset
        await asyncio.sleep(1.5)
        result = await cache.get("key", reset_ttl=True)
        assert result == "value"

    @pytest.mark.asyncio
    async def test_ttl_no_reset_when_explicitly_disabled(self):
        """Cache TTL should not reset when reset_ttl=False."""
        cache = InMemoryCacheStore()

        # Set with 1 second TTL
        await cache.set("key", "value", ttl=1)

        # Access with explicit reset_ttl=False
        await asyncio.sleep(0.5)
        result = await cache.get("key", reset_ttl=False)
        assert result == "value"

        # Wait remaining TTL plus buffer
        await asyncio.sleep(0.7)

        # Entry should be expired (TTL was not reset)
        result = await cache.get("key")
        assert result is None

    @pytest.mark.asyncio
    async def test_entry_expires_without_access(self):
        """Cache entry should expire normally if not accessed."""
        cache = InMemoryCacheStore()

        # Set with 1 second TTL
        await cache.set("key", "value", ttl=1)

        # Wait for expiration
        await asyncio.sleep(1.1)

        # Entry should be expired
        result = await cache.get("key")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_expiration_entry_not_affected(self):
        """Entries without expiration should not be affected by reset logic."""
        cache = InMemoryCacheStore()

        # Set without TTL (no expiration)
        await cache.set("key", "value", ttl=None)

        result = await cache.get("key")
        assert result == "value"

        # Access again - should still work
        result = await cache.get("key")
        assert result == "value"

    @pytest.mark.asyncio
    async def test_multiple_accesses_extend_lifetime_when_enabled(self):
        """Multiple accesses with reset_ttl=True should keep extending entry lifetime."""
        cache = InMemoryCacheStore()

        # Set with 1 second TTL
        await cache.set("key", "value", ttl=1)

        # Access every 0.7 seconds, 5 times (total 3.5s) with explicit reset_ttl=True
        for _ in range(5):
            await asyncio.sleep(0.7)
            result = await cache.get("key", reset_ttl=True)
            assert result == "value", "Entry should still be valid after TTL reset"

        # Final check - entry is still alive after 3.5s (original TTL was 1s)
        result = await cache.get("key", reset_ttl=True)
        assert result == "value"

    @pytest.mark.asyncio
    async def test_multiple_accesses_do_not_extend_by_default(self):
        """Multiple accesses without reset_ttl=True should NOT extend lifetime."""
        cache = InMemoryCacheStore()

        # Set with 2 second TTL
        await cache.set("key", "value", ttl=2)

        # Access multiple times but TTL should not reset (default behavior)
        for _ in range(3):
            await asyncio.sleep(0.5)
            result = await cache.get("key")  # Uses default reset_ttl=False
            assert result == "value"

        # After 2.5 seconds (3 * 0.5s + overhead), entry should be expired
        await asyncio.sleep(0.6)
        result = await cache.get("key")
        assert result is None, "Entry should expire at original TTL"


class TestCacheStoreTTLTracking:
    """Tests for TTL tracking in set operations."""

    @pytest.mark.asyncio
    async def test_set_stores_ttl_for_reset(self):
        """set() should store TTL in CacheEntry for later reset."""
        cache = InMemoryCacheStore()

        await cache.set("key", "value", ttl=300)

        # Access internal cache to verify TTL is stored
        entry = cache._cache.get("key")
        assert entry is not None
        assert entry.ttl == 300

    @pytest.mark.asyncio
    async def test_set_without_ttl_has_none(self):
        """set() without TTL should have None TTL."""
        cache = InMemoryCacheStore()

        await cache.set("key", "value")

        entry = cache._cache.get("key")
        assert entry is not None
        assert entry.ttl is None
        assert entry.expires_at is None
