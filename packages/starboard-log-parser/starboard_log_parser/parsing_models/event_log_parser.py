# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
from __future__ import annotations

import collections
import logging
from collections.abc import Iterator
from typing import Any

import numpy

from starboard_log_parser.parsing_models.dag_model import DagModel
from starboard_log_parser.parsing_models.exceptions import (
    LogSubmissionException,
    UrgentEventValidationException,
)
from starboard_log_parser.parsing_models.executor_model import (
    ExecutorModel,
)
from starboard_log_parser.parsing_models.job_model import JobModel
from starboard_log_parser.parsing_models.stage_model import StageModel
from starboard_log_parser.parsing_models.task_model import TaskModel
from starboard_log_parser.validators.streaming_validator import (
    StreamingValidator,
)

# Maximum recursion depth for parsing nested dictionaries
# Prevents stack overflow on malformed or malicious log data
MAX_RECURSION_DEPTH = 50

logger = logging.getLogger(__name__)


class ApplicationModel:
    """Model for a complete Spark application.

    A Spark application consists of one or more jobs, which consist of one or more
    stages, which consist of one or more tasks. This model parses event logs and
    builds a complete hierarchy of execution metrics.

    Using parts of the trace analyzer from Kay Ousterhout: https://github.com/kayousterhout/trace-analysis

    Attributes:
        dag: DAG model representing stage dependencies
        jobs: Dictionary mapping job IDs to JobModel instances
        stages: Dictionary mapping stage IDs to StageModel instances
        tasks: List of all TaskModel instances
        sql: Dictionary of SQL execution metadata
        accum_metrics: Accumulated metrics from broadcast operations
        executors: Dictionary mapping executor IDs to ExecutorModel instances
        jobs_for_stage: Mapping of stage IDs to job IDs
        num_executors: Current number of active executors
        max_executors: Maximum number of concurrent executors
        start_time: Application start timestamp (seconds)
        finish_time: Application finish timestamp (seconds)
        cloud_platform: Cloud platform (databricks, emr, etc.)
        cloud_provider: Cloud provider (aws, azure, gcp)
        cluster_id: Cloud cluster identifier
        spark_version: Spark version string
        spark_metadata: Additional Spark configuration metadata
    """

    def __init__(
        self,
        log_lines: Iterator[dict[str, Any]],
        stdoutpath: str | None = None,
        debug: bool = False,
        enable_streaming_validation: bool = False,
    ) -> None:  # noqa: C901
        """Initialize ApplicationModel by parsing Spark event log.

        Args:
            log_lines: Iterator yielding parsed JSON event log lines as dicts
            stdoutpath: Optional path to stdout log for additional broadcast info
            debug: If True, skip validation checks that would normally raise exceptions
            enable_streaming_validation: If True, validate events during parsing for
                                        fail-fast error detection (60x faster)

        Raises:
            UrgentEventValidationException: If critical event data is missing
            LogSubmissionException: If rollover logs are incomplete
        """
        # set default parameters
        self.dag: DagModel = DagModel()
        self.jobs: dict[int, JobModel] = collections.defaultdict(JobModel)
        self.stages: dict[int, StageModel] = collections.defaultdict(StageModel)
        self.tasks: list[TaskModel] = []
        self.sql: dict[int, dict[str, Any]] = collections.defaultdict(dict)
        self.accum_metrics: dict[int, dict[str, Any]] = collections.defaultdict(dict)
        self.executors: dict[str, ExecutorModel] = collections.defaultdict(
            ExecutorModel
        )
        self.jobs_for_stage: dict[int, list[int]] = collections.defaultdict(list)
        self.num_executors: int = 0
        self.max_executors: int = 0
        self.executorRemovedEarly: bool = False
        self.parallelism: int | None = None
        self.memory_per_executor: float | None = None
        self.cores_per_executor: int | None = None
        self.num_instances: int | None = None
        self.start_time: float | None = None
        self.finish_time: float | None = None
        self.platformIdentified: bool = False
        self.platform: str | None = None
        self.spark_metadata: dict[str, Any] = {}
        self.stdoutpath: str | None = stdoutpath

        self.shuffle_partitions: int = 200

        self.cloud_platform: str | None = None
        self.cloud_provider: str | None = None
        self.cluster_id: str | None = None
        self.spark_version: str | None = None
        self.emr_version_tag: str | None = None
        self.executors_per_instance: int = 0

        # Initialize streaming validator if enabled
        validator: StreamingValidator | None = None
        if enable_streaming_validation:
            validator = StreamingValidator(strict=not debug)
            logger.debug("Streaming validation enabled for fail-fast error detection")

        hosts: set[str] = set()
        rollover_log_numbers_seen: set[int] = set()

        line_number = 0
        for json_data in log_lines:
            line_number += 1

            # Validate event before processing if streaming validation enabled
            if validator:
                try:
                    validator.validate_event(json_data, line_number=line_number)
                except UrgentEventValidationException as e:
                    logger.error(
                        f"Streaming validation failed at line {line_number}: {e.error_message}"
                    )
                    raise
            event_type = json_data.get("Event")
            # When clients upload archives to us, it is possible that we get valid JSON files in that archive that look
            # like eventlog log lines, but are actually not
            if not event_type:
                continue

            if event_type == "SparkListenerLogStart":
                # spark_version_dict = {"spark_version": json_data["Spark Version"]}
                self.spark_version = json_data["Spark Version"]
                self.spark_metadata = {**self.spark_metadata}

            elif event_type == "DBCEventLoggingListenerMetadata":
                rollover_log_numbers_seen.add(json_data["Rollover Number"])
                continue

            elif event_type == "SparkListenerJobStart":
                job_id = json_data["Job ID"]
                self.jobs[job_id].submission_time = json_data["Submission Time"] / 1000
                # Avoid using "Stage Infos" here, which was added in 1.2.0.
                stage_ids = json_data["Stage IDs"]

                for stage_id in stage_ids:
                    self.jobs_for_stage[stage_id].append(job_id)

            elif event_type == "SparkListenerJobEnd":
                job_id = json_data["Job ID"]
                self.jobs[job_id].completion_time = json_data["Completion Time"] / 1000
                self.jobs[job_id].result = json_data["Job Result"]["Result"]

            elif event_type == "SparkListenerTaskEnd":
                if "Task Metrics" in json_data:
                    task = TaskModel(json_data, True)
                    self.tasks.append(task)

            elif event_type == "SparkListenerStageSubmitted":
                stage_info = json_data["Stage Info"]

                if "Submission Time" not in stage_info:
                    # PROD-426 Submission Time key may be missing from stages that
                    # don't get submitted. There is usually a StageCompleted event
                    # shortly after. This may happen when stages fail
                    continue

                stage_id = stage_info["Stage ID"]
                attempt_id = stage_info["Stage Attempt ID"]
                stage = self.stages[stage_id]
                # Note - see StageModel.attempt_id for a description of why this logic is here.
                if stage.attempt_id is None or attempt_id >= stage.attempt_id:
                    stage.id = stage_id
                    stage.attempt_id = attempt_id
                    stage.stage_info = stage_info
                    stage.stage_name = stage_info["Stage Name"]
                    stage.submission_time = stage_info["Submission Time"] / 1000
                    stage.num_tasks = stage_info["Number of Tasks"]

            elif event_type == "SparkListenerStageCompleted":
                # stages may not be executed exclusively from one job
                stage_info = json_data["Stage Info"]
                stage_id = stage_info["Stage ID"]
                stage_completion_time = stage_info["Completion Time"] / 1000

                stage = self.stages[stage_id]
                attempt_id = stage_info["Stage Attempt ID"]
                # Note - see StageModel.attempt_id for a description of why this logic is here.
                if stage.attempt_id is None or attempt_id >= stage.attempt_id:
                    stage.completion_time = stage_completion_time
                    self.maybe_set_new_finish_time(stage_completion_time)

            elif event_type == "SparkListenerEnvironmentUpdate":
                spark_properties = json_data["Spark Properties"]

                # This if is specifically for databricks logs
                if spark_version := spark_properties.get(
                    "spark.databricks.clusterUsageTags.sparkVersion"
                ):
                    self.cloud_platform = "databricks"
                    self.spark_version = spark_version
                    self.cluster_id = spark_properties[
                        "spark.databricks.clusterUsageTags.clusterId"
                    ]
                    self.cloud_provider = spark_properties[
                        "spark.databricks.clusterUsageTags.cloudProvider"
                    ].lower()
                elif cluster_id := json_data.get("System Properties", {}).get(
                    "EMR_CLUSTER_ID"
                ):
                    self.cloud_platform = "emr"
                    self.cloud_provider = "aws"
                    self.cluster_id = cluster_id
                    self.emr_version_tag = json_data["System Properties"][
                        "EMR_RELEASE_LABEL"
                    ]

                self.spark_metadata = {**self.spark_metadata, **spark_properties}

            elif event_type == "SparkListenerExecutorAdded":
                executor_id = json_data["Executor ID"]
                executor_info = json_data["Executor Info"]

                executor = self.executors[executor_id]
                executor.id = executor_id
                executor.start_time = json_data["Timestamp"]
                executor.host = executor_info["Host"]
                executor.cores = int(executor_info["Total Cores"])

                hosts.add(executor.host)

                self.cores_per_executor = executor.cores
                self.num_executors += 1
                self.max_executors = max(self.num_executors, self.max_executors)

            # So far logs I've looked at only explicitly remove Executors when there is a problem like
            # lost worker. Use this to flag premature executor removal
            elif event_type == "SparkListenerExecutorRemoved":
                self.executorRemovedEarly = True
                self.num_executors = self.num_executors - 1

                executor = self.executors[json_data["Executor ID"]]
                executor.end_time = json_data["Timestamp"]
                executor.removed_reason = json_data["Removed Reason"]

            elif (
                event_type
                == "org.apache.spark.sql.execution.ui.SparkListenerSQLExecutionEnd"
            ):
                sql_id = json_data["executionId"]
                end_time = json_data["time"] / 1000
                self.sql[sql_id]["end_time"] = end_time
                self.maybe_set_new_finish_time(end_time)

            elif event_type == "SparkListenerApplicationStart":
                self.start_time = json_data["Timestamp"] / 1000
                self.app_name = json_data["App Name"]

            elif event_type == "SparkListenerApplicationEnd":
                self.finish_time = json_data["Timestamp"] / 1000

            elif (
                event_type
                == "org.apache.spark.sql.execution.ui.SparkListenerSQLExecutionStart"
            ):
                sql_id = json_data["executionId"]
                self.sql[sql_id]["start_time"] = json_data["time"] / 1000
                self.sql[sql_id]["description"] = json_data["description"]
                self.parse_all_accum_metrics(json_data)

            elif (
                event_type
                == "org.apache.spark.sql.execution.ui.SparkListenerSQLAdaptiveExecutionUpdate"
            ):
                self.parse_all_accum_metrics(json_data)

            # populate accumulated metrics with updated values
            elif (
                event_type
                == "org.apache.spark.sql.execution.ui.SparkListenerDriverAccumUpdates"
            ):
                sql_id = json_data["executionId"]
                for metric in json_data["accumUpdates"]:
                    accum_id = metric[0]
                    self.accum_metrics[accum_id]["value"] = metric[1]
                    self.accum_metrics[accum_id]["sql_id"] = sql_id

            elif (
                event_type
                == "org.apache.spark.sql.execution.ui.SparkListenerEffectiveSQLConf"
            ):
                #########################
                # Note to predictor team:
                # This is spark parameters for each sql execution id
                # Need to decide how we want to deal with this.
                # Right now the last one is saved, but need to figure out if we want to deal with each execution id's parameters
                #########################
                self.spark_metadata = {
                    **self.spark_metadata,
                    **json_data["effectiveSQLConf"],
                }

            # Add DAG components
            # using stage submitted to preserve order stages are submitted
            if event_type in ["SparkListenerJobStart", "SparkListenerStageSubmitted"]:
                self.dag.parse_dag(json_data)

        if not self.cloud_platform:
            # Ideally, we would be able to determine the platform/provider reliably from our Spark logs. However, EMR
            # logs may not necessarily contain an SparkListenerEnvironmentUpdate event, so if we don't encounter one,
            # we will assume this is an EMR job running on AWS
            self.cloud_platform = "emr"
            self.cloud_provider = "aws"

        self.num_instances = len(hosts)
        if self.num_instances > 0:
            self.executors_per_instance = numpy.ceil(
                self.num_executors / self.num_instances
            )
        else:
            self.executors_per_instance = 0

        if rollover_log_numbers_seen:
            # When we encounter rollover logs, we expect the final set to be a sequence of numbers 0 - N, where N is
            # the maximum "Rollover Number" that we saw while processing the eventlog files. If one of those is missing,
            # we know that the archive is incomplete and missing some files
            max_rollover = max(rollover_log_numbers_seen)
            expected_rollover_log_numbers_seen = set(range(max_rollover + 1))
            if expected_rollover_log_numbers_seen.difference(rollover_log_numbers_seen):
                raise LogSubmissionException(
                    error_message=(
                        "Rollover logs were detected, but there were fewer than expected.\n"
                        + f"Expected to receive rollover numbers: {', '.join(str(n) for n in expected_rollover_log_numbers_seen)}, "
                        + f"but instead received: {', '.join(str(n) for n in sorted(rollover_log_numbers_seen))} "
                    )
                )

        # Finalize streaming validation if enabled
        if validator:
            try:
                validator.finalize()
                logger.debug(
                    f"Streaming validation complete: {validator.state.event_count} events validated"
                )

                # Log validation summary
                summary = validator.get_summary()
                logger.debug(f"Validation summary: {summary}")
            except UrgentEventValidationException as e:
                logger.error(
                    f"Streaming validation failed during finalization: {e.error_message}"
                )
                raise

        for task in self.tasks:
            stage_id = task.stage_id
            stage = self.stages[stage_id]
            stage.add_task(task)

        for stage_id, stage in self.stages.items():
            if stage.submission_time is None:
                raise UrgentEventValidationException(
                    missing_event=f"Stage {stage_id} Submit"
                )

            job_ids_for_stage = self.jobs_for_stage.get(stage_id)
            if (not job_ids_for_stage) and (not debug):
                # If this stage is not associated with any particular job, that likely means we are missing some data
                raise UrgentEventValidationException(
                    missing_event=f"Job Start for Stage {stage_id}"
                )

            if job_ids_for_stage:
                for job_id in job_ids_for_stage:
                    self.jobs[job_id].stages[stage_id] = stage

            stage.finalize_tasks()

        for _, job in self.jobs.items():
            job.initialize_job()

        self.dag.decipher_dag()
        self.dag.add_broadcast_dependencies(self.stdoutpath)

    def maybe_set_new_finish_time(self, new_finish_time: int) -> None:
        """Update application finish time if the new time is later.

        As we read log lines, we track the latest finish_time seen. This may come
        from various events (stage completion, SQL execution end, application end)
        since no single event is guaranteed to be present.

        Args:
            new_finish_time: Candidate finish time in seconds
        """
        if not self.finish_time or new_finish_time > self.finish_time:
            self.finish_time = new_finish_time

    def plot_task_runtime_distribution(self) -> bool:
        """
        For each stage, plot task runtime distribution and calculate how closely it follows normal distribution

        Returns true if normal distribution
        """
        # TODO(BACKLOG-017): Implement task runtime distribution plotting and normality test
        return False

    # Accumulated metrics including broadcast data
    def parse_all_accum_metrics(
        self, accum_data: dict[str, Any], depth: int = 0
    ) -> None:
        """
        Parse accumulated metrics recursively with depth limit.

        Args:
            accum_data: Dictionary containing accumulated metrics
            depth: Current recursion depth (default: 0)

        Raises:
            ValueError: If maximum recursion depth exceeded
        """
        if depth > MAX_RECURSION_DEPTH:
            raise ValueError(
                f"Maximum recursion depth ({MAX_RECURSION_DEPTH}) exceeded while "
                f"parsing accumulated metrics. This may indicate malformed or malicious log data."
            )

        # Search recursively for accumulated metrics (can be many layers deep)
        for k, v in accum_data.items():
            if k == "metrics":
                for metric in v:
                    accum_id = metric["accumulatorId"]
                    self.accum_metrics[accum_id]["name"] = metric["name"]
                    self.accum_metrics[accum_id]["metric_type"] = metric["metricType"]
            if isinstance(v, dict):
                self.parse_all_accum_metrics(v, depth=depth + 1)
            if isinstance(v, list):
                for d in v:
                    if isinstance(d, dict):
                        self.parse_all_accum_metrics(d, depth=depth + 1)
