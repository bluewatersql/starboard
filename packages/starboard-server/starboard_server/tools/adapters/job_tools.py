# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Reasoning interface for job tools.

This module provides LLM-facing tools for job operations.
Uses domain logic directly - service layer was inlined.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starboard_core.domain.models.job import (
    AnalysisMode,
    JobHistoryResult,
    JobResolutionInput,
    JobResolutionResult,
    TaskDependencyResult,
)

from starboard_server.infra.observability.logging import get_logger
from starboard_server.services.context.transforms import (
    get_job_metadata,
    search_jobs_by_name,
)
from starboard_server.tools.adapters.base import BaseToolAdapter
from starboard_server.tools.domain.job.analyzer import JobAnalyzer
from starboard_server.tools.domain.job.resolver import JobResolver
from starboard_server.tools.utils import extract_job_clusters

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class JobTools(BaseToolAdapter):
    """Reasoning interface for job operations.

    Clean interface optimized for LLM reasoning. Uses SharedContextProvider
    directly with transforms and domain logic - service layer was inlined.

    Architecture:
        JobTools → JobResolver/JobAnalyzer (domain) + transforms

    Example:
        >>> tools = JobTools.from_provider(provider, events=events)
        >>> result = await tools.resolve_job("my-job")
    """

    async def _get_job_by_name(self, job_name: str) -> tuple[str | None, list[dict]]:
        """Get job ID by name using efficient search.

        Uses SDK's name filter for exact match (server-side), falls back to
        partial match if no exact match found.

        Args:
            job_name: Job name to search for.

        Returns:
            Tuple of (job_id, partial_matches):
            - job_id: Job ID if exactly one match found, None otherwise
            - partial_matches: List of partial matches if multiple found
        """
        if self.provider is None:
            raise RuntimeError("SharedContextProvider not initialized")

        result = await search_jobs_by_name(
            self.provider,
            job_name=job_name,
            exact_match=True,
            limit=5,
        )

        if result is None:
            logger.debug("Error searching for job name: {job_name}")
            return None, []

        # Check for exact match
        if result.get("exact_match") and result.get("job_id"):
            job_id = result["job_id"]
            logger.debug("Exact match found for job_name '{job_name}': {job_id}")
            return job_id, []

        # Multiple partial matches found
        matches = result.get("matches", [])
        if matches:
            logger.debug(
                f"Found {len(matches)} partial matches for job_name '{job_name}'"
            )
            return None, matches

        logger.debug("No job found with name: {job_name}")
        return None, []

    async def resolve_job(
        self,
        target: str,
        classification: dict | None = None,
    ) -> dict[str, Any]:
        """Resolve job from input.

        Args:
            target: Job ID, job name, or source code.
            classification: Optional LLM classification hints.

        Returns:
            Dict with resolution result.

        Raises:
            ValueError: If job cannot be resolved or multiple matches found.
        """
        self.events.emit_info(
            source="job_tools",
            message="Resolving job",
            phase="execution",
        )

        input_data = JobResolutionInput(
            target=target,
            classification=classification,
        )

        # Call domain logic directly
        result = JobResolver.resolve_job(input_data)

        # Enrich with API data if needed (job name -> job ID)
        if result.analysis_mode == AnalysisMode.JOB and result.job_name:
            job_id, partial_matches = await self._get_job_by_name(result.job_name)

            if job_id:
                # Exact match found
                result = JobResolutionResult(
                    job_id=job_id,
                    job_name=result.job_name,
                    source_code=result.source_code,
                    analysis_mode=result.analysis_mode,
                )
            elif partial_matches:
                # Multiple partial matches - raise with suggestions
                match_names = [
                    f"- {m.get('settings', {}).get('name', 'unknown')} (ID: {m.get('job_id')})"
                    for m in partial_matches[:5]
                ]
                raise ValueError(
                    f"Multiple jobs match '{result.job_name}'. "
                    f"Please specify the exact job name or ID:\n"
                    + "\n".join(match_names)
                )
            else:
                # No matches at all
                result = JobResolutionResult(
                    job_id=None,
                    job_name=result.job_name,
                    source_code=result.source_code,
                    analysis_mode=result.analysis_mode,
                )

        # Validate we got a job ID for job analysis mode
        if result.analysis_mode == AnalysisMode.JOB and not result.job_id:
            raise ValueError(f"No valid job ID found for: {input_data.target}")

        return {
            "job_id": result.job_id,
            "job_name": result.job_name,
            "source_code": result.source_code,
            "analysis_mode": result.analysis_mode.value,
        }

    async def analyze_job_history(
        self, job_id: str, lookback_days: int = 7
    ) -> dict[str, Any]:
        """Analyze job run history with cluster metadata.

        Note: This method does NOT fetch Spark logs. Use the separate
        get_spark_logs tool to get Spark UI logs. This separation allows:
        - Clear visibility into Spark log availability
        - LLM control over when/if to fetch logs
        - Multi-run log analysis when needed
        - Proper handling of serverless clusters (no logs available)

        Args:
            job_id: Job ID to analyze.
            lookback_days: Days of history to analyze (default: 7).

        Returns:
            Dict with analysis result including cluster_id for Spark log lookup.

        Raises:
            ValueError: If job metadata cannot be fetched.
        """
        self.events.emit_info(
            source="job_tools",
            message=f"Analyzing job history for job: {job_id}",
            phase="execution",
        )

        # Map lookback_days to max_runs (cap at 25 to avoid exceeding API limits)
        max_runs = min(max(lookback_days, 5), 25)

        if self.provider is None:
            raise RuntimeError("SharedContextProvider not initialized")

        # Use transforms helper for data access
        job_metadata = await get_job_metadata(self.provider, job_id, max_runs)

        if not job_metadata:
            raise ValueError(f"Failed to fetch runs for job_id: {job_id}")

        # Call domain logic directly
        runs = job_metadata.get("runs", [])
        runtime_meta = job_metadata.get("runtime_meta", {})

        result: JobHistoryResult = JobAnalyzer.analyze_job_history(runs, runtime_meta)

        # Extract cluster information for reference (LLM can use for get_spark_logs)
        cluster_id = None
        job_clusters = extract_job_clusters(runs)
        if job_clusters:
            # Most recent cluster (job_clusters sorted newest first)
            cluster_id = job_clusters[0]["cluster_id"]

        logger.debug(
            f"Analyzed {result.total_runs} runs for job_id {job_id}: "
            f"{result.success_rate:.1%} success rate, cluster_id={cluster_id}"
        )

        return {
            "total_runs": result.total_runs,
            "success_rate": result.success_rate,
            "avg_duration_seconds": result.avg_duration_seconds,
            "has_failures": result.has_failures,
            "spark_logs": None,  # Fetched separately via get_spark_logs tool
            "cluster_id": cluster_id,
        }

    async def analyze_task_dependencies(
        self, task_definitions: list[dict]
    ) -> dict[str, Any]:
        """Analyze task dependencies.

        Args:
            task_definitions: List of task definitions.

        Returns:
            Dict with dependency analysis.
        """
        self.events.emit_info(
            source="job_tools",
            message="Analyzing task dependencies",
            phase="execution",
        )

        if not task_definitions:
            logger.warning("No task definitions found for dependency analysis")
            return {"dependencies": {}, "critical_path": []}

        # Call domain logic directly
        result: TaskDependencyResult = JobAnalyzer.analyze_task_dependencies(
            task_definitions
        )

        return {
            "dependencies": result.dependencies,
            "critical_path": result.critical_path,
        }

    async def get_job_config(self, job_id: str) -> dict[str, Any]:
        """Get job configuration and task definitions.

        Args:
            job_id: Job ID to get config for.

        Returns:
            Dict with job_config, task_definitions, job_clusters.

        Raises:
            ValueError: If job metadata cannot be fetched.

        Example:
            >>> result = await tools.get_job_config("123456")
            >>> # Returns: {"job_config": {...}, "task_definitions": [...], "job_clusters": {...}}
        """
        logger.debug("Fetching job configuration for job: {job_id}")

        if self.provider is None:
            raise RuntimeError("SharedContextProvider not initialized")

        # Fetch job metadata using transforms helper
        job_metadata = await get_job_metadata(self.provider, job_id, max_runs=1)

        if not job_metadata:
            raise ValueError(f"Failed to fetch metadata for job_id: {job_id}")

        # Extract task definitions
        tasks = job_metadata.get("parsed_settings", {}).get("job", {}).get("tasks", [])

        # Extract cluster information
        job_clusters = extract_job_clusters(job_metadata.get("runs", []))

        logger.debug("Fetched config for job_id {job_id}: {len(tasks)} tasks")

        return {
            "job_config": job_metadata,
            "task_definitions": tasks,
            "job_clusters": job_clusters,
        }

    async def get_run_output(self, run_id: str) -> dict[str, Any]:
        """Get output and logs for a job run including all task-level outputs.

        This is a key diagnostic tool for understanding job failures.
        Iterates through each task in the run to collect detailed diagnostics
        including per-task errors, logs, and notebook outputs.

        Args:
            run_id: Databricks job run ID (string or integer).

        Returns:
            Dict with comprehensive run output including:
            - run_id: Run identifier
            - state: Run state dict (life_cycle_state, result_state, state_message)
            - job_id: Parent job ID
            - tasks: List of task outputs with:
              - task_key: Task identifier
              - run_id: Task-level run ID
              - state: Task state
              - error: Task error message if failed
              - output: Full task output (notebook_output, logs, etc.)
              - logs: Task logs if available
              - notebook_result: Notebook result if applicable
            - summary: Aggregated error messages from all failed tasks
            - error: Top-level run error if present

        Example:
            >>> result = await tools.get_run_output("123456789")
            >>> if result.get("summary"):
            ...     print(f"Failed tasks:\\n{result['summary']}")
            >>> for task in result.get("tasks", []):
            ...     if task.get("error"):
            ...         print(f"Task {task['task_key']}: {task['error']}")
        """
        self.events.emit_info(
            source="job_tools",
            message=f"Fetching run output for run: {run_id}",
            phase="execution",
        )

        run_id_int = int(run_id)

        if self.provider is None:
            raise RuntimeError("SharedContextProvider not initialized")

        # Get comprehensive run output including all task-level outputs
        # The service layer now iterates through tasks and fetches each task's output
        run_output = await self.provider.client.get_run_output(run_id_int)

        # Extract failed tasks for quick reference
        tasks = run_output.get("tasks", [])
        failed_tasks = [
            {
                "task_key": t.get("task_key"),
                "run_id": t.get("run_id"),
                "state": t.get("state", {}).get("result_state"),
                "error": t.get("error"),
            }
            for t in tasks
            if t.get("state", {}).get("result_state") == "FAILED" or t.get("error")
        ]

        # Extract state info for convenience
        state = run_output.get("state", {})
        result_state = state.get("result_state", "UNKNOWN") if state else "UNKNOWN"
        state_message = state.get("state_message", "") if state else ""

        logger.debug(
            f"Fetched run output for run_id {run_id}: "
            f"state={result_state}, tasks={len(tasks)}, failed={len(failed_tasks)}"
        )

        return {
            "run_id": run_id,
            "job_id": run_output.get("job_id"),
            "state": result_state,
            "state_message": state_message,
            "start_time": run_output.get("start_time"),
            "end_time": run_output.get("end_time"),
            "error": run_output.get("error"),
            "error_code": "tool_error",
            "summary": run_output.get("summary"),  # Aggregated task errors
            "tasks": tasks,  # Full task outputs with logs/notebook_output
            "failed_tasks": failed_tasks,  # Quick reference to failed tasks
        }

    async def get_task_logs(self, run_id: str, task_key: str) -> dict[str, Any]:
        """Get logs for a specific task within a job run.

        This tool retrieves detailed logs and output for a single task,
        useful when you need to focus on a specific failing task within
        a multi-task job run.

        Args:
            run_id: Databricks job run ID (string or integer).
            task_key: The task_key identifier for the specific task.

        Returns:
            Dict with task logs including:
            - task_key: Task identifier
            - task_run_id: Task-level run ID
            - state: Task state (result_state, state_message)
            - logs: Task execution logs (if available)
            - error: Error message if task failed
            - notebook_output: Notebook result if applicable
            - duration_ms: Task execution duration

        Example:
            >>> result = await tools.get_task_logs("123456789", "etl_transform")
            >>> if result.get("error"):
            ...     print(f"Task failed: {result['error']}")
            >>> if result.get("logs"):
            ...     print(result["logs"])
        """
        self.events.emit_info(
            source="job_tools",
            message=f"Fetching task logs for run: {run_id}, task: {task_key}",
            phase="execution",
        )

        run_id_int = int(run_id)

        if self.provider is None:
            raise RuntimeError("SharedContextProvider not initialized")

        # Get task-specific logs
        task_logs = await self.provider.client.get_task_logs(run_id_int, task_key)

        # Format duration for readability
        duration_ms = task_logs.get("duration_ms")
        duration_str = None
        if duration_ms:
            if duration_ms < 1000:
                duration_str = f"{duration_ms}ms"
            elif duration_ms < 60000:
                duration_str = f"{duration_ms / 1000:.1f}s"
            else:
                duration_str = f"{duration_ms / 60000:.1f}m"

        # Extract state info
        state = task_logs.get("state", {})
        result_state = state.get("result_state", "UNKNOWN") if state else "UNKNOWN"
        state_message = state.get("state_message", "") if state else ""

        logger.debug(
            f"Fetched task logs for run_id {run_id}, task {task_key}: "
            f"state={result_state}, has_logs={task_logs.get('logs') is not None}"
        )

        return {
            "run_id": run_id,
            "task_key": task_key,
            "task_run_id": task_logs.get("task_run_id"),
            "state": result_state,
            "state_message": state_message,
            "logs": task_logs.get("logs"),
            "error": task_logs.get("error"),
            "error_code": "tool_error",
            "notebook_output": task_logs.get("notebook_output"),
            "sql_output": task_logs.get("sql_output"),
            "dbt_output": task_logs.get("dbt_output"),
            "duration_ms": duration_ms,
            "duration": duration_str,
        }
