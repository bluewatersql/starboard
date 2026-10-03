# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
SparkApplication domain model.

Main aggregate root for Spark application data including jobs, stages, tasks, SQL, and executors.
"""

import gzip
from dataclasses import dataclass
from typing import Any, Literal

import orjson
import polars as pl

from starboard_core.log_parser.domain.models.metadata import (
    SparkApplicationMetadata,
)


@dataclass(frozen=True)
class SparkApplication:
    """
    Immutable Spark application aggregate root.

    This is the main domain entity that represents all data parsed from a Spark event log.
    It contains structured data about jobs, stages, tasks, SQL executions, executors,
    accumulators, and application metadata.

    All DataFrames are Polars DataFrames for memory efficiency and performance.

    Args:
        metadata: Application metadata (timing, config, flags)
        job_data: Job-level data (job IDs, status, timing)
        stage_data: Stage-level data (stage IDs, metrics, parents)
        task_data: Task-level data (task metrics, executor IDs, timing)
        accum_data: Accumulator data (custom metrics)
        sql_data: SQL execution data (query plans, timing) - None if no SQL
        executor_data: Executor data (executor IDs, hosts, resources) - None if not available

    Examples:
        >>> app = SparkApplication(
        ...     metadata=metadata,
        ...     job_data=pl.DataFrame({"job_id": [0, 1], "status": ["SUCCESS", "SUCCESS"]}),
        ...     stage_data=pl.DataFrame({"stage_id": [0, 1, 2]}),
        ...     task_data=pl.DataFrame({"task_id": [0, 1, 2, 3]}),
        ...     accum_data=pl.DataFrame({"accum_id": [0]}),
        ...     sql_data=None,
        ...     executor_data=None,
        ... )
        >>> app.metadata.exists_sql
        False
        >>> app.has_sql_data()
        False
    """

    metadata: SparkApplicationMetadata
    job_data: pl.DataFrame
    stage_data: pl.DataFrame
    task_data: pl.DataFrame
    accum_data: pl.DataFrame
    sql_data: pl.DataFrame | None
    executor_data: pl.DataFrame | None

    def __post_init__(self) -> None:
        """
        Validate field values after initialization.

        Raises:
            TypeError: If DataFrames are not Polars DataFrames
            ValueError: If required DataFrames are None
        """
        # Validate required DataFrames
        for field_name, field_value in [
            ("job_data", self.job_data),
            ("stage_data", self.stage_data),
            ("task_data", self.task_data),
            ("accum_data", self.accum_data),
        ]:
            if field_value is None:
                raise ValueError(f"{field_name} cannot be None")
            if not isinstance(field_value, pl.DataFrame):
                raise TypeError(
                    f"{field_name} must be a Polars DataFrame, got {type(field_value)}"
                )

        # Validate optional DataFrames (if present)
        if self.sql_data is not None and not isinstance(self.sql_data, pl.DataFrame):
            raise TypeError(
                f"sql_data must be a Polars DataFrame or None, got {type(self.sql_data)}"
            )
        if self.executor_data is not None and not isinstance(
            self.executor_data, pl.DataFrame
        ):
            raise TypeError(
                f"executor_data must be a Polars DataFrame or None, got {type(self.executor_data)}"
            )

        # Validate metadata consistency
        if self.metadata.exists_sql and self.sql_data is None:
            raise ValueError("metadata.exists_sql is True but sql_data is None")
        if not self.metadata.exists_sql and self.sql_data is not None:
            raise ValueError("metadata.exists_sql is False but sql_data is provided")

        if self.metadata.exists_executors and self.executor_data is None:
            raise ValueError(
                "metadata.exists_executors is True but executor_data is None"
            )
        if not self.metadata.exists_executors and self.executor_data is not None:
            raise ValueError(
                "metadata.exists_executors is False but executor_data is provided"
            )

    def has_sql_data(self) -> bool:
        """
        Check if SQL execution data is available.

        Returns:
            True if SQL data is available, False otherwise
        """
        return self.metadata.exists_sql and self.sql_data is not None

    def has_executor_data(self) -> bool:
        """
        Check if executor data is available.

        Returns:
            True if executor data is available, False otherwise
        """
        return self.metadata.exists_executors and self.executor_data is not None

    def to_dict(
        self,
        *,
        include_spark_params: bool = False,
        df_format: Literal["list", "records"] = "list",
    ) -> dict[str, Any]:
        """
        Convert SparkApplication to a dictionary representation.

        Serializes all DataFrames to dictionaries and aggregates metadata.
        Useful for JSON serialization, API responses, or persistence.

        Args:
            include_spark_params: If True, include spark_params in metadata.
                                  If False, exclude them (default).
            df_format: DataFrame serialization format:
                       - "list": {col: [values]} format (column-oriented)
                       - "records": [{col: val}, ...] format (row-oriented)

        Returns:
            Dictionary containing all application data with serialized DataFrames

        Examples:
            >>> app_dict = app.to_dict(include_spark_params=True, df_format="records")
            >>> "jobData" in app_dict
            True
            >>> isinstance(app_dict["metadata"], dict)
            True

        Raises:
            ValueError: If df_format is not "list" or "records"
        """
        if df_format not in ["list", "records"]:
            raise ValueError(
                f"df_format must be 'list' or 'records', got '{df_format}'"
            )

        def _df_to_dict(df: pl.DataFrame) -> dict[str, list] | list[dict[str, Any]]:
            """Convert Polars DataFrame to dict using correct API."""
            if df_format == "records":
                return df.to_dicts()  # type: ignore[return-value]
            else:  # "list"
                return df.to_dict(as_series=False)  # type: ignore[return-value]

        result: dict[str, Any] = {}

        # Serialize required DataFrames
        result["jobData"] = _df_to_dict(self.job_data)
        result["stageData"] = _df_to_dict(self.stage_data)
        result["taskData"] = _df_to_dict(self.task_data)
        result["accumData"] = _df_to_dict(self.accum_data)

        # Serialize optional DataFrames
        if self.has_sql_data():
            result["sqlData"] = _df_to_dict(self.sql_data)  # type: ignore[arg-type]

        if self.has_executor_data():
            result["executors"] = _df_to_dict(self.executor_data)  # type: ignore[arg-type]

        # Serialize metadata
        metadata_dict = {
            "application_info": {
                "timestamp_start_ms": self.metadata.application_info.timestamp_start_ms,
                "timestamp_end_ms": self.metadata.application_info.timestamp_end_ms,
                "runtime_sec": self.metadata.application_info.runtime_sec,
                "name": self.metadata.application_info.name,
                "id": self.metadata.application_info.id,
                "spark_version": self.metadata.application_info.spark_version,
                "emr_version_tag": self.metadata.application_info.emr_version_tag,
                "cloud_platform": self.metadata.application_info.cloud_platform,
                "cloud_provider": self.metadata.application_info.cloud_provider,
                "cluster_id": self.metadata.application_info.cluster_id,
            },
            "existsSQL": self.metadata.exists_sql,
            "existsExecutors": self.metadata.exists_executors,
        }

        if include_spark_params:
            metadata_dict["spark_params"] = self.metadata.spark_params

        result["metadata"] = metadata_dict

        return result

    @staticmethod
    def is_parsed_spark_app(data: Any) -> bool:
        """
        Check if a dictionary represents a parsed Spark application.

        This is a heuristic check based on the presence of expected keys.

        Args:
            data: Data to check (typically a dict)

        Returns:
            True if data looks like a parsed Spark application, False otherwise

        Examples:
            >>> SparkApplication.is_parsed_spark_app({"jobData": [], "stageData": []})
            True
            >>> SparkApplication.is_parsed_spark_app({"foo": "bar"})
            False
            >>> SparkApplication.is_parsed_spark_app("not a dict")
            False
        """
        if not isinstance(data, dict):
            return False
        # Heuristic: parsed apps have jobData
        return "jobData" in data

    def save(
        self,
        filepath: str,
        *,
        compress: bool = False,
        include_spark_params: bool = False,
    ) -> None:
        """
        Save SparkApplication to a JSON file (optionally compressed).

        Args:
            filepath: Path to save the file (without extension)
            compress: If True, compress with gzip (.json.gz), else plain JSON (.json)
            include_spark_params: If True, include spark_params in metadata

        Examples:
            >>> app.save("/tmp/my_app", compress=True)
            # Saves to /tmp/my_app.json.gz

        Raises:
            OSError: If file cannot be written
        """
        save_data = self.to_dict(
            include_spark_params=include_spark_params, df_format="list"
        )

        if compress:
            with gzip.open(filepath + ".json.gz", "wb") as fout:
                fout.write(orjson.dumps(save_data))
        else:
            with open(filepath + ".json", "wb") as fout:
                fout.write(orjson.dumps(save_data))
