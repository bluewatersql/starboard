# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Stage data computation for Spark applications."""

import logging
from collections import defaultdict
from collections.abc import Iterator

import polars as pl

from starboard_core.log_parser.parsing_models.event_log_parser import (
    ApplicationModel,
)

logger = logging.getLogger(__name__)


class StageDataComputer:
    """Computes stage-level metrics from ApplicationModel.

    This class extracts stage information by aggregating task data for each stage.
    Requires task data to be computed first.

    The computed DataFrame contains:
    - stage_id, query_id, job_id
    - task_ids: List of task IDs in this stage
    - parents: Parent stage IDs (for DAG)
    - rdd_ids: RDD IDs used in this stage
    - stage_info: Metadata (name, num_tasks, num_rdds, etc.)
    - Aggregated metrics from tasks: input/output MB, memory, timings, etc.

    Example:
        >>> computer = StageDataComputer()
        >>> app_model = ApplicationModel(...)
        >>> task_df = TaskDataComputer().compute(app_model)
        >>> stage_df = computer.compute(app_model, task_df)
        >>> if stage_df is not None:
        ...     print(f"Found {len(stage_df)} stages")
    """

    def compute(
        self,
        app_model: ApplicationModel,
        task_data: pl.DataFrame,
        sql_data: pl.DataFrame | None = None,
    ) -> pl.DataFrame | None:
        """Compute stage DataFrame from ApplicationModel and task data.

        Args:
            app_model: Parsed application model containing stage data.
            task_data: Task DataFrame (required for aggregation).
            sql_data: Optional SQL DataFrame for mapping stages to queries.

        Returns:
            DataFrame with stage metrics, or None if no stage data available.

        Raises:
            ValueError: If task_data is None or empty.
        """
        # Check if job data exists (stages are nested in jobs)
        if not (hasattr(app_model, "jobs") and app_model.jobs):
            logger.warning("No jobs attribute found in ApplicationModel")
            return None

        if task_data is None or len(task_data) == 0:
            raise ValueError("task_data must be provided and non-empty")

        # Extract stage IDs from within SQL queries
        sid2qid = defaultdict(lambda: None)
        if sql_data is not None and len(sql_data) > 0:
            for row in sql_data.iter_rows(named=True):
                for sid in row["stage_ids"]:
                    sid2qid[sid] = row["sql_id"]

        # OPTIMIZED: Use generator pattern
        def stage_generator() -> Iterator[dict]:
            """Generator that yields stage records as dictionaries."""
            for jid, job in app_model.jobs.items():
                for sid, stage in job.stages.items():
                    # Get the task-ids for this stage
                    taskids = [task.task_id for task in stage.tasks]

                    # Filter task data for this stage
                    stage_task_data = task_data.filter(pl.col("task_id").is_in(taskids))

                    # Skip if no tasks found (shouldn't happen)
                    if len(stage_task_data) == 0:
                        continue

                    yield {
                        "stage_id": sid,
                        "query_id": sid2qid[sid],
                        "job_id": jid,
                        "task_ids": taskids,
                        "parents": app_model.dag.parents_dag_dict[sid],
                        "rdd_ids": app_model.dag.stage_rdd_dict[sid],
                        "stage_info": {
                            "stage_name": stage.stage_name,
                            "num_tasks": stage.num_tasks,
                            "num_rdds": len(stage.stage_info["RDD Info"]),
                            "num_parents": len(stage.stage_info["Parent IDs"]),
                            "final_rdd_name": stage.stage_info["RDD Info"][0]["Name"],
                        },
                        "start_time": stage_task_data["start_time"].min(),
                        "end_time": stage_task_data["end_time"].max(),
                        "duration": stage_task_data["end_time"].max()
                        - stage_task_data["start_time"].min(),
                        "num_tasks": len(stage_task_data),
                        "task_time": stage_task_data["duration"].sum(),
                        "input_mb": stage_task_data["input_mb"].sum(),
                        "output_mb": stage_task_data["output_mb"].sum(),
                        "peak_execution_memory": stage_task_data[
                            "peak_execution_memory"
                        ].max(),
                        "shuffle_mb_written": stage_task_data[
                            "shuffle_mb_written"
                        ].sum(),
                        "remote_mb_read": stage_task_data["remote_mb_read"].sum(),
                        "memory_bytes_spilled": stage_task_data[
                            "memory_bytes_spilled"
                        ].sum(),
                        "disk_bytes_spilled": stage_task_data[
                            "disk_bytes_spilled"
                        ].sum(),
                        "result_size": stage_task_data["result_size"].sum(),
                        "executor_run_time": stage_task_data["executor_run_time"].sum(),
                        "executor_deserialize_time": stage_task_data[
                            "executor_deserialize_time"
                        ].sum(),
                        "result_serialization_time": stage_task_data[
                            "result_serialization_time"
                        ].sum(),
                        "executor_cpu_time": stage_task_data["executor_cpu_time"].sum(),
                        "gc_time": stage_task_data["gc_time"].sum(),
                        "scheduler_delay": stage_task_data["scheduler_delay"].sum(),
                        "fetch_wait_time": stage_task_data["fetch_wait_time"].sum(),
                        "local_read_time": stage_task_data["local_read_time"].sum(),
                        "compute_time": stage_task_data["compute_time"].sum(),
                        "task_compute_time": stage_task_data["task_compute_time"].sum(),
                        "input_read_time": stage_task_data["input_read_time"].sum(),
                        "output_write_time": stage_task_data["output_write_time"].sum(),
                        "shuffle_write_time": stage_task_data[
                            "shuffle_write_time"
                        ].sum(),
                    }

        # Create DataFrame directly from generator
        stage_records = list(stage_generator())

        if not stage_records:
            logger.warning("No stage records found")
            return None

        df = (
            pl.DataFrame(stage_records)
            .unique(subset=["stage_id"], keep="first")
            .sort("stage_id")
        )

        return df
