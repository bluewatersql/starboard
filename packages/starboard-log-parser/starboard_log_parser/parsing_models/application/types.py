"""
Type definitions for Spark application metadata.

Contains TypedDict definitions used across the application model.
"""

from __future__ import annotations

from typing import TypedDict


class SparkApplicationInfo(TypedDict):
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
    application_info: SparkApplicationInfo
    spark_params: dict[str, str | int | float | dict]
    existsSQL: bool
    existsExecutors: bool
