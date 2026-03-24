"""Job data computation for Spark applications."""

import logging

import polars as pl

from starboard_log_parser.parsing_models.event_log_parser import (
    ApplicationModel,
)

logger = logging.getLogger(__name__)


class JobDataComputer:
    """Computes job-level metrics from ApplicationModel.

    This class extracts job information from a parsed Spark application,
    including job IDs, SQL associations, stage lists, and timing information.

    The computed DataFrame contains:
    - job_id: Unique identifier for the job
    - sql_id: Associated SQL query ID (if applicable)
    - stage_ids: List of stage IDs in this job
    - submission_time: Job submission time (relative to app start)
    - completion_time: Job completion time (relative to app start)
    - duration: Job duration
    - submission_timestamp: Absolute submission timestamp
    - completion_timestamp: Absolute completion timestamp

    Example:
        >>> computer = JobDataComputer()
        >>> app_model = ApplicationModel(...)
        >>> job_df = computer.compute(app_model)
        >>> if job_df is not None:
        ...     print(f"Found {len(job_df)} jobs")
    """

    def compute(
        self, app_model: ApplicationModel, sql_data: pl.DataFrame | None = None
    ) -> pl.DataFrame | None:
        """Compute job DataFrame from ApplicationModel.

        Args:
            app_model: Parsed application model containing job data.
            sql_data: Optional SQL DataFrame for joining sql_id to jobs.

        Returns:
            DataFrame with job metrics, or None if no job data available.

        Raises:
            ValueError: If app_model.start_time is None.
        """
        # Check if job data exists
        if not (hasattr(app_model, "jobs") and app_model.jobs):
            logger.warning("No jobs attribute found in ApplicationModel")
            return None

        if app_model.start_time is None:
            raise ValueError("app_model.start_time must be set")

        ref_time = app_model.start_time
        dfs: list[pl.DataFrame] = []

        for jid, job in app_model.jobs.items():
            # Collect stage IDs for this job
            stage_ids = list(job.stages)

            dfs.append(
                pl.DataFrame(
                    {
                        "job_id": [jid],
                        "sql_id": None,
                        "stage_ids": [stage_ids],
                        "submission_time": [job.submission_time - ref_time],
                        "completion_time": [job.completion_time - ref_time],
                        "duration": [job.completion_time - job.submission_time],
                        "submission_timestamp": [job.submission_time],
                        "completion_timestamp": [job.completion_time],
                    }
                )
            )

        # If no jobs, return None
        if not dfs:
            logger.warning("No valid job data found")
            return None

        df = pl.concat(dfs, how="vertical").sort("job_id")

        # Join with SQL data if provided
        if sql_data is not None and len(sql_data) > 0:
            # Build a mapping of job_id -> sql_id
            job_to_sql = {}
            for row in sql_data.iter_rows(named=True):
                for jid in row["job_ids"]:
                    job_to_sql[jid] = row["sql_id"]

            # Update sql_id column using the mapping
            df = df.with_columns(
                pl.col("job_id")
                .map_elements(lambda jid: job_to_sql.get(jid), return_dtype=pl.Int64)
                .alias("sql_id")
            )

        return df
