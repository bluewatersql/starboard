# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Loader for unparsed Spark event logs.

Handles parsing raw Spark event log files into SparkApplication instances.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

import numpy as np
import polars as pl

from starboard_core.log_parser.loaders.json import JSONLinesDataLoader
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
from starboard_core.log_parser.parsing_models.event_log_parser import (
    ApplicationModel,
)
from starboard_core.log_parser.parsing_models.validation_configs import (
    ConfigValidationDatabricks,
    ConfigValidationEMR,
)
from starboard_core.log_parser.parsing_models.validation_event_data import (
    EventDataValidation,
)

if TYPE_CHECKING:
    from starboard_core.log_parser.parsing_models.computers.registry import ComputerRegistry

logger = logging.getLogger(__name__)


class UnparsedLogSparkApplicationLoader(
    AbstractSparkApplicationDataLoader[str, ApplicationModel, SparkApplicationClass]
):
    """
    From a raw set of Spark log lines, constructs a SparkApplication.

    Now uses ComputerRegistry for dependency injection and cleaner separation of concerns.

    This loader:
    1. Loads raw JSON lines from event log files
    2. Creates ApplicationModel from the lines
    3. Validates the application model
    4. Computes all data (SQL, executor, job, stage, task, accum, metadata)
    5. Returns a fully constructed SparkApplication

    Example:
        >>> loader = UnparsedLogSparkApplicationLoader(json_lines_loader)
        >>> spark_app = loader.load("path/to/eventlog.gz")
        >>> print(spark_app.jobData)
    """

    def __init__(
        self,
        json_lines_loader: JSONLinesDataLoader | None,
        spark_application_constructor: Callable[[], SparkApplication] | None = None,
        stdout_path: str | None = None,
        debug: bool = False,
        computer_registry: ComputerRegistry | None = None,
    ):
        """
        Initialize the loader.

        Args:
            json_lines_loader: Loader for JSON lines data
            spark_application_constructor: Optional custom SparkApplication factory
            stdout_path: Optional path to stdout logs
            debug: Whether to enable debug logging
            computer_registry: Optional ComputerRegistry for dependency injection
        """
        super().__init__(spark_application_constructor=spark_application_constructor)

        self.stdout_path = stdout_path
        self.debug = debug

        self._json_lines_loader: JSONLinesDataLoader = json_lines_loader

        # Import here to avoid circular dependency
        from starboard_core.log_parser.parsing_models.computers.registry import (
            ComputerRegistry,
        )

        self._computers = computer_registry or ComputerRegistry.create_default()

    @staticmethod
    def validate_app_model(app_model: ApplicationModel) -> None:
        """
        Validate the application model using platform-specific validators.

        Args:
            app_model: The ApplicationModel to validate

        Raises:
            ValueError: If the cloud platform is unknown
            Various validation exceptions from validators
        """
        if app_model.cloud_platform == "emr":
            val1 = ConfigValidationEMR(app=app_model)
        elif app_model.cloud_platform == "databricks":
            val1 = ConfigValidationDatabricks(app=app_model)
        else:
            raise ValueError(
                f"Unknown cloud_platform {app_model.cloud_platform} provided in app_model"
            )

        val1.validate()

        val2 = EventDataValidation(app=app_model)
        val2.validate()

    def load_raw_datas(
        self, keys: list[SparkApplicationLoaderKey]
    ) -> list[ApplicationModel]:
        """
        Returns a list of ApplicationModels, provided some keys pointing to some raw eventlog file locations. These
        models have not yet been validated, since we are loading the "raw" data here.

        Args:
            keys: List of file paths or URLs pointing to event log files

        Returns:
            List of ApplicationModel instances (not yet validated)

        Raises:
            RuntimeError: If instance was initialized without a json_lines_loader
        """
        if self._json_lines_loader is None:
            raise RuntimeError(
                "Instance was initialized without a json_lines_loader, and therefore can't be used "
                + "to load raw data."
            )

        raw_datas = self._json_lines_loader.load_many(keys)

        app_models = [ApplicationModel(log_lines=raw_data) for raw_data in raw_datas]

        return app_models

    def init_spark_application(
        self, raw_data: ApplicationModel
    ) -> SparkApplicationClass:
        """
        Initialize a SparkApplication after validating the ApplicationModel.

        Args:
            raw_data: ApplicationModel to validate and initialize from

        Returns:
            A new SparkApplication instance
        """
        self.validate_app_model(raw_data)
        return super().init_spark_application(raw_data)

    def compute_sql_info(
        self, raw_data: ApplicationModel, spark_app: SparkApplicationClass
    ) -> SparkApplication:
        """
        Compute SQL data using SQLDataComputer.

        Args:
            raw_data: ApplicationModel containing event log data
            spark_app: SparkApplication to populate

        Returns:
            SparkApplication with SQL data populated
        """
        app_model = raw_data

        sql_df = self._computers.sql_computer.compute(app_model)

        if sql_df is not None:
            spark_app.existsSQL = True
            spark_app.sqlData = sql_df
        else:
            spark_app.existsSQL = False

        return spark_app

    def compute_executor_info(
        self, raw_data: ApplicationModel, spark_app: SparkApplicationClass
    ) -> SparkApplication:
        """
        Compute executor data using ExecutorDataComputer.

        Args:
            raw_data: ApplicationModel containing event log data
            spark_app: SparkApplication to populate

        Returns:
            SparkApplication with executor data populated
        """
        app_model = raw_data

        executor_df = self._computers.executor_computer.compute(app_model)

        if executor_df is not None:
            spark_app.existsExecutors = True
            spark_app.executorData = executor_df
        else:
            spark_app.existsExecutors = False

        return spark_app

    def compute_all_job_data(
        self, raw_data: ApplicationModel, spark_app: SparkApplicationClass
    ) -> SparkApplication:
        """
        Compute job data using JobDataComputer.

        Args:
            raw_data: ApplicationModel containing event log data
            spark_app: SparkApplication to populate

        Returns:
            SparkApplication with job data populated
        """
        app_model = raw_data
        t1 = time.time()

        job_df = self._computers.job_computer.compute(
            app_model, sql_data=spark_app.sqlData if spark_app.existsSQL else None
        )

        spark_app.jobData = job_df if job_df is not None else pl.DataFrame()

        logger.debug("Aggregated job data [%.2f]" % (time.time() - t1))
        return spark_app

    def compute_all_task_data(
        self, raw_data: ApplicationModel, spark_app: SparkApplicationClass
    ) -> SparkApplication:
        """
        Compute task data using TaskDataComputer.

        Args:
            raw_data: ApplicationModel containing event log data
            spark_app: SparkApplication to populate

        Returns:
            SparkApplication with task data populated
        """
        app_model = raw_data
        t1 = time.time()

        task_df = self._computers.task_computer.compute(
            app_model, sql_data=spark_app.sqlData if spark_app.existsSQL else None
        )

        spark_app.taskData = task_df if task_df is not None else pl.DataFrame()

        logger.debug("Aggregated task data [%.2fs]" % (time.time() - t1))
        return spark_app

    def compute_all_stage_data(
        self, raw_data: ApplicationModel, spark_app: SparkApplicationClass
    ) -> SparkApplication:
        """
        Compute stage data using StageDataComputer.

        Args:
            raw_data: ApplicationModel containing event log data
            spark_app: SparkApplication to populate

        Returns:
            SparkApplication with stage data populated
        """
        app_model = raw_data
        t1 = time.time()

        stage_df = self._computers.stage_computer.compute(
            app_model,
            task_data=spark_app.taskData,
            sql_data=spark_app.sqlData if spark_app.existsSQL else None,
        )

        spark_app.stageData = stage_df if stage_df is not None else pl.DataFrame()

        logger.debug("Aggregated stage data [%.2fs]" % (time.time() - t1))
        return spark_app

    def compute_all_driver_accum_data(
        self, raw_data: ApplicationModel, spark_app: SparkApplicationClass
    ) -> SparkApplication:
        """
        Compute accumulator data using AccumDataComputer.

        Args:
            raw_data: ApplicationModel containing event log data
            spark_app: SparkApplication to populate

        Returns:
            SparkApplication with accumulator data populated
        """
        app_model = raw_data
        t1 = time.time()

        accum_df = self._computers.accum_computer.compute(
            app_model, sql_data=spark_app.sqlData if spark_app.existsSQL else None
        )

        spark_app.accumData = accum_df if accum_df is not None else pl.DataFrame()

        logger.debug("Aggregated accum data [%.2fs]" % (time.time() - t1))
        return spark_app

    def compute_all_metadata(
        self, raw_data: ApplicationModel, spark_app: SparkApplicationClass
    ) -> SparkApplicationMetadata:
        """
        Compute application metadata using MetadataComputer.

        Args:
            raw_data: ApplicationModel containing event log data
            spark_app: SparkApplication to get SQL/executor existence info

        Returns:
            Application metadata dictionary
        """
        app_model = raw_data

        return self._computers.metadata_computer.compute(
            app_model,
            exists_sql=spark_app.existsSQL,
            exists_executors=spark_app.existsExecutors,
        )

    def compute_recent_events(
        self,
        raw_data: ApplicationModel,  # noqa: ARG002
        spark_app: SparkApplicationClass,  # noqa: ARG002
    ) -> SparkApplicationClass:
        """
        Compute time_since_last_event for stages and SQL queries.

        This calculates how long it has been since the last task or SQL event
        completed before each stage/SQL event started.

        Args:
            raw_data: ApplicationModel (unused)
            spark_app: SparkApplication with populated task/stage/SQL data

        Returns:
            SparkApplication with time_since_last_event columns added
        """
        # Polars API: use .to_numpy() instead of .values
        tcomp = np.concatenate(([0.0], spark_app.taskData["end_time"].to_numpy()))

        if spark_app.existsSQL:
            tcomp = np.concatenate(
                (
                    tcomp,
                    spark_app.sqlData["start_time"].to_numpy(),
                    spark_app.sqlData["end_time"].to_numpy(),
                )
            )

        # Polars doesn't have .index - iterate over rows directly
        trecent = []
        for row in spark_app.stageData.iter_rows(named=True):
            row.get("stage_id")  # Assuming stage_id column exists
            tstart = row["start_time"]
            trecent.append(tstart - tcomp[tcomp < tstart].max())

        spark_app.stageData = spark_app.stageData.with_columns(
            pl.Series("time_since_last_event", trecent)
        )

        if spark_app.existsSQL:
            trecent = []
            for row in spark_app.sqlData.iter_rows(named=True):
                row.get("sql_id")  # Assuming sql_id column exists
                tstart = row["start_time"]

                tmp = tcomp[tcomp < tstart]

                if len(tmp) == 0:
                    trecent.append(0)
                else:
                    trecent.append(tstart - tcomp[tcomp < tstart].max())

            spark_app.sqlData = spark_app.sqlData.with_columns(
                pl.Series("time_since_last_event", trecent)
            )

        return spark_app
