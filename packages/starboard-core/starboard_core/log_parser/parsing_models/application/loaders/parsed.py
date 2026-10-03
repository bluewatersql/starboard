# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Loader for already-parsed Spark application data.

Handles re-hydrating SparkApplication instances from JSON representations
that were previously saved.
"""

from __future__ import annotations

from collections.abc import Callable

import polars as pl

from starboard_core.log_parser.loaders.json import JSONBlobDataLoader
from starboard_core.log_parser.parsing_models.application.loaders.base import (
    AbstractSparkApplicationDataLoader,
    SparkApplicationClass,
    SparkApplicationLoaderKey,
)
from starboard_core.log_parser.parsing_models.application.model import (
    SparkApplication,
)
from starboard_core.log_parser.parsing_models.application.types import (
    SparkApplicationMetadata,
)


class ParsedLogSparkApplicationLoader(
    AbstractSparkApplicationDataLoader[str, dict, SparkApplication]
):
    """
    Creates a SparkApplication from a parsed JSON representation of that application. Useful for re-hydrating
    parsed logs that were saved somewhere (or submitted directly to us).

    This loader expects JSON files with the structure produced by `SparkApplication.to_dict()`.

    Example:
        >>> loader = ParsedLogSparkApplicationLoader(json_loader)
        >>> spark_app = loader.load("path/to/parsed-app.json")
        >>> print(spark_app.jobData)
    """

    def __init__(
        self,
        json_loader: JSONBlobDataLoader | None,
        spark_application_constructor: Callable[[], SparkApplication] | None = None,
    ):
        """
        Initialize the loader.

        Args:
            json_loader: Loader for JSON blob data
            spark_application_constructor: Optional custom SparkApplication factory
        """
        super().__init__(spark_application_constructor=spark_application_constructor)

        self._json_data_loader: JSONBlobDataLoader = json_loader

    @staticmethod
    def _ensure_string_keys(data: dict | list) -> dict | list:
        """
        Ensure all keys are strings for Polars DataFrame creation.
        Handles both dict format {'col': [vals]} and records format [{'col': val}, ...].

        Args:
            data: Dictionary or list to convert

        Returns:
            Data with all keys converted to strings
        """
        if isinstance(data, dict):
            # Dict/list format: convert top-level keys to strings
            return {str(k): v for k, v in data.items()}
        elif isinstance(data, list) and data and isinstance(data[0], dict):
            # Records format: convert keys in each record to strings
            return [{str(k): v for k, v in record.items()} for record in data]
        return data

    def load_raw_datas(self, keys: list[SparkApplicationLoaderKey]) -> list[dict]:
        """
        Loads many already-parsed eventlogs from the provided filepaths.

        Args:
            keys: List of file paths to load

        Returns:
            List of dictionaries containing parsed application data
        """
        return self._json_data_loader.load_many(keys)

    def init_spark_application(self, raw_data: dict) -> SparkApplication:
        """Initialize a new SparkApplication instance."""
        return super().init_spark_application(raw_data)

    def compute_recent_events(
        self,
        raw_data: dict,  # noqa: ARG002
        spark_app: SparkApplicationClass,  # noqa: ARG002
    ) -> SparkApplication:
        """
        'Recent Events' are really injected into other parts of the SparkApplication during initial computation
        So since we are 'rehydrating' a SparkApplication here, we can assume the recent event data is already
        in the proper places in our raw_data.

        Args:
            raw_data: The parsed data (unused - data already complete)
            spark_app: The SparkApplication (already has recent events)

        Returns:
            The unmodified SparkApplication
        """
        return spark_app

    def compute_sql_info(
        self, raw_data: dict, spark_app: SparkApplicationClass
    ) -> SparkApplication:
        """
        Extract SQL data from parsed JSON.

        Args:
            raw_data: Dictionary containing parsed application data
            spark_app: SparkApplication to populate

        Returns:
            SparkApplication with SQL data populated
        """
        metadata = raw_data.get("metadata", {})
        spark_app.existsSQL = existsSQL = metadata.get("existsSQL", False)
        if existsSQL:
            # Polars doesn't use index - sql_id remains as a regular column
            # Ensure all column names are strings (handle legacy data with non-string keys)
            sql_data = raw_data["sqlData"]
            sql_data = self._ensure_string_keys(sql_data)
            spark_app.sqlData = pl.DataFrame(sql_data)

        return spark_app

    def compute_executor_info(
        self, raw_data: dict, spark_app: SparkApplicationClass
    ) -> SparkApplication:
        """
        Extract executor data from parsed JSON.

        Args:
            raw_data: Dictionary containing parsed application data
            spark_app: SparkApplication to populate

        Returns:
            SparkApplication with executor data populated
        """
        spark_app.existsExecutors = exists_executors = raw_data.get("metadata", {}).get(
            "existsExecutors", False
        )
        if exists_executors:
            # Polars doesn't use index - executor_id remains as a regular column
            # Ensure all column names are strings (handle legacy data with non-string keys)
            executors = raw_data["executors"]
            executors = self._ensure_string_keys(executors)
            spark_app.executorData = pl.DataFrame(executors)

        return spark_app

    def compute_all_job_data(
        self, raw_data: dict, spark_app: SparkApplicationClass
    ) -> SparkApplication:
        """
        Extract job data from parsed JSON.

        Args:
            raw_data: Dictionary containing parsed application data
            spark_app: SparkApplication to populate

        Returns:
            SparkApplication with job data populated

        Notes:
            SPC113 - SDG
            Because of the way jobData is created, if there are no job Events in the eventlog then the
            correct fields will not exist. A second condition checking for the 'job_id' field is
            necessary here to ensure this method will run if this is the case.

            Note: stageData is initialized differently so this same issue does not exist for that
            structure. Furthermore, in the event that 'jobData' has no values within, 'stageData' will
            also have no values and an invalidLog exception will be thrown during log validation
            in SparkApplicationAdvanced.
        """
        job_data = raw_data.get("jobData")
        if job_data is not None:
            # Check for job_id in both dict and records format
            has_job_id = (
                ("job_id" in job_data)
                if isinstance(job_data, dict)
                else (
                    job_data
                    and isinstance(job_data[0], dict)
                    and "job_id" in job_data[0]
                )
            )
            if has_job_id:
                # Polars doesn't use index - job_id remains as a regular column
                # Ensure all column names are strings (handle legacy data with non-string keys)
                job_data = self._ensure_string_keys(job_data)
                df = pl.DataFrame(job_data)
                spark_app.jobData = df

        return spark_app

    def compute_all_stage_data(
        self, raw_data: dict, spark_app: SparkApplicationClass
    ) -> SparkApplication:
        """
        Extract stage data from parsed JSON.

        Args:
            raw_data: Dictionary containing parsed application data
            spark_app: SparkApplication to populate

        Returns:
            SparkApplication with stage data populated
        """
        if "stageData" in raw_data:
            # Polars doesn't use index - stage_id remains as a regular column
            # Ensure all column names are strings (handle legacy data with non-string keys)
            stage_data = raw_data["stageData"]
            stage_data = self._ensure_string_keys(stage_data)
            spark_app.stageData = pl.DataFrame(stage_data)

        return spark_app

    def compute_all_task_data(
        self, raw_data: dict, spark_app: SparkApplicationClass
    ) -> SparkApplication:
        """
        Extract task data from parsed JSON.

        Args:
            raw_data: Dictionary containing parsed application data
            spark_app: SparkApplication to populate

        Returns:
            SparkApplication with task data populated
        """
        if "taskData" in raw_data:
            # Polars doesn't use index - task_id remains as a regular column
            # Ensure all column names are strings (handle legacy data with non-string keys)
            task_data = raw_data["taskData"]
            task_data = self._ensure_string_keys(task_data)
            spark_app.taskData = pl.DataFrame(task_data)

        return spark_app

    def compute_all_driver_accum_data(
        self, raw_data: dict, spark_app: SparkApplicationClass
    ) -> SparkApplication:
        """
        Extract accumulator data from parsed JSON.

        Args:
            raw_data: Dictionary containing parsed application data
            spark_app: SparkApplication to populate

        Returns:
            SparkApplication with accumulator data populated
        """
        if "accumData" in raw_data:
            # Polars doesn't use index - sql_id remains as a regular column
            # Ensure all column names are strings (handle legacy data with non-string keys)
            accum_data = raw_data["accumData"]
            accum_data = self._ensure_string_keys(accum_data)
            spark_app.accumData = pl.DataFrame(accum_data)

        return spark_app

    def compute_all_metadata(
        self,
        raw_data: dict,
        spark_app: SparkApplicationClass,  # noqa: ARG002
    ) -> SparkApplicationMetadata:
        """
        Extract application metadata from parsed JSON.

        Args:
            raw_data: Dictionary containing parsed application data
            spark_app: SparkApplication (unused for parsed data)

        Returns:
            Application metadata dictionary
        """
        return raw_data.get("metadata", {})
