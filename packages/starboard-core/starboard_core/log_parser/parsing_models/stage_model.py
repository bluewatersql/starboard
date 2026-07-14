# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
from __future__ import annotations

from typing import Any

import numpy

from starboard_core.log_parser.parsing_models.task_model import TaskModel


class StageModel:
    """Model for a stage within a Spark job.

    A stage is a set of tasks that can be executed in parallel. Stages are separated
    by shuffle boundaries in the execution plan. This model aggregates metrics across
    all tasks in the stage.

    Attributes:
        id: Unique stage identifier
        stage_name: Human-readable stage name
        attempt_id: Stage attempt number (increments on retry)
        stage_info: Raw stage information from event log
        start_time: Stage start timestamp (seconds)
        tasks: List of TaskModel instances in this stage
        tasks_finalized: Whether all tasks have been added and sorted
        num_tasks: Total number of tasks in this stage
        submission_time: When the stage was submitted (seconds)
        completion_time: When the stage completed (seconds)
    """

    def __init__(self) -> None:
        self.id: int | None = None
        self.stage_name: str | None = None
        # By default, Stages will have a "Stage Attempt ID" of 0 the first time they are run.
        # If a Stage fails for some reason, it may be re-tried, and appear again in the eventlog with the
        # "Stage Attempt ID" incremented by 1. As such, we want to keep track of this so that we aren't putting
        # "stale" data onto a Stage when processing the eventlog lines (i.e. we don't want to set the `submission_time`
        # to be that of Attempt ID 0 when we've already encountered Attempt ID 1!)
        self.attempt_id: int | None = None
        self.stage_info: dict[str, Any] | None = None
        self.start_time: float = -1.0
        self.tasks: list[TaskModel] = []
        self.tasks_finalized: bool = False
        self.num_tasks: int = 0
        self.submission_time: float | None = None
        self.completion_time: float | None = None

    def average_task_runtime(self) -> float:
        return float(
            numpy.percentile([t.compute_time() for t in self.tasks], 50)
            if len(self.tasks) > 0
            else 0
        )

    def average_executor_deserialize_time(self) -> float:
        return float(
            sum([t.executor_deserialize_time for t in self.tasks])
            * 1.0
            / len(self.tasks)
            if len(self.tasks) > 0
            else 0
        )

    def average_result_serialization_time(self) -> float:
        return float(
            sum([t.result_serialization_time for t in self.tasks])
            * 1.0
            / len(self.tasks)
            if len(self.tasks) > 0
            else 0
        )

    def total_executor_deserialize_time(self) -> float:
        return float(sum([t.executor_deserialize_time for t in self.tasks]))

    def total_result_serialization_time(self) -> float:
        return float(sum([t.result_serialization_time for t in self.tasks]))

    def total_scheduler_delay(self) -> float:
        return float(sum([t.scheduler_delay for t in self.tasks]))

    def total_peak_execution_memory(self) -> float:
        return float(sum([t.peak_execution_memory for t in self.tasks]))

    def average_scheduler_delay(self) -> float:
        return float(
            sum([t.scheduler_delay for t in self.tasks]) * 1.0 / len(self.tasks)
            if len(self.tasks) > 0
            else 0
        )

    def average_gc_time(self) -> float:
        return float(
            sum([t.gc_time for t in self.tasks]) * 1.0 / len(self.tasks)
            if len(self.tasks) > 0
            else 0
        )

    def total_gc_time(self) -> float:
        return float(sum([t.gc_time for t in self.tasks]))

    def has_shuffle_read(self) -> bool:
        total_shuffle_read_bytes = sum(
            [t.remote_mb_read + t.local_mb_read for t in self.tasks if t.has_fetch]
        )
        return total_shuffle_read_bytes > 0

    def conservative_finish_time(self) -> float:
        # Subtract scheduler delay to account for asynchrony in the scheduler where sometimes tasks
        # aren't marked as finished until a few ms later.
        return float(max([(t.finish_time - t.scheduler_delay) for t in self.tasks]))

    def finish_time(self) -> float:
        return float(max([t.finish_time for t in self.tasks], default=0))

    def total_runtime(self) -> float:
        return float(sum([t.finish_time - t.start_time for t in self.tasks]))

    def total_fetch_wait(self) -> float:
        return float(sum([t.fetch_wait for t in self.tasks if t.has_fetch]))

    def total_remote_blocks_read(self) -> float:
        return float(sum([t.remote_blocks_read for t in self.tasks if t.has_fetch]))

    def total_remote_mb_read(self) -> float:
        return float(sum([t.remote_mb_read for t in self.tasks if t.has_fetch]))

    def total_write_time(self) -> float:
        return float(sum([t.shuffle_write_time for t in self.tasks]))

    def total_memory_bytes_spilled(self) -> float:
        return float(sum([t.memory_bytes_spilled for t in self.tasks]))

    def total_disk_bytes_spilled(self) -> float:
        return float(sum([t.disk_bytes_spilled for t in self.tasks]))

    def total_result_size(self) -> float:
        return float(sum([t.result_size for t in self.tasks]))

    def max_disk_bytes_spilled(self) -> float:
        return float(max([t.disk_bytes_spilled for t in self.tasks]))

    def max_memory_bytes_spilled(self) -> float:
        return float(max([t.memory_bytes_spilled for t in self.tasks]))

    def max_task_runtime(self) -> float:
        return float(
            numpy.percentile([t.compute_time() for t in self.tasks], 100)
            if len(self.tasks) > 0
            else 0
        )

    def max_peak_execution_memory(self) -> float:
        return float(max([t.peak_execution_memory for t in self.tasks]))

    def total_runtime_no_remote_shuffle_read(self) -> float:
        return float(sum([t.runtime_no_remote_shuffle_read() for t in self.tasks]))

    def total_time_fetching(self) -> float:
        return float(sum([t.total_time_fetching for t in self.tasks if t.has_fetch]))

    def input_mb(self) -> float:
        """Calculate total input data size for this stage.

        Aggregates input from both shuffle reads (remote + local) and
        direct input sources across all tasks.

        Returns:
            Total input size in MB

        Note:
            Only includes shuffle data if tasks have fetch operations
        """
        total_input_bytes = sum(
            [t.remote_mb_read + t.local_mb_read for t in self.tasks if t.has_fetch]
        )
        total_input_bytes += sum([t.input_mb for t in self.tasks])
        return float(total_input_bytes)

    def output_mb(self) -> float:
        """Calculate total output data size for this stage.

        Aggregates shuffle write sizes across all tasks.

        Returns:
            Total output size in MB

        Note:
            Currently only includes shuffle writes. HDFS and in-memory RDD
            output sizes are not yet tracked.
        """
        total_output_size = sum([t.shuffle_mb_written for t in self.tasks])
        return float(total_output_size)

    def add_event(self, data: dict[str, Any] | str, is_json: bool) -> None:
        # TODO(BACKLOG-013): Account for failed tasks in stage event parsing
        if not isinstance(data, dict):
            return  # Can't process non-dict data
        if "Task Metrics" in data:
            task = TaskModel(data, is_json)
            self.add_task(task)

    def add_task(self, task: TaskModel) -> None:
        """Add a task to this stage and update start time.

        Args:
            task: TaskModel instance to add

        Raises:
            RuntimeError: If tasks have already been finalized
        """
        if self.tasks_finalized:
            raise RuntimeError(
                "Attempted to add a task to a stage after that stage had already been finalized."
            )

        if self.start_time == -1:
            self.start_time = task.start_time
        else:
            self.start_time = min(self.start_time, task.start_time)

        self.tasks.append(task)

    def finalize_tasks(self) -> None:
        """Finalize all tasks by sorting them by finish time.

        Since tasks may be added to Stages out-of-order from the event log,
        this method should be called once all tasks have been added. It sorts
        tasks by finish_time to establish correct ordering for analysis.
        """
        self.tasks_finalized = True
        # When log lines are read in-order, SparkListenerTaskEnd lines will be present in the log ordered by their
        # finish_time (but, if multiple Tasks end at the same time, the order they appear in the eventlog is
        # non-deterministic). Since we receive the tasks out-of-order, we can just do a sort on them to put them
        # in their "correct" order
        self.tasks.sort(key=lambda t: t.finish_time)

    def get_features(self, stage_id: int) -> list[list[Any]]:
        """
        Return features from stage to write to csv
        """
        features = []
        for t in self.tasks:
            features.append(
                [
                    stage_id,
                    t.executor_id,
                    t.start_time,
                    t.finish_time,
                    t.executor,
                    t.executor_run_time,
                    t.executor_deserialize_time,
                    t.result_serialization_time,
                    t.gc_time,
                    t.network_bytes_transmitted_ps,
                    t.network_bytes_received_ps,
                    t.process_cpu_utilization,
                    t.total_cpu_utilization,
                    t.shuffle_write_time,
                    t.shuffle_mb_written,
                    t.input_read_time,
                    t.input_mb,
                    t.output_mb,
                    t.has_fetch,
                    t.data_local,
                    t.local_mb_read,
                    t.local_read_time,
                    t.total_time_fetching,
                    t.remote_mb_read,
                    t.scheduler_delay,
                ]
            )

        return features
