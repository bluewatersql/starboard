"""SQL data computation for Spark applications."""

import logging

import polars as pl

from starboard_log_parser.parsing_models.event_log_parser import (
    ApplicationModel,
)

logger = logging.getLogger(__name__)


class SQLDataComputer:
    """Computes SQL execution data from ApplicationModel.

    This class extracts SQL query information from a parsed Spark application,
    including query IDs, descriptions, timings, and associated jobs/stages/tasks.

    The computed DataFrame contains:
    - sql_id: Unique identifier for the SQL query
    - description: SQL query description
    - start_time: Query start time (relative to app start)
    - end_time: Query end time (relative to app start)
    - duration: Query duration
    - job_ids: List of job IDs associated with this query
    - stage_ids: List of stage IDs associated with this query
    - task_ids: List of task IDs associated with this query

    Example:
        >>> computer = SQLDataComputer()
        >>> app_model = ApplicationModel(...)
        >>> sql_df = computer.compute(app_model)
        >>> if sql_df is not None:
        ...     print(f"Found {len(sql_df)} SQL queries")
    """

    def compute(self, app_model: ApplicationModel) -> pl.DataFrame | None:
        """Compute SQL DataFrame from ApplicationModel.

        Args:
            app_model: Parsed application model containing SQL execution data.

        Returns:
            DataFrame with SQL execution data, or None if no SQL data available.

        Raises:
            ValueError: If app_model.start_time is None.
        """
        # Check if SQL data exists
        if not (hasattr(app_model, "sql") and app_model.sql):
            logger.warning("No sql attribute found in ApplicationModel")
            return None

        if app_model.start_time is None:
            raise ValueError("app_model.start_time must be set")

        dfs: list[pl.DataFrame] = []

        for sqlid, sql in app_model.sql.items():
            sql_jobs = []
            sql_stages = []
            sql_tasks = []

            # Sometimes an SQL event will be missing. To be informative, both
            # events must be present. But this information is not critical, so
            # if either event is missing then simply reject the SQL data
            if "start_time" not in sql or "end_time" not in sql:
                continue

            # Find all jobs associated with this SQL query
            for jid, job in app_model.jobs.items():
                if (job.submission_time >= sql["start_time"]) and (
                    job.submission_time <= sql["end_time"]
                ):
                    # Handle missing completion time
                    if "completion_time" not in job.__dict__:
                        logger.debug(
                            f"Job {jid} missing completion time. "
                            f"Substituting with associated SQL {sqlid} completion time"
                        )
                        job.completion_time = sql["end_time"]

                    sql_jobs.append(jid)

                    # Find all stages and tasks in this job
                    for sid, stage in job.stages.items():
                        sql_stages.append(sid)
                        for task in stage.tasks:
                            sql_tasks.append(task.task_id)

            dfs.append(
                pl.DataFrame(
                    {
                        "sql_id": [sqlid],
                        "description": sql["description"],
                        "start_time": [sql["start_time"] - app_model.start_time],
                        "end_time": [sql["end_time"] - app_model.start_time],
                        "duration": [sql["end_time"] - sql["start_time"]],
                        "job_ids": [sql_jobs],
                        "stage_ids": [sql_stages],
                        "task_ids": [sql_tasks],
                    }
                )
            )

        # If no valid SQL data, return None
        if not dfs:
            logger.warning("No valid SQL data found with required fields")
            return None

        df = (
            pl.concat(dfs, how="vertical")
            # Remove any rows that have duplicate sql_id column values
            .unique(subset=["sql_id"], keep="first")
            .sort("sql_id")
        )

        return df
