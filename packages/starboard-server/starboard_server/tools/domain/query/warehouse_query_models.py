"""Domain models for warehouse query history data structures.

These dataclasses provide type-safe representations of warehouse query metrics,
performance statistics, and aggregated summaries.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PerformanceBytes:
    """Aggregated byte metrics.

    Attributes:
        read_total: Total bytes read
        remote_read_total: Total remote bytes read
        cache_read_total: Total cache bytes read
        spill_total: Total bytes spilled to disk
        network_sent_total: Total bytes sent over network
        write_remote_total: Total bytes written remotely
    """

    read_total: int = 0
    remote_read_total: int = 0
    cache_read_total: int = 0
    spill_total: int = 0
    network_sent_total: int = 0
    write_remote_total: int = 0

    def to_dict(self) -> dict[str, int]:
        """Convert to dictionary."""
        return {
            "read_total": self.read_total,
            "remote_read_total": self.remote_read_total,
            "cache_read_total": self.cache_read_total,
            "spill_total": self.spill_total,
            "network_sent_total": self.network_sent_total,
            "write_remote_total": self.write_remote_total,
        }


@dataclass
class PerformanceRows:
    """Aggregated row metrics.

    Attributes:
        read_total: Total rows read
        produced_total: Total rows produced
    """

    read_total: int = 0
    produced_total: int = 0

    def to_dict(self) -> dict[str, int]:
        """Convert to dictionary."""
        return {
            "read_total": self.read_total,
            "produced_total": self.produced_total,
        }


@dataclass
class PerformanceScan:
    """Aggregated scan metrics.

    Attributes:
        files_read_total: Total files read
        partitions_read_total: Total partitions read
    """

    files_read_total: int = 0
    partitions_read_total: int = 0

    def to_dict(self) -> dict[str, int]:
        """Convert to dictionary."""
        return {
            "files_read_total": self.files_read_total,
            "partitions_read_total": self.partitions_read_total,
        }


@dataclass
class CacheMetrics:
    """Cache performance metrics.

    Attributes:
        hit_rate: Cache hit rate (0.0-1.0)
        hits: Number of cache hits
    """

    hit_rate: float = 0.0
    hits: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "hit_rate": self.hit_rate,
            "hits": self.hits,
        }


@dataclass
class PhotonMetrics:
    """Photon usage metrics.

    Attributes:
        observations: Number of queries with photon metrics
        total_time_ms: Total photon time in milliseconds
        usage_share_of_total_time: Photon share of total time (0.0-1.0)
    """

    observations: int = 0
    total_time_ms: float = 0.0
    usage_share_of_total_time: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "observations": self.observations,
            "total_time_ms": self.total_time_ms,
            "usage_share_of_total_time": self.usage_share_of_total_time,
        }


@dataclass
class DurationStats:
    """Duration statistics.

    Attributes:
        avg: Average duration
        p50: 50th percentile (median)
        p95: 95th percentile
        p99: 99th percentile
        max: Maximum duration
    """

    avg: float = 0.0
    p50: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    max: float = 0.0

    def to_dict(self) -> dict[str, float]:
        """Convert to dictionary."""
        return {
            "avg": self.avg,
            "p50": self.p50,
            "p95": self.p95,
            "p99": self.p99,
            "max": self.max,
        }


@dataclass
class TimesAverage:
    """Average time metrics in milliseconds.

    Attributes:
        compilation: Average compilation time
        execution: Average execution time
        task_total: Average task total time
    """

    compilation: float = 0.0
    execution: float = 0.0
    task_total: float = 0.0

    def to_dict(self) -> dict[str, float]:
        """Convert to dictionary."""
        return {
            "compilation": self.compilation,
            "execution": self.execution,
            "task_total": self.task_total,
        }


@dataclass
class StatementTypeStats:
    """Statistics for a statement type.

    Attributes:
        count: Number of queries
        avg_duration_ms: Average duration in milliseconds
    """

    count: int = 0
    avg_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "count": self.count,
            "avg_duration_ms": self.avg_duration_ms,
        }


@dataclass
class WarehouseConfig:
    """Warehouse configuration metadata.

    Attributes:
        warehouse_id: Warehouse identifier
        dbsql_versions: List of DBSQL versions observed
        channels: List of channels observed
        client_app_mix: Count of queries per client application
    """

    warehouse_id: str
    dbsql_versions: list[str] = field(default_factory=list)
    channels: list[str] = field(default_factory=list)
    client_app_mix: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "warehouse_id": self.warehouse_id,
            "dbsql_versions": self.dbsql_versions,
            "channels": self.channels,
            "client_app_mix": self.client_app_mix,
        }


@dataclass
class WarehousePerformance:
    """Complete performance metrics for a warehouse.

    Attributes:
        duration_ms: Duration statistics
        times_ms_avg: Average time breakdown
        photon: Photon usage metrics
        bytes: Byte metrics
        rows: Row metrics
        scan: Scan metrics
        cache: Cache metrics
        statement_type_mix: Statistics by statement type
    """

    duration_ms: DurationStats
    times_ms_avg: TimesAverage
    photon: PhotonMetrics
    bytes: PerformanceBytes
    rows: PerformanceRows
    scan: PerformanceScan
    cache: CacheMetrics
    statement_type_mix: dict[str, StatementTypeStats]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "duration_ms": self.duration_ms.to_dict(),
            "times_ms_avg": self.times_ms_avg.to_dict(),
            "photon": self.photon.to_dict(),
            "bytes": self.bytes.to_dict(),
            "rows": self.rows.to_dict(),
            "scan": self.scan.to_dict(),
            "cache": self.cache.to_dict(),
            "statement_type_mix": {
                k: v.to_dict() for k, v in self.statement_type_mix.items()
            },
        }


@dataclass
class WarehouseSummary:
    """Complete summary for a warehouse.

    Attributes:
        counts: Query and user counts
        config: Warehouse configuration
        performance: Performance metrics
    """

    counts: dict[str, int]
    config: WarehouseConfig
    performance: WarehousePerformance

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "counts": self.counts,
            "config": self.config.to_dict(),
            "performance": self.performance.to_dict(),
        }
