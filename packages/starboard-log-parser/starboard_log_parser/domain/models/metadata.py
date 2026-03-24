"""
SparkApplicationMetadata domain model.

Contains metadata about a Spark application including application info and configuration.
"""

from dataclasses import dataclass
from typing import Any

from starboard_log_parser.domain.models.info import SparkApplicationInfo


@dataclass(frozen=True)
class SparkApplicationMetadata:
    """
    Immutable metadata for a Spark application.

    Aggregates application information with Spark configuration parameters
    and flags indicating what data types are available.

    Args:
        application_info: Basic information about the application execution
        spark_params: Spark configuration parameters (spark.* settings)
        exists_sql: Whether SQL execution data is available
        exists_executors: Whether executor data is available

    Examples:
        >>> info = SparkApplicationInfo(
        ...     timestamp_start_ms=1700000000000,
        ...     timestamp_end_ms=1700001000000,
        ...     runtime_sec=1000.0,
        ...     name="MyApp",
        ...     id="app-123",
        ...     spark_version="3.5.0",
        ...     emr_version_tag="",
        ...     cloud_platform="standalone",
        ...     cloud_provider="on-prem",
        ...     cluster_id="",
        ... )
        >>> metadata = SparkApplicationMetadata(
        ...     application_info=info,
        ...     spark_params={
        ...         "spark.executor.memory": "4g",
        ...         "spark.executor.cores": 2,
        ...         "spark.sql.adaptive.enabled": True,
        ...     },
        ...     exists_sql=True,
        ...     exists_executors=True,
        ... )
        >>> metadata.exists_sql
        True
        >>> metadata.spark_params["spark.executor.cores"]
        2
    """

    application_info: SparkApplicationInfo
    spark_params: dict[str, str | int | float | bool | dict[str, Any]]
    exists_sql: bool
    exists_executors: bool

    def __post_init__(self) -> None:
        """
        Validate field values after initialization.

        Raises:
            TypeError: If spark_params is not a dict
            ValueError: If exists_sql or exists_executors are not booleans
        """
        if not isinstance(self.spark_params, dict):
            raise TypeError(
                f"spark_params must be a dict, got {type(self.spark_params)}"
            )
        if not isinstance(self.exists_sql, bool):
            raise ValueError(f"exists_sql must be a bool, got {type(self.exists_sql)}")
        if not isinstance(self.exists_executors, bool):
            raise ValueError(
                f"exists_executors must be a bool, got {type(self.exists_executors)}"
            )
