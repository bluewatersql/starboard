# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Spark application data model.

Contains the core SparkApplication class that holds parsed Spark event log data.
"""

from __future__ import annotations

import gzip
import logging
import os
from typing import Any

import orjson
import polars as pl

from starboard_core.log_parser.parsing_models.application.types import (
    SparkApplicationMetadata,
)

logger = logging.getLogger(__name__)


class SparkApplication:
    """
    Data model for a Spark application with parsed event log data.

    Holds DataFrames for job, stage, task, SQL, executor, and accumulator data,
    along with application metadata.

    Attributes:
        existsSQL: Whether SQL data exists in the application
        sqlData: DataFrame containing SQL execution data
        existsExecutors: Whether executor data exists
        executorData: DataFrame containing executor information
        metadata: Application metadata (name, version, parameters, etc.)
        jobData: DataFrame containing job-level data
        stageData: DataFrame containing stage-level data
        taskData: DataFrame containing task-level data
        accumData: DataFrame containing accumulator data
    """

    def __init__(self):
        # TODO(BACKLOG-014): Remove redundant boolean flags; use `sqlData is not None` checks
        self.existsSQL: bool = False
        self.sqlData: pl.DataFrame | None = None

        self.existsExecutors: bool = False
        self.executorData: pl.DataFrame | None = None

        self.metadata: SparkApplicationMetadata | None = None

        # TODO(BACKLOG-015): Add docstrings for DataFrame fields
        self.jobData: pl.DataFrame | None = None
        self.stageData: pl.DataFrame | None = None
        self.taskData: pl.DataFrame | None = None
        self.accumData: pl.DataFrame | None = None

    def to_dict(
        self, *, include_spark_params: bool = False, df_format: str = "list"
    ) -> dict[str, Any]:
        """
        Convert all dataframes into dictionaries and aggregate into a single dict.

        Args:
            include_spark_params: Include spark_params in metadata
            df_format: "list" for {col: [values]} or "records" for [{col: val}, ...]

        Returns:
            Dictionary with all application data

        Raises:
            ValueError: If df_format is not "list" or "records"
        """

        if df_format not in ["list", "records"]:
            raise ValueError(f"Invalid dataframe format: {df_format}")

        def _df_to_dict(df: pl.DataFrame) -> dict | list:
            """Convert Polars DataFrame to dict using correct API."""
            # Polars API: to_dict(as_series=False) for list format, to_dicts() for records
            if df_format == "records":
                return df.to_dicts()
            else:  # "list"
                return df.to_dict(as_series=False)

        save_data = {}
        if hasattr(self, "jobData") and self.jobData is not None:
            save_data["jobData"] = _df_to_dict(self.jobData)
        if hasattr(self, "stageData") and self.stageData is not None:
            save_data["stageData"] = _df_to_dict(self.stageData)
        if hasattr(self, "taskData") and self.taskData is not None:
            save_data["taskData"] = _df_to_dict(self.taskData)
        if hasattr(self, "accumData") and self.accumData is not None:
            save_data["accumData"] = _df_to_dict(self.accumData)
        if self.existsSQL and self.sqlData is not None:
            save_data["sqlData"] = _df_to_dict(self.sqlData)
        if self.existsExecutors and self.executorData is not None:
            save_data["executors"] = _df_to_dict(self.executorData)

        if self.metadata is not None:
            if not include_spark_params:
                metadata = self.metadata.copy()
                metadata.pop("spark_params", None)
                save_data["metadata"] = metadata
            else:
                save_data["metadata"] = self.metadata
        else:
            save_data["metadata"] = {}

        return save_data

    @staticmethod
    def is_parsed_spark_app(data) -> bool:
        """
        Check if data represents a parsed Spark application.

        Args:
            data: Data to check

        Returns:
            True if data appears to be a parsed Spark application dict
        """
        if not isinstance(data, dict):
            return False

        # TODO(BACKLOG-016): Strengthen parsed-app detection beyond "jobData" key check
        return "jobData" in data

    def save(self, filepath: str | None = None, compress: bool = False) -> None:
        """
        Save application data to a local file.

        Args:
            filepath: Path to save to (defaults to eventlog name + "-sync")
            compress: Whether to gzip compress the output
        """
        save_data = self.to_dict()
        self.save_to_local(save_data, filepath, compress)

    def save_to_local(
        self, saveDat: dict[str, Any], filepath: str | None, compress: bool
    ) -> None:
        """
        Save dictionary data to a local JSON file.

        Args:
            saveDat: Dictionary data to save
            filepath: Path to save to (defaults to eventlog name + "-sync")
            compress: Whether to gzip compress the output

        Raises:
            Exception: If no filepath provided and no eventlog path found
        """
        if filepath is None:
            if self.spark_eventlog_path is None:
                raise Exception('No input eventlog found. Must specify "filepath".')
            inputFile = os.path.basename(
                os.path.normpath(self.spark_eventlog_path)
            ).replace(".gz", "")
            filepath = inputFile + "-sync"

        if compress is False:
            with open(filepath + ".json", "wb") as fout:
                fout.write(orjson.dumps(saveDat))
        elif compress is True:
            with gzip.open(filepath + ".json.gz", "wb") as fout:
                fout.write(orjson.dumps(saveDat))
        logger.debug(f"Saved object locally to: {filepath}")
