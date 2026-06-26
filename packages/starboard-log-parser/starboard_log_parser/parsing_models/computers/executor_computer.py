# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Executor data computation for Spark applications."""

import logging
from collections import defaultdict

import polars as pl

from starboard_log_parser.parsing_models.event_log_parser import (
    ApplicationModel,
)

logger = logging.getLogger(__name__)


class ExecutorDataComputer:
    """Computes executor metrics from ApplicationModel.

    This class extracts executor (worker node) information from a parsed Spark
    application, including executor IDs, cores, start/end times, hosts, and
    removal reasons.

    The computed DataFrame contains:
    - executor_id: Unique identifier for the executor
    - cores: Number of cores allocated to the executor
    - start_time: Executor start time (relative to app start)
    - end_time: Executor end time (relative to app start, or None if still running)
    - host: Host machine where executor ran
    - removed_reason: Reason executor was removed (if applicable)

    Example:
        >>> computer = ExecutorDataComputer()
        >>> app_model = ApplicationModel(...)
        >>> executor_df = computer.compute(app_model)
        >>> if executor_df is not None:
        ...     print(f"Found {len(executor_df)} executors")
    """

    def compute(self, app_model: ApplicationModel) -> pl.DataFrame | None:
        """Compute executor DataFrame from ApplicationModel.

        Args:
            app_model: Parsed application model containing executor data.

        Returns:
            DataFrame with executor metrics, or None if no executor data available.

        Raises:
            ValueError: If app_model.start_time is None.
        """
        # Check if executor data exists
        if not (hasattr(app_model, "executors") and app_model.executors):
            logger.warning("No executor attribute found in ApplicationModel")
            return None

        if app_model.start_time is None:
            raise ValueError("app_model.start_time must be set")

        df = defaultdict(lambda: [])

        for xid, executor in app_model.executors.items():
            # There appears to be a scenario in Spark where if an executor is
            # started and then stopped very quickly, that executor's startup
            # routine will cause an exception, killing the executor. Since the
            # startup routine never actually finished, a `start_time` is never
            # registered. Databricks Autoscaling or Spot Terminations are
            # common causes of this scenario.
            start_time = (
                (executor.start_time / 1000) - app_model.start_time
                if executor.start_time is not None
                else None
            )

            # If an executor lives until the end of the Spark Application, it
            # may never register an `end_time`
            end_time = (
                (executor.end_time / 1000) - app_model.start_time
                if executor.end_time is not None
                else None
            )

            df["executor_id"].append(xid)
            df["cores"].append(executor.cores)
            df["start_time"].append(start_time)
            df["end_time"].append(end_time)
            df["host"].append(executor.host)
            df["removed_reason"].append(executor.removed_reason)

        result_df = pl.DataFrame(df).sort("executor_id")

        return result_df
