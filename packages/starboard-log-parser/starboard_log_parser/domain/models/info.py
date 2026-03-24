"""
SparkApplicationInfo domain model.

Contains basic information about a Spark application execution.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SparkApplicationInfo:
    """
    Immutable information about a Spark application execution.

    This model captures the essential metadata about a Spark application run,
    including timing, version, and infrastructure details.

    Args:
        timestamp_start_ms: Application start time in milliseconds since epoch
        timestamp_end_ms: Application end time in milliseconds since epoch
        runtime_sec: Total runtime in seconds (derived: (end - start) / 1000)
        name: Application name as specified by the user
        id: Unique application identifier (typically app-YYYYMMDD-HHMMSS-XXXX)
        spark_version: Spark version string (e.g., "3.5.0")
        emr_version_tag: EMR version if running on AWS EMR (e.g., "emr-6.15.0")
        cloud_platform: Cloud platform identifier (e.g., "emr", "databricks", "standalone")
        cloud_provider: Cloud provider (e.g., "aws", "azure", "gcp", "on-prem")
        cluster_id: Cluster identifier if running on a managed cluster

    Examples:
        >>> info = SparkApplicationInfo(
        ...     timestamp_start_ms=1700000000000,
        ...     timestamp_end_ms=1700001000000,
        ...     runtime_sec=1000.0,
        ...     name="MySparkApp",
        ...     id="app-20231114-101010-0001",
        ...     spark_version="3.5.0",
        ...     emr_version_tag="emr-6.15.0",
        ...     cloud_platform="emr",
        ...     cloud_provider="aws",
        ...     cluster_id="j-ABC123XYZ",
        ... )
        >>> info.runtime_sec
        1000.0
        >>> info.name
        'MySparkApp'
    """

    timestamp_start_ms: int
    timestamp_end_ms: int
    runtime_sec: float
    name: str
    id: str
    spark_version: str
    emr_version_tag: str
    cloud_platform: str
    cloud_provider: str
    cluster_id: str

    def __post_init__(self) -> None:
        """
        Validate field values after initialization.

        Raises:
            ValueError: If timestamps are invalid or runtime is negative
        """
        if self.timestamp_start_ms < 0:
            raise ValueError(
                f"timestamp_start_ms must be >= 0, got {self.timestamp_start_ms}"
            )
        if self.timestamp_end_ms < 0:
            raise ValueError(
                f"timestamp_end_ms must be >= 0, got {self.timestamp_end_ms}"
            )
        if self.timestamp_end_ms < self.timestamp_start_ms:
            raise ValueError(
                f"timestamp_end_ms ({self.timestamp_end_ms}) must be >= "
                f"timestamp_start_ms ({self.timestamp_start_ms})"
            )
        if self.runtime_sec < 0:
            raise ValueError(f"runtime_sec must be >= 0, got {self.runtime_sec}")
