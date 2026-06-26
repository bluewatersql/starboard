# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for SemanticCache (mocked vector store)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from starboard_core.foundations.models import (
    VectorSearchResult,
)
from starboard_server.infra.cache import SemanticCache


class TestSemanticCacheInit:
    """Tests for SemanticCache initialization."""

    def test_init_with_valid_threshold(self):
        """Test initialization with valid similarity threshold."""
        mock_store = Mock()
        mock_embedding_fn = Mock(return_value=[0.1] * 1536)

        cache = SemanticCache(
            vector_store=mock_store,
            embedding_fn=mock_embedding_fn,
            ttl=300,
            similarity_threshold=0.95,
        )

        assert cache.similarity_threshold == 0.95
        assert cache.default_ttl == 300

    def test_init_with_invalid_threshold_too_low(self):
        """Test initialization fails with threshold < 0."""
        mock_store = Mock()
        mock_embedding_fn = Mock(return_value=[0.1] * 1536)

        with pytest.raises(ValueError, match="similarity_threshold must be between"):
            SemanticCache(
                vector_store=mock_store,
                embedding_fn=mock_embedding_fn,
                similarity_threshold=-0.1,
            )

    def test_init_with_invalid_threshold_too_high(self):
        """Test initialization fails with threshold > 1."""
        mock_store = Mock()
        mock_embedding_fn = Mock(return_value=[0.1] * 1536)

        with pytest.raises(ValueError, match="similarity_threshold must be between"):
            SemanticCache(
                vector_store=mock_store,
                embedding_fn=mock_embedding_fn,
                similarity_threshold=1.1,
            )


class TestSemanticCacheGet:
    """Tests for cache retrieval."""

    @pytest.fixture
    def mock_store(self):
        """Create mock vector store."""
        store = AsyncMock()
        return store

    @pytest.fixture
    def mock_embedding_fn(self):
        """Create mock embedding function."""
        return AsyncMock(return_value=[0.1] * 1536)

    @pytest.fixture
    def cache(self, mock_store, mock_embedding_fn):
        """Create cache instance."""
        return SemanticCache(
            vector_store=mock_store,
            embedding_fn=mock_embedding_fn,
            ttl=300,
            similarity_threshold=0.95,
        )

    async def test_cache_miss_no_results(self, cache, mock_store):
        """Test cache miss when no similar queries found."""
        mock_store.search.return_value = []

        result = await cache.get("test query")

        assert result is None
        assert cache._misses == 1
        assert cache._hits == 0

    async def test_cache_miss_below_threshold(self, cache, mock_store):
        """Test cache miss when similarity below threshold."""
        # Return result with score below threshold
        mock_store.search.return_value = [
            VectorSearchResult(
                id="cache_123",
                score=0.90,  # Below default 0.95
                metadata={
                    "query": "similar query",
                    "response": "cached response",
                    "created_at": datetime.now(UTC).isoformat(),
                    "ttl": 300,
                },
                content="similar query",
            )
        ]

        result = await cache.get("test query")

        assert result is None
        assert cache._misses == 1

    async def test_cache_hit_valid_entry(self, cache, mock_store):
        """Test cache hit with valid entry."""
        created_at = datetime.now(UTC)
        mock_store.search.return_value = [
            VectorSearchResult(
                id="cache_123",
                score=0.96,  # Above threshold
                metadata={
                    "query": "test query",
                    "response": "cached response",
                    "created_at": created_at.isoformat(),
                    "ttl": 300,
                },
                content="test query",
            )
        ]

        result = await cache.get("test query")

        assert result is not None
        assert result.id == "cache_123"
        assert result.response == "cached response"
        assert cache._hits == 1
        assert cache._misses == 0

    async def test_cache_miss_expired_entry(self, cache, mock_store):
        """Test cache miss when entry is expired."""
        # Entry created in the past beyond TTL
        created_at = datetime.now(UTC) - timedelta(seconds=400)
        mock_store.search.return_value = [
            VectorSearchResult(
                id="cache_123",
                score=0.96,
                metadata={
                    "query": "test query",
                    "response": "cached response",
                    "created_at": created_at.isoformat(),
                    "ttl": 300,  # TTL was 300 seconds, so expired
                },
                content="test query",
            )
        ]

        result = await cache.get("test query")

        assert result is None
        assert cache._misses == 1
        # Should have deleted expired entry
        mock_store.delete.assert_called_once_with(["cache_123"])

    async def test_cache_miss_invalid_metadata(self, cache, mock_store):
        """Test cache miss when metadata is invalid."""
        mock_store.search.return_value = [
            VectorSearchResult(
                id="cache_123",
                score=0.96,
                metadata={
                    # Missing required fields
                    "response": "cached response",
                },
                content="test query",
            )
        ]

        result = await cache.get("test query")

        assert result is None
        assert cache._misses == 1
        # Should have deleted invalid entry
        mock_store.delete.assert_called_once_with(["cache_123"])

    async def test_get_with_custom_threshold(self, cache, mock_store):
        """Test cache retrieval with custom similarity threshold."""
        mock_store.search.return_value = [
            VectorSearchResult(
                id="cache_123",
                score=0.90,  # Below default (0.95) but above custom (0.85)
                metadata={
                    "query": "test query",
                    "response": "cached response",
                    "created_at": datetime.now(UTC).isoformat(),
                    "ttl": 300,
                },
                content="test query",
            )
        ]

        result = await cache.get("test query", similarity_threshold=0.85)

        assert result is not None
        assert result.response == "cached response"
        assert cache._hits == 1


