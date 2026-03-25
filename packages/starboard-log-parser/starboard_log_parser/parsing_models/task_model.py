import logging
from typing import Any


class TaskModel:
    """Model for a task within a stage.

    A task is the smallest unit of work in Spark, executed within a stage.
    This model parses and stores all metrics related to a single task execution,
    including timing, resource usage, shuffle operations, and executor information.

    Attributes:
        stage_id: ID of the parent stage
        task_id: Unique task identifier
        executor: Host name of the executor running this task
        executor_id: ID of the executor
        start_time: Task start timestamp (seconds)
        finish_time: Task finish timestamp (seconds)
        executor_run_time: Time spent in executor (seconds)
        executor_cpu_time: CPU time consumed (seconds)
        scheduler_delay: Delay in task scheduling (seconds)
        gc_time: Garbage collection time (seconds)
        shuffle_write_time: Time spent writing shuffle data (seconds)
        shuffle_mb_written: Amount of shuffle data written (MB)
        shuffle_mb_read: Amount of shuffle data read (MB)
        memory_bytes_spilled: Memory spilled to disk (MB)
        disk_bytes_spilled: Disk bytes spilled (MB)
        peak_execution_memory: Peak execution memory used (MB)
        locality: Data locality level (PROCESS_LOCAL, NODE_LOCAL, etc.)
        has_fetch: Whether this task fetches shuffle data
        data_local: Whether task ran locally with its input data
    """

    def __init__(self, data: dict[str, Any], is_json: bool) -> None:
        """Initialize a TaskModel from event log data.

        Args:
            data: Dictionary containing task metrics and metadata
            is_json: If True, parse from JSON event log format; if False, parse from job logger format

        Raises:
            KeyError: If required fields are missing from the data dict
        """
        self.logger = logging.getLogger(__name__)

        if is_json:
            self.initialize_from_json(data)
        else:
            self.initialize_from_job_logger(data)

        self.scheduler_delay = (
            self.finish_time
            - self.executor_run_time
            - self.executor_deserialize_time
            - self.result_serialization_time
            - self.start_time
        )
        # Should be set to true if this task is a straggler, and we know the cause of the
        # straggler behavior.
        self.straggler_behavior_explained = False

    def initialize_from_job_logger(self, data: dict[str, Any]) -> None:
        """
        Stub implementation for parsing job logger format.

        This method is not fully implemented. It initializes all attributes to default values
        to prevent AttributeError when this parsing path is used.

        Args:
            data: Dictionary containing job logger format data
        """
        self.logger.warning(
            "initialize_from_job_logger_not_implemented", extra={"data": data}
        )
        # Initialize all required attributes to default values
        self.stage_id = -1
        self.start_time = 0.0
        self.finish_time = 0.0
        self.task_id = -1
        self.executor = "unknown"
        self.killed = False
        self.speculative = False
        self.executor_run_time = 0.0
        self.executor_cpu_time = 0.0
        self.executor_deserialize_time = 0.0
        self.result_serialization_time = 0.0
        self.gc_time = 0.0
        self.memory_bytes_spilled = 0.0
        self.disk_bytes_spilled = 0.0
        self.result_size = 0.0
        self.peak_execution_memory = -1.0
        self.executor_id = "unknown"
        self.disk_utilization: dict[str, float] = {}
        self.network_bytes_transmitted_ps = 0.0
        self.network_bytes_received_ps = 0.0
        self.process_cpu_utilization = 0.0
        self.total_cpu_utilization = 0.0
        self.shuffle_write_time = 0.0
        self.shuffle_mb_written = 0.0
        self.locality = "UNKNOWN"
        self.input_read_time = 0.0
        self.input_read_method = "unknown"
        self.input_mb = 0.0
        self.output_mb = 0.0
        self.output_write_time = 0.0
        self.data_local = False
        self.has_fetch = False
        self.fetch_wait = 0.0
        self.local_blocks_read = 0
        self.remote_blocks_read = 0
        self.remote_mb_read = 0.0
        self.local_mb_read = 0.0
        self.local_read_time = 0.0
        self.total_time_fetching = 0.0
        self.jvm_heap_memory = 0
        self.jvm_offheap_memory = 0
        self.onheap_execution_memory = 0
        self.onheap_storage_memory = 0
        self.offheap_storage_memory = 0
        self.onheap_unified_memory = 0
        self.offheap_unified_memory = 0
        self.jvm_v_memory = 0
        self.jvm_rss_memory = 0
        self.python_v_memory = 0
        self.python_rss_memory = 0
        self.other_v_memory = 0
        self.other_rss_memory = 0
        self.shuffle_mb_read = 0.0

    def initialize_from_json(self, json_data: dict[str, Any]) -> None:
        task_info = json_data["Task Info"]
        task_metrics = json_data["Task Metrics"]
        task_executor_metrics = json_data.get("Task Executor Metrics")

        self.stage_id = json_data["Stage ID"]
        self.start_time = task_info["Launch Time"] / 1000  # [s]
        self.finish_time = task_info["Finish Time"] / 1000  # [s]
        self.task_id = task_info["Task ID"]
        self.executor = task_info["Host"]
        self.killed = task_info["Killed"]
        self.speculative = task_info["Speculative"]  # True if a duplicate task
        self.executor_run_time = task_metrics["Executor Run Time"] / 1000  # [ms --> s]
        self.executor_cpu_time = (
            task_metrics["Executor CPU Time"] / 1000000000
        )  # [ns --> s]
        self.executor_deserialize_time = (
            task_metrics["Executor Deserialize Time"] / 1000
        )  # [ms --> s]
        self.result_serialization_time = (
            task_metrics["Result Serialization Time"] / 1000
        )  # [ms --> s]#
        self.gc_time = task_metrics["JVM GC Time"] / 1000  # [s]
        self.memory_bytes_spilled = (
            task_metrics["Memory Bytes Spilled"] / 1000000
        )  # [MB]
        self.disk_bytes_spilled = task_metrics["Disk Bytes Spilled"] / 1000000  # [MB]
        self.result_size = task_metrics["Result Size"] / 1000000  # [MB]

        if "Peak Execution Memory" in task_metrics:
            self.peak_execution_memory = (
                task_metrics["Peak Execution Memory"] / 1000000
            )  # [MB]
        else:
            self.peak_execution_memory = -1

        self.executor_id = task_info["Executor ID"]

        # TODO(BACKLOG-018): Add utilization metrics to task JSON output
        self.disk_utilization = {}
        self.network_bytes_transmitted_ps = 0.0
        self.network_bytes_received_ps = 0
        self.process_cpu_utilization = 0
        self.total_cpu_utilization = 0

        self.shuffle_write_time = 0
        self.shuffle_mb_written = 0

        # Locality addition
        self.locality = task_info["Locality"]

        if shuffle_write_metrics := task_metrics.get("Shuffle Write Metrics"):
            # Convert to s (from nanoseconds).
            self.shuffle_write_time = (
                shuffle_write_metrics["Shuffle Write Time"] / 1.0e9
            )

            OPEN_TIME_KEY = "Shuffle Open Time"
            if OPEN_TIME_KEY in shuffle_write_metrics:
                shuffle_open_time = shuffle_write_metrics[OPEN_TIME_KEY] / 1.0e9
                self.logger.debug(
                    "shuffle_metric_parsed",
                    extra={
                        "metric_type": "open_time",
                        "value_seconds": shuffle_open_time,
                        "task_id": self.task_id,
                    },
                )
                self.shuffle_write_time += shuffle_open_time

            CLOSE_TIME_KEY = "Shuffle Close Time"
            if CLOSE_TIME_KEY in shuffle_write_metrics:
                shuffle_close_time = shuffle_write_metrics[CLOSE_TIME_KEY] / 1.0e9
                self.logger.debug(
                    "shuffle_metric_parsed",
                    extra={
                        "metric_type": "close_time",
                        "value_seconds": shuffle_close_time,
                        "task_id": self.task_id,
                    },
                )
                self.shuffle_write_time += shuffle_close_time

            self.shuffle_mb_written = (
                shuffle_write_metrics["Shuffle Bytes Written"] / 1048576.0
            )

        # TODO(BACKLOG-019): Warn on non-zero disk spill and reconcile with shuffle metrics

        INPUT_METRICS_KEY = "Input Metrics"
        self.input_read_time = 0
        self.input_read_method = "unknown"
        self.input_mb = 0

        if INPUT_METRICS_KEY in task_metrics:
            input_metrics = task_metrics[INPUT_METRICS_KEY]
            self.input_read_time = (
                0  # TODO(BACKLOG-020): Populate once Spark exposes input read time
            )
            # self.input_read_method = input_metrics["Data Read Method"]
            self.input_mb = input_metrics["Bytes Read"] / 1048576.0

        self.output_mb, self.output_write_time = (
            0.0,
            0.0,
        )  # TODO(BACKLOG-021): Populate once Spark exposes output write time
        if output_metrics := task_metrics.get("Output Metrics"):
            self.output_mb = float(int(output_metrics["Bytes Written"]) / 1048576.0)

        # False if the task was a map task that did not run locally with its input data.
        self.data_local = True
        self.has_fetch = True
        SHUFFLE_READ_METRICS_KEY = "Shuffle Read Metrics"
        if SHUFFLE_READ_METRICS_KEY not in task_metrics:
            self.data_local = (task_info["Locality"] == "NODE_LOCAL") or (
                task_info["Locality"] == "PROCESS_LOCAL"
            )
            self.has_fetch = False
            return

        shuffle_read_metrics = task_metrics[SHUFFLE_READ_METRICS_KEY]

        self.fetch_wait = shuffle_read_metrics["Fetch Wait Time"] / 1000  # [s]
        self.local_blocks_read = shuffle_read_metrics["Local Blocks Fetched"]
        self.remote_blocks_read = shuffle_read_metrics["Remote Blocks Fetched"]
        self.remote_mb_read = shuffle_read_metrics["Remote Bytes Read"] / 1048576.0

        # The local read time is not included in the fetch wait time: the task blocks
        # on reading data locally in the BlockFetcherIterator.initialize() method.
        self.local_mb_read = shuffle_read_metrics.get("Local Bytes Read", 0) / 1048576.0
        self.local_read_time = (
            shuffle_read_metrics.get("Local Read Time", 0) / 1000
        )  # [s]
        self.total_time_fetching = shuffle_read_metrics["Fetch Wait Time"] / 1000  # [s]

        if task_executor_metrics is not None:
            self.jvm_heap_memory = task_executor_metrics["JVMHeapMemory"]
            self.jvm_offheap_memory = task_executor_metrics["JVMOffHeapMemory"]
            self.onheap_execution_memory = task_executor_metrics[
                "OnHeapExecutionMemory"
            ]
            self.onheap_storage_memory = task_executor_metrics["OnHeapStorageMemory"]
            self.offheap_storage_memory = task_executor_metrics["OffHeapStorageMemory"]
            self.onheap_unified_memory = task_executor_metrics["OnHeapUnifiedMemory"]
            self.offheap_unified_memory = task_executor_metrics["OffHeapUnifiedMemory"]
            self.jvm_v_memory = task_executor_metrics["ProcessTreeJVMVMemory"]
            self.jvm_rss_memory = task_executor_metrics["ProcessTreeJVMRSSMemory"]
            self.python_v_memory = task_executor_metrics["ProcessTreePythonVMemory"]
            self.python_rss_memory = task_executor_metrics["ProcessTreePythonRSSMemory"]
            self.other_v_memory = task_executor_metrics["ProcessTreeOtherVMemory"]
            self.other_rss_memory = task_executor_metrics["ProcessTreeOtherRSSMemory"]
        else:
            self.jvm_heap_memory = 0
            self.jvm_offheap_memory = 0
            self.onheap_execution_memory = 0
            self.onheap_storage_memory = 0
            self.offheap_storage_memory = 0
            self.onheap_unified_memory = 0
            self.offheap_unified_memory = 0
            self.jvm_v_memory = 0
            self.jvm_rss_memory = 0
            self.python_v_memory = 0
            self.python_rss_memory = 0
            self.other_v_memory = 0
            self.other_rss_memory = 0

    def input_size_mb(self) -> float:
        """Calculate total input data size for this task.

        Returns:
            Total input size in MB, either from shuffle read (remote + local) or direct input
        """
        if self.has_fetch:
            return self.remote_mb_read + self.local_mb_read
        else:
            return self.input_mb

    def compute_time_without_gc(self) -> float:
        """Calculate task compute time excluding garbage collection.

        This represents pure computation time by subtracting all overhead:
        scheduler delay, GC time, shuffle operations, and I/O time.

        Assumes shuffle writes don't get pipelined with task execution.

        Returns:
            Compute time in seconds, excluding GC time
        """
        compute_time = (
            self.runtime()
            - self.scheduler_delay
            - self.gc_time
            - self.shuffle_write_time
            - self.input_read_time
            - self.output_write_time
        )
        if self.has_fetch:
            # Subtract off of the time to read local data (which typically comes from disk) because
            # this read happens before any of the computation starts.
            compute_time = compute_time - self.fetch_wait - self.local_read_time
        return compute_time

    def compute_time(self) -> float:
        """Calculate task compute time including garbage collection.

        The reason we include GC time here is that garbage collection may happen
        during fetch wait and other operations, making it part of effective compute time.

        Returns:
            Total compute time in seconds, including GC time
        """
        return self.compute_time_without_gc() + self.gc_time

    def task_compute_time(self) -> float:
        """Calculate pure task compute time excluding all overhead.

        This provides the finest-grained compute time by excluding:
        - Garbage collection
        - Executor deserialization
        - Result serialization
        - Scheduler delay
        - All I/O operations

        Returns:
            Pure task compute time in seconds
        """
        task_compute_time = (
            self.compute_time_without_gc()
            - self.executor_deserialize_time
            - self.result_serialization_time
        )

        return task_compute_time

    def runtime(self) -> float:
        """Calculate total task runtime from start to finish.

        Returns:
            Total elapsed time in seconds
        """
        return self.finish_time - self.start_time

    def runtime_no_input(self) -> float:
        new_finish_time = self.finish_time - self.input_read_time
        return new_finish_time - self.start_time

    def runtime_no_output(self) -> float:
        new_finish_time = self.finish_time - self.output_write_time
        return new_finish_time - self.start_time

    def runtime_no_input_or_output(self) -> float:
        new_finish_time = (
            self.finish_time - self.input_read_time - self.output_write_time
        )
        return new_finish_time - self.start_time

    def runtime_no_shuffle_write(self) -> float:
        return self.finish_time - self.shuffle_write_time - self.start_time

    def runtime_no_shuffle_read(self) -> float:
        if self.has_fetch:
            return (
                self.finish_time
                - self.fetch_wait
                - self.local_read_time
                - self.start_time
            )
        else:
            return self.runtime()

    def runtime_no_remote_shuffle_read(self) -> float:
        if self.has_fetch:
            return self.finish_time - self.fetch_wait - self.start_time
        else:
            return self.runtime()

    def runtime_no_network(self) -> float:
        runtime_no_in_or_out = self.runtime_no_output()
        if not self.data_local:
            runtime_no_in_or_out -= self.input_read_time
        if self.has_fetch:
            return runtime_no_in_or_out - self.fetch_wait
        else:
            return runtime_no_in_or_out
