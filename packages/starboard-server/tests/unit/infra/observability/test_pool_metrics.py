"""Tests for connection pool metrics via OpenTelemetry."""

from unittest.mock import MagicMock

from starboard_server.infra.observability.pool_metrics import (
    PoolMetricsCollector,
)


class TestPoolMetricsCollector:
    """Tests for PoolMetricsCollector."""

    def test_creates_otel_instruments(self):
        """Collector creates gauge and histogram instruments."""
        mock_pool = MagicMock()
        mock_pool.size = 10
        mock_pool.freesize = 5

        collector = PoolMetricsCollector(mock_pool, "database")

        assert collector.pool_name == "database"
        # Instruments should be created (not None)
        assert collector._size_gauge is not None
        assert collector._active_gauge is not None
        assert collector._wait_histogram is not None

    def test_record_acquisition_records_histogram(self):
        """record_acquisition records wait time to histogram."""
        mock_pool = MagicMock()
        collector = PoolMetricsCollector(mock_pool, "database")

        # Should not raise
        collector.record_acquisition(5.2)
        collector.record_acquisition(0.1)
        collector.record_acquisition(100.0)

    def test_pool_name_property(self):
        """pool_name returns the configured name."""
        mock_pool = MagicMock()
        collector = PoolMetricsCollector(mock_pool, "http")
        assert collector.pool_name == "http"

    def test_get_pool_size_with_size_attr(self):
        """Gets pool size from pool.size attribute."""
        mock_pool = MagicMock()
        mock_pool.size = 20
        collector = PoolMetricsCollector(mock_pool, "database")
        assert collector.get_pool_size() == 20

    def test_get_pool_size_with_maxsize_attr(self):
        """Gets pool size from pool.maxsize when size not available."""
        mock_pool = MagicMock(spec=[])
        mock_pool.maxsize = 15
        collector = PoolMetricsCollector(mock_pool, "http")
        assert collector.get_pool_size() == 15

    def test_get_pool_size_fallback(self):
        """Returns 0 when pool has no size attribute."""
        mock_pool = MagicMock(spec=[])
        collector = PoolMetricsCollector(mock_pool, "unknown")
        assert collector.get_pool_size() == 0

    def test_get_active_count_with_freesize(self):
        """Calculates active from size - freesize."""
        mock_pool = MagicMock()
        mock_pool.size = 20
        mock_pool.freesize = 15
        collector = PoolMetricsCollector(mock_pool, "database")
        assert collector.get_active_count() == 5

    def test_get_active_count_fallback(self):
        """Returns 0 when pool has no active count info."""
        mock_pool = MagicMock(spec=[])
        collector = PoolMetricsCollector(mock_pool, "unknown")
        assert collector.get_active_count() == 0

    def test_multiple_collectors_different_names(self):
        """Multiple collectors can coexist with different pool names."""
        pool1 = MagicMock()
        pool2 = MagicMock()

        c1 = PoolMetricsCollector(pool1, "database")
        c2 = PoolMetricsCollector(pool2, "http")

        assert c1.pool_name != c2.pool_name