class TestSemanticCacheSet:
    """Tests for cache storage."""

    @pytest.fixture
    def mock_store(self):
        """Create mock vector store."""
        store = AsyncMock()
        return store

    @pytest.fixture
    def mock_embedding_fn(self):
        """Create mock embedding function."""
        return AsyncMock(return_value=[0.1] * 1536)

    @pytest.fixture
    def cache(self, mock_store, mock_embedding_fn):
        """Create cache instance."""
        return SemanticCache(
            vector_store=mock_store,
            embedding_fn=mock_embedding_fn,
            ttl=300,
            similarity_threshold=0.95,
        )

    async def test_set_basic(self, cache, mock_store):
        """Test basic cache storage."""
        await cache.set("test query", "test response")

        # Verify upsert was called with correct structure
        mock_store.upsert.assert_called_once()
        vectors = mock_store.upsert.call_args[0][0]
        assert len(vectors) == 1
        assert vectors[0].metadata["query"] == "test query"
        assert vectors[0].metadata["response"] == "test response"
        assert vectors[0].metadata["ttl"] == 300

    async def test_set_with_custom_ttl(self, cache, mock_store):
        """Test cache storage with custom TTL."""
        await cache.set("test query", "test response", ttl=600)

        vectors = mock_store.upsert.call_args[0][0]
        assert vectors[0].metadata["ttl"] == 600

    async def test_set_with_metadata(self, cache, mock_store):
        """Test cache storage with additional metadata."""
        await cache.set(
            "test query",
            "test response",
            metadata={"model": "gpt-4", "tokens": 100},
        )

        vectors = mock_store.upsert.call_args[0][0]
        assert vectors[0].metadata["metadata"] == {
            "model": "gpt-4",
            "tokens": 100,
        }


