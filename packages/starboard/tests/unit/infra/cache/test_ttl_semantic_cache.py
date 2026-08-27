# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the TTL-only exact-key semantic cache (Phase 2 C4, D-2.9).

The default semantic cache carries no vector store, no embeddings, and no
sqlite-vec dependency. It matches on the exact query key and honours a
per-entry TTL. The similarity-based ``SemanticCache`` remains available behind
``vector_backend`` / ``starboard[vectorsearch]``.
"""

from __future__ import annotations

import sys

import pytest
from starboard.infra.cache import TTLSemanticCache


class TestTTLSemanticCacheBasics:
    @pytest.mark.asyncio
    async def test_exact_key_hit(self) -> None:
        cache = TTLSemanticCache(ttl=300)
        await cache.set("show top 10 jobs", {"sql": "SELECT 1"})
        entry = await cache.get("show top 10 jobs")
        assert entry is not None
        assert entry.response == {"sql": "SELECT 1"}
        assert entry.query == "show top 10 jobs"

    @pytest.mark.asyncio
    async def test_different_key_misses(self) -> None:
        cache = TTLSemanticCache(ttl=300)
        await cache.set("show top 10 jobs", {"sql": "SELECT 1"})
        # A semantically similar but not identical query must MISS: there is
        # no similarity path in the TTL-only default.
        assert await cache.get("show me the top ten jobs") is None

    @pytest.mark.asyncio
    async def test_miss_on_empty_cache(self) -> None:
        cache = TTLSemanticCache(ttl=300)
        assert await cache.get("anything") is None

    @pytest.mark.asyncio
    async def test_similarity_threshold_arg_is_ignored(self) -> None:
        # The threshold kwarg is accepted for API compatibility with the
        # similarity-based cache, but never triggers a fuzzy match.
        cache = TTLSemanticCache(ttl=300)
        await cache.set("q1", {"a": 1})
        assert await cache.get("q1", similarity_threshold=0.1) is not None
        assert await cache.get("q2", similarity_threshold=0.1) is None


class TestTTLExpiry:
    @pytest.mark.asyncio
    async def test_expired_entry_is_a_miss(self) -> None:
        cache = TTLSemanticCache(ttl=300)
        # Store with an immediately-expired TTL.
        await cache.set("q", {"a": 1}, ttl=0)
        # ttl=0 means age (>0) always exceeds ttl → expired.
        assert await cache.get("q") is None

    @pytest.mark.asyncio
    async def test_non_expired_entry_hits(self) -> None:
        cache = TTLSemanticCache(ttl=300)
        await cache.set("q", {"a": 1}, ttl=3600)
        assert await cache.get("q") is not None

    @pytest.mark.asyncio
    async def test_cleanup_expired_removes_expired(self) -> None:
        cache = TTLSemanticCache(ttl=300)
        await cache.set("fresh", {"a": 1}, ttl=3600)
        await cache.set("stale", {"a": 2}, ttl=0)
        removed = await cache.cleanup_expired()
        assert removed == 1
        assert await cache.count() == 1


class TestTTLMetricsAndInvalidation:
    @pytest.mark.asyncio
    async def test_metrics_track_hits_and_misses(self) -> None:
        cache = TTLSemanticCache(ttl=300)
        await cache.set("q", {"a": 1})
        await cache.get("q")  # hit
        await cache.get("missing")  # miss
        metrics = cache.get_metrics()
        assert metrics["hits"] == 1
        assert metrics["misses"] == 1
        assert metrics["hit_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_invalidate_all(self) -> None:
        cache = TTLSemanticCache(ttl=300)
        await cache.set("a", 1)
        await cache.set("b", 2)
        count = await cache.invalidate()
        assert count == 2
        assert await cache.count() == 0

    @pytest.mark.asyncio
    async def test_clear(self) -> None:
        cache = TTLSemanticCache(ttl=300)
        await cache.set("a", 1)
        await cache.clear()
        assert await cache.count() == 0

    @pytest.mark.asyncio
    async def test_close_is_noop(self) -> None:
        cache = TTLSemanticCache(ttl=300)
        await cache.close()  # must not raise


class TestTTLCacheHasNoVectorDependency:
    @pytest.mark.asyncio
    async def test_no_sqlite_vec_import(self) -> None:
        # Constructing + using the TTL cache must not import sqlite_vec.
        sys.modules.pop("sqlite_vec", None)
        cache = TTLSemanticCache(ttl=300)
        await cache.set("q", {"a": 1})
        await cache.get("q")
        assert "sqlite_vec" not in sys.modules
