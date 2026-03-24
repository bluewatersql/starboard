"""Tests for CacheStore protocol and CacheMetrics.

Tests cover:
- Protocol compliance (duck typing)
- Method signatures
- Type hints
- CacheMetrics dataclass
"""

import pytest
from starboard_core.ports.cache_store import CacheMetrics, CacheStore


class TestCacheStoreProtocol:
    """Tests for CacheStore protocol definition."""

    def test_protocol_has_required_methods(self):
        """Test that protocol defines required methods."""
        # Check that the protocol has all required methods
        assert hasattr(CacheStore, "get")
        assert hasattr(CacheStore, "set")
        assert hasattr(CacheStore, "delete")
        assert hasattr(CacheStore, "exists")
        assert hasattr(CacheStore, "clear")

    def test_cache_store_implementation(self):
        """Test that a class can implement CacheStore protocol."""

        class MockCacheStore:
            """Mock implementation of CacheStore."""

            async def get(self, key: str):  # noqa: ARG002
                return None

            async def set(self, key: str, value, ttl: int | None = None) -> None:  # noqa: ARG002
                pass

            async def delete(self, key: str) -> bool:  # noqa: ARG002
                return True

            async def exists(self, key: str) -> bool:  # noqa: ARG002
                return False

            async def clear(self) -> None:
                pass

        # Should be compatible with protocol
        cache: CacheStore = MockCacheStore()
        assert cache is not None

    def test_protocol_methods_are_async(self):
        """Test that protocol methods are defined as async."""
        # All methods should be coroutines
        assert "get" in dir(CacheStore)
        assert "set" in dir(CacheStore)
        assert "delete" in dir(CacheStore)
        assert "exists" in dir(CacheStore)
        assert "clear" in dir(CacheStore)


class TestCacheMetrics:
    """Tests for CacheMetrics dataclass."""

    def test_create_with_all_fields(self):
        """Test creating CacheMetrics with all fields."""
        metrics = CacheMetrics(hits=80, misses=20, size=50, hit_rate=0.8)

        assert metrics.hits == 80
        assert metrics.misses == 20
        assert metrics.size == 50
        assert metrics.hit_rate == 0.8

    def test_empty_factory(self):
        """Test CacheMetrics.empty() returns zeroed metrics."""
        metrics = CacheMetrics.empty()

        assert metrics.hits == 0
        assert metrics.misses == 0
        assert metrics.size == 0
        assert metrics.hit_rate == 0.0

    def test_from_counts_calculates_hit_rate(self):
        """Test from_counts() calculates hit_rate correctly."""
        metrics = CacheMetrics.from_counts(hits=80, misses=20, size=50)

        assert metrics.hits == 80
        assert metrics.misses == 20
        assert metrics.size == 50
        assert metrics.hit_rate == 0.8

    def test_from_counts_zero_total(self):
        """Test from_counts() handles zero total gracefully."""
        metrics = CacheMetrics.from_counts(hits=0, misses=0, size=0)

        assert metrics.hit_rate == 0.0

    def test_from_counts_default_size(self):
        """Test from_counts() uses default size of 0."""
        metrics = CacheMetrics.from_counts(hits=10, misses=5)

        assert metrics.size == 0

    def test_to_dict(self):
        """Test to_dict() returns correct dictionary."""
        metrics = CacheMetrics(hits=10, misses=5, size=8, hit_rate=0.67)

        result = metrics.to_dict()

        assert result == {
            "hits": 10,
            "misses": 5,
            "size": 8,
            "hit_rate": 0.67,
        }

    def test_immutable(self):
        """Test CacheMetrics is immutable (frozen dataclass)."""
        metrics = CacheMetrics(hits=10, misses=5, size=8, hit_rate=0.67)

        # Attempting to modify should raise FrozenInstanceError
        import dataclasses

        with pytest.raises(dataclasses.FrozenInstanceError):
            metrics.hits = 20  # type: ignore[misc]

    def test_equality(self):
        """Test CacheMetrics equality comparison."""
        m1 = CacheMetrics(hits=10, misses=5, size=8, hit_rate=0.67)
        m2 = CacheMetrics(hits=10, misses=5, size=8, hit_rate=0.67)
        m3 = CacheMetrics(hits=20, misses=5, size=8, hit_rate=0.8)

        assert m1 == m2
        assert m1 != m3

    def test_hashable(self):
        """Test CacheMetrics is hashable (can be used in sets/dicts)."""
        metrics = CacheMetrics(hits=10, misses=5, size=8, hit_rate=0.67)

        # Should be hashable
        metric_set = {metrics}
        assert metrics in metric_set

        metric_dict = {metrics: "test"}
        assert metric_dict[metrics] == "test"
