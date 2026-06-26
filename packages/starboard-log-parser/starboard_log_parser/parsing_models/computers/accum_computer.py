# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Accumulator data computation for Spark applications."""

import logging

import polars as pl

from starboard_log_parser.parsing_models.event_log_parser import (
    ApplicationModel,
)

logger = logging.getLogger(__name__)


class AccumDataComputer:
    """Computes accumulator metrics from ApplicationModel.

    This class extracts driver accumulator values from a parsed Spark application.
    Only driver accumulator values are updated, so we filter out nulls.

    The computed DataFrame contains:
    - Accumulator values (transposed from dict)
    - start_times: SQL query start times (if SQL data available)
    - end_times: SQL query end times (if SQL data available)

    Example:
        >>> computer = AccumDataComputer()
        >>> app_model = ApplicationModel(...)
        >>> accum_df = computer.compute(app_model)
        >>> if accum_df is not None:
        ...     print(f"Found {len(accum_df)} accumulator entries")
    """

    def compute(
        self, app_model: ApplicationModel, sql_data: pl.DataFrame | None = None
    ) -> pl.DataFrame | None:
        """Compute accumulator DataFrame from ApplicationModel.

        Args:
            app_model: Parsed application model containing accumulator data.
            sql_data: Optional SQL DataFrame for joining start/end times.

        Returns:
            DataFrame with accumulator metrics, or None if no data available.
        """
        # Check if accumulator data exists
        if not (hasattr(app_model, "accum_metrics") and app_model.accum_metrics):
            logger.debug(
                "No accum_metrics attribute found in ApplicationModel (expected for jobs without accumulators)"
            )
            return None

        # Convert dict keys to strings for Polars compatibility
        accum_data = {str(k): v for k, v in app_model.accum_metrics.items()}

        df = (
            pl.DataFrame(accum_data)
            .transpose()
            # only driver accum values are updated
            .drop_nulls()
        )

        # If no columns or no "value" column, return None
        if len(df) == 0 or "value" not in df.columns:
            logger.debug(
                "No valid accumulator data found with 'value' column (expected for jobs without custom accumulators)"
            )
            return None

        # Get start and end times of sql_id if SQL data is available
        if sql_data is not None and len(sql_data) > 0:
            start_times = []
            end_times = []

            for row in df.iter_rows(named=True):
                # Try to find matching SQL row
                try:
                    sql_row = sql_data.filter(pl.col("sql_id") == row["sql_id"]).row(
                        0, named=True
                    )
                    start_times.append(sql_row["start_time"])
                    end_times.append(sql_row["end_time"])
                except Exception:
                    # If no matching SQL row, append None
                    start_times.append(None)
                    end_times.append(None)

            df = df.with_columns(
                [
                    pl.Series("start_times", start_times),
                    pl.Series("end_times", end_times),
                ]
            )

        return df