class TestSemanticCacheMetrics:
    """Tests for cache metrics."""

    @pytest.fixture
    def mock_store(self):
        """Create mock vector store."""
        return AsyncMock()

    @pytest.fixture
    def mock_embedding_fn(self):
        """Create mock embedding function."""
        return AsyncMock(return_value=[0.1] * 1536)

    @pytest.fixture
    def cache(self, mock_store, mock_embedding_fn):
        """Create cache instance."""
        return SemanticCache(
            vector_store=mock_store,
            embedding_fn=mock_embedding_fn,
            ttl=300,
            similarity_threshold=0.95,
        )

    async def test_metrics_initial_state(self, cache):
        """Test metrics in initial state."""
        metrics = cache.get_metrics()

        assert metrics["hits"] == 0
        assert metrics["misses"] == 0
        assert metrics["total_requests"] == 0
        assert metrics["hit_rate"] == 0.0
        assert metrics["similarity_threshold"] == 0.95
        assert metrics["default_ttl"] == 300

    async def test_metrics_after_operations(self, cache, mock_store):
        """Test metrics after cache operations."""
        # Setup for hit
        created_at = datetime.now(UTC)
        mock_store.search.return_value = [
            VectorSearchResult(
                id="cache_123",
                score=0.96,
                metadata={
                    "query": "query1",
                    "response": "response1",
                    "created_at": created_at.isoformat(),
                    "ttl": 300,
                },
                content="query1",
            )
        ]
        await cache.get("query1")  # Hit

        # Setup for miss
        mock_store.search.return_value = []
        await cache.get("query2")  # Miss
        await cache.get("query3")  # Miss

        metrics = cache.get_metrics()

        assert metrics["hits"] == 1
        assert metrics["misses"] == 2
        assert metrics["total_requests"] == 3
        assert metrics["hit_rate"] == pytest.approx(1 / 3)

    async def test_reset_metrics(self, cache, mock_store):
        """Test resetting metrics."""
        mock_store.search.return_value = []
        await cache.get("query")

        cache.reset_metrics()

        metrics = cache.get_metrics()
        assert metrics["hits"] == 0
        assert metrics["misses"] == 0


class TestSemanticCacheUtilities:
    """Tests for cache utility methods."""

    @pytest.fixture
    def mock_store(self):
        """Create mock vector store."""
        store = AsyncMock()
        store.count.return_value = 42
        return store

    @pytest.fixture
    def mock_embedding_fn(self):
        """Create mock embedding function."""
        return AsyncMock(return_value=[0.1] * 1536)

    @pytest.fixture
    def cache(self, mock_store, mock_embedding_fn):
        """Create cache instance."""
        return SemanticCache(
            vector_store=mock_store,
            embedding_fn=mock_embedding_fn,
        )

    async def test_count(self, cache, mock_store):
        """Test getting cache entry count."""
        count = await cache.count()

        assert count == 42
        mock_store.count.assert_called_once()

    async def test_invalidate_returns_zero(self, cache):
        """Test invalidate returns 0 (not yet implemented)."""
        count = await cache.invalidate(pattern="test")

        assert count == 0

    async def test_cleanup_expired_returns_zero(self, cache):
        """Test cleanup_expired returns 0 (lazy cleanup)."""
        count = await cache.cleanup_expired()

        assert count == 0

    def test_generate_cache_id_deterministic(self, cache):
        """Test cache ID generation is deterministic."""
        id1 = cache._generate_cache_id("test query")
        id2 = cache._generate_cache_id("test query")

        assert id1 == id2
        assert id1.startswith("cache_")

    def test_generate_cache_id_unique(self, cache):
        """Test different queries generate different IDs."""
        id1 = cache._generate_cache_id("query 1")
        id2 = cache._generate_cache_id("query 2")

        assert id1 != id2


class TestSemanticCacheAsyncEmbedding:
    """Tests for async embedding function support."""

    @pytest.fixture
    def mock_store(self):
        """Create mock vector store."""
        return AsyncMock()

    @pytest.fixture
    def async_embedding_fn(self):
        """Create async mock embedding function."""

        async def embed(text):
            return [0.1] * 1536

        return embed

    @pytest.fixture
    def cache(self, mock_store, async_embedding_fn):
        """Create cache with async embedding function."""
        return SemanticCache(
            vector_store=mock_store,
            embedding_fn=async_embedding_fn,
        )

    async def test_get_with_async_embedding(self, cache, mock_store):
        """Test cache retrieval with async embedding function."""
        mock_store.search.return_value = []

        result = await cache.get("test query")

        assert result is None
        # Verify search was called with embeddings
        mock_store.search.assert_called_once()

    async def test_set_with_async_embedding(self, cache, mock_store):
        """Test cache storage with async embedding function."""
        await cache.set("test query", "test response")

        # Verify upsert was called
        mock_store.upsert.assert_called_once()
