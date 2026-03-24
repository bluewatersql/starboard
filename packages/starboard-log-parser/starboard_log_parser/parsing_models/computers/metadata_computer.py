"""Metadata computation for Spark applications."""

import logging
from typing import TypedDict

from starboard_log_parser.parsing_models.event_log_parser import (
    ApplicationModel,
)

logger = logging.getLogger(__name__)


class SparkApplicationInfo(TypedDict):
    """Application-level information."""

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


class SparkApplicationMetadata(TypedDict):
    """Complete application metadata."""

    application_info: SparkApplicationInfo
    spark_params: dict[str, str | int | float | dict]
    existsSQL: bool
    existsExecutors: bool


class MetadataComputer:
    """Computes application metadata from ApplicationModel.

    This class extracts high-level application information such as name, ID,
    version, cloud platform, cluster ID, and Spark configuration parameters.

    Unlike other computers, this returns a dictionary (SparkApplicationMetadata)
    instead of a DataFrame.

    Example:
        >>> computer = MetadataComputer()
        >>> app_model = ApplicationModel(...)
        >>> metadata = computer.compute(app_model, exists_sql=True, exists_executors=True)
        >>> print(metadata["application_info"]["name"])
    """

    def compute(
        self, app_model: ApplicationModel, exists_sql: bool, exists_executors: bool
    ) -> SparkApplicationMetadata:
        """Compute application metadata from ApplicationModel.

        Args:
            app_model: Parsed application model containing metadata.
            exists_sql: Whether SQL data exists.
            exists_executors: Whether executor data exists.

        Returns:
            Dictionary with application metadata.

        Raises:
            ValueError: If app_model is missing required fields.
        """
        if app_model.start_time is None:
            raise ValueError("app_model.start_time must be set")
        if app_model.finish_time is None:
            raise ValueError("app_model.finish_time must be set")
        if not hasattr(app_model, "app_name"):
            raise ValueError("app_model.app_name must be set")
        if not hasattr(app_model, "spark_metadata"):
            raise ValueError("app_model.spark_metadata must be set")

        app_info: SparkApplicationInfo = {
            "timestamp_start_ms": int(app_model.start_time * 1000),
            "timestamp_end_ms": int(app_model.finish_time * 1000),
            "runtime_sec": app_model.finish_time - app_model.start_time,
            "name": app_model.app_name,
            "id": app_model.spark_metadata["spark.app.id"],
            "spark_version": app_model.spark_version,
            "emr_version_tag": app_model.emr_version_tag,
            "cloud_platform": app_model.cloud_platform,
            "cloud_provider": app_model.cloud_provider,
            "cluster_id": app_model.cluster_id,
        }

        return {
            "application_info": app_info,
            "spark_params": app_model.spark_metadata,
            "existsSQL": exists_sql,
            "existsExecutors": exists_executors,
        }
