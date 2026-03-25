from __future__ import annotations

import collections
import logging
from typing import Any

import numpy

from starboard_log_parser.parsing_models.stage_model import StageModel
from starboard_log_parser.parsing_models.task_model import TaskModel


class JobModel:
    """Model for a Spark job within an application.

    A job is triggered by an action (like collect, save, count) and consists of
    one or more stages. This model tracks job-level metrics and aggregates stage
    information.

    Modified from trace analyzer from Kay Ousterhout: https://github.com/kayousterhout/trace-analysis

    Attributes:
        stages: Dictionary mapping stage IDs to StageModel instances
        overlap: Amount of time (seconds) stages ran concurrently
        stages_to_combine: Set of stage IDs that ran concurrently
        submission_time: When the job was submitted (seconds)
        completion_time: When the job completed (seconds)
        result: Job completion result (e.g., "JobSucceeded", "JobFailed")
    """

    def __init__(self) -> None:
        self.logger: logging.Logger = logging.getLogger(__name__)
        # Map of stage IDs to Stages.
        self.stages: dict[int, StageModel] = collections.defaultdict(StageModel)
        self.overlap: float = 0.0
        self.stages_to_combine: set[int] = set()
        self.submission_time: float | None = None
        self.completion_time: float | None = None
        self.result: str | None = None

    def add_event(self, data: dict[str, Any] | str, is_json: bool) -> None:
        if is_json:
            if not isinstance(data, dict):
                self.logger.error(
                    "Expected dict for JSON data", extra={"data_type": type(data)}
                )
                return
            event_type = data["Event"]
            if event_type == "SparkListenerTaskEnd":
                stage_id = data["Stage ID"]
                self.stages[stage_id].add_event(data, True)
        else:
            if not isinstance(data, str):
                self.logger.error(
                    "Expected str for non-JSON data", extra={"data_type": type(data)}
                )
                return
            STAGE_ID_MARKER = "STAGE_ID="
            stage_id_loc = data.find(STAGE_ID_MARKER)
            if stage_id_loc != -1:
                stage_id_and_suffix = data[stage_id_loc + len(STAGE_ID_MARKER) :]
                stage_id_str = stage_id_and_suffix[: stage_id_and_suffix.find(" ")]
                stage_id = int(stage_id_str)
                self.stages[stage_id].add_event(data, False)

    def initialize_job(self) -> None:
        """Initialize job-level metrics after all events have been added.

        Performs post-processing:
        1. Removes empty stages (stages with no tasks)
        2. Calculates stage overlap time (concurrent execution)
        3. Identifies stages that ran concurrently

        This method should be called once all stage and task events have been processed.
        """
        # Drop empty stages.
        stages_to_drop = []
        for id, s in self.stages.items():
            if len(s.tasks) == 0:
                stages_to_drop.append(id)
        for id in stages_to_drop:
            del self.stages[id]

        # Compute the amount of overlapped time between stages
        # (there should just be two stages, at the beginning, that overlap and run concurrently).
        # This computation assumes that not more than two stages overlap.
        start_and_finish_times = [
            (id, s.start_time, s.conservative_finish_time())
            for id, s in self.stages.items()
        ]
        start_and_finish_times.sort(key=lambda x: x[1])
        self.overlap = 0.0
        old_end = 0.0
        previous_id: int | None = None
        self.stages_to_combine = set()
        for id, start, finish in start_and_finish_times:
            if start < old_end:
                self.overlap += old_end - start
                self.stages_to_combine.add(id)
                if previous_id is not None:
                    self.stages_to_combine.add(previous_id)
                old_end = max(old_end, finish)
            if finish > old_end:
                old_end = finish
                previous_id = id

        # self.combined_stages_concurrency = -1
        # if len(self.stages_to_combine) > 0:
        #     tasks_for_combined_stages = []
        #     for stage_id in self.stages_to_combine:
        #         tasks_for_combined_stages.extend(self.stages[stage_id].tasks)
        #         self.combined_stages_concurrency = concurrency.get_max_concurrency(tasks_for_combined_stages)

    def all_tasks(self) -> list[TaskModel]:
        """Retrieve all tasks across all stages in this job.

        Returns:
            List of TaskModel instances from all stages, flattened into a single list
        """
        return [task for stage in self.stages.values() for task in stage.tasks]

    def write_features(self, filepath: str) -> None:
        """Outputs a csv file with features of each task"""
        with open(f"{filepath}.csv", "w") as f:
            f.write(
                "stage_id, executor_id, start_time, finish_time, executor, executor_run_time, executor_deserialize_time, result_serialization_time, gc_time, network_bytes_transmitted_ps, network_bytes_received_ps, process_cpu_utilization, total_cpu_utilization, shuffle_write_time, shuffle_mb_written, input_read_time, input_mb, output_mb, has_fetch, data_local, local_mb_read, local_read_time, total_time_fetching, remote_mb_read, scheduler_delay\n"
            )
            for id, stage in self.stages.items():
                numpy.savetxt(f, stage.get_features(id), delimiter=",", fmt="%s")
