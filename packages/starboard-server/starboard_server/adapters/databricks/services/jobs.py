"""Async Job service implementation.

This module provides async job operations for the Databricks Jobs API,
including job configuration retrieval, run listing, and job execution.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any

from starboard_server.adapters.databricks.services.base import BaseService
from starboard_server.exceptions import DatabricksAPIError
from starboard_server.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient

logger = get_logger(__name__)

class JobService(BaseService):
    """Async service for Databricks job operations.

    Provides async methods for:
    - Getting job configuration
    - Listing job runs
    - Running jobs
    - Creating jobs
    - Listing all jobs

    Example:
        >>> service = JobService(workspace_client)
        >>> job = await service.get_job(12345)
        >>> runs = await service.list_runs(12345, limit=5)
    """

    def __init__(self, client: WorkspaceClient) -> None:
        """Initialize job service.

        Args:
            client: Authenticated Databricks WorkspaceClient
        """
        super().__init__(client)

    async def get_job(self, job_id: int) -> dict[str, Any]:
        """Get job configuration by ID.

        Args:
            job_id: Databricks job ID

        Returns:
            Job configuration dictionary with keys like:
            - job_id: Job identifier
            - settings: Job settings (name, tasks, schedule, etc.)
            - creator_user_name: User who created the job
            - created_time: Creation timestamp

        Example:
            >>> job = await service.get_job(12345)
            >>> print(job["settings"]["name"])
            'ETL Pipeline'
        """
        logger.debug("get_job", extra={"job_id": job_id})
        return await self._run_sync(lambda: self._client.jobs.get(job_id).as_dict())

    async def list_runs(
        self,
        job_id: int,
        limit: int = 5,
        expand_tasks: bool = True,
    ) -> list[dict[str, Any]]:
        """List recent runs for a job, sorted by start_time descending.

        Args:
            job_id: Databricks job ID
            limit: Maximum number of runs to return (default: 5)
            expand_tasks: Include task details in response (default: True)

        Returns:
            List of run dictionaries sorted by start_time descending (newest first).
            Each run contains:
            - run_id: Run identifier
            - state: Run state (life_cycle_state, result_state, etc.)
            - start_time: Run start timestamp (epoch ms)
            - end_time: Run end timestamp (epoch ms)
            - tasks: Task details (if expand_tasks=True)

        Example:
            >>> runs = await service.list_runs(12345, limit=10)
            >>> for run in runs:
            ...     print(f"Run {run['run_id']}: {run['state']['result_state']}")
        """
        logger.debug(
            "list_runs",
            extra={"job_id": job_id, "limit": limit, "expand_tasks": expand_tasks},
        )

        def _list() -> list[dict[str, Any]]:
            runs: list[dict[str, Any]] = []
            for run in self._client.jobs.list_runs(
                job_id=job_id,
                expand_tasks=expand_tasks,
                limit=limit,
            ):
                runs.append(run.as_dict())
            # Sort by start_time descending (newest first)
            runs.sort(key=lambda r: r.get("start_time", 0), reverse=True)
            return runs

        return await self._run_sync(_list)

    async def run_job(
        self,
        job_id: int,
        wait_timeout: int = 15,
    ) -> dict[str, Any]:
        """Run a job and wait for completion.

        This is a blocking operation that waits for the job to complete
        or timeout. Use for jobs expected to complete within the timeout.

        Args:
            job_id: Databricks job ID to run
            wait_timeout: Maximum minutes to wait for completion (default: 15)

        Returns:
            Run result dictionary with:
            - run_id: The run identifier
            - state: Final state of the run
            - tasks: Task execution details

        Raises:
            TimeoutError: If job doesn't complete within timeout
            DatabricksError: If job execution fails

        Example:
            >>> result = await service.run_job(12345, wait_timeout=30)
            >>> print(f"Run completed: {result['run_id']}")
        """
        logger.debug("run_job", extra={"job_id": job_id, "wait_timeout": wait_timeout})

        def _run() -> dict[str, Any]:
            waiter = self._client.jobs.run_now(job_id)
            result = waiter.result(
                timeout=datetime.timedelta(minutes=wait_timeout),
            )
            return result.as_dict()

        return await self._run_sync(_run)

    async def create_job(self, job_spec: dict[str, Any]) -> dict[str, Any]:
        """Create a new job.

        Args:
            job_spec: Job configuration dictionary. See Databricks Jobs API
                     documentation for full specification.

        Returns:
            Created job dictionary with job_id

        Example:
            >>> job_spec = {
            ...     "name": "My ETL Job",
            ...     "tasks": [...],
            ...     "schedule": {...},
            ... }
            >>> job = await service.create_job(job_spec)
            >>> print(f"Created job: {job['job_id']}")
        """
        logger.debug("create_job", extra={"job_name": job_spec.get("name")})
        return await self._run_sync(
            lambda: self._client.jobs.create(**job_spec).as_dict()
        )

    async def list_jobs(self, limit: int = 100) -> list[dict[str, Any]]:
        """List all jobs in the workspace.

        Args:
            limit: Maximum number of jobs to return (default: 100)

        Returns:
            List of job summary dictionaries

        Example:
            >>> jobs = await service.list_jobs(limit=50)
            >>> for job in jobs:
            ...     print(f"{job['job_id']}: {job['settings']['name']}")
        """
        logger.debug("list_jobs", extra={"limit": limit})

        def _list() -> list[dict[str, Any]]:
            return [job.as_dict() for job in self._client.jobs.list(limit=limit)]

        return await self._run_sync(_list)

    async def search_jobs_by_name(
        self,
        job_name: str,
        exact_match: bool = True,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search for jobs by name.

        Uses Databricks SDK's name filter for efficient exact match search.
        Falls back to partial match search if exact match not found.

        Args:
            job_name: Job name to search for
            exact_match: If True, try exact match first (default: True)
            limit: Maximum number of results for partial match (default: 10)

        Returns:
            List of matching job dictionaries. For exact match, returns 0-1 result.
            For partial match, returns up to `limit` results.

        Example:
            >>> # Exact match
            >>> jobs = await service.search_jobs_by_name("my_etl_pipeline")
            >>> # Partial match
            >>> jobs = await service.search_jobs_by_name("etl", exact_match=False)
        """
        logger.debug(
            "search_jobs_by_name",
            extra={"job_name": job_name, "exact_match": exact_match, "limit": limit},
        )

        def _search() -> list[dict[str, Any]]:
            results: list[dict[str, Any]] = []

            if exact_match:
                # Use SDK's name filter for exact match - efficient server-side filter
                for job in self._client.jobs.list(name=job_name):
                    results.append(job.as_dict())
                    # Exact match should return only one result
                    break

                if results:
                    logger.debug("Exact match found for job name: {job_name}")
                    return results

            # Partial match: iterate and filter
            # Note: This is less efficient but necessary for partial matches
            job_name_lower = job_name.lower()
            for job in self._client.jobs.list():
                settings = job.settings
                if (
                    settings
                    and settings.name
                    and job_name_lower in settings.name.lower()
                ):
                    results.append(job.as_dict())
                    if len(results) >= limit:
                        break

            logger.debug("Partial match found {len(results)} jobs for: {job_name}")
            return results

        return await self._run_sync(_search)

    async def get_run(self, run_id: int) -> dict[str, Any]:
        """Get details of a specific job run.

        Args:
            run_id: Databricks run ID

        Returns:
            Run dictionary with:
            - run_id: Run identifier
            - state: Run state (life_cycle_state, result_state, state_message)
            - start_time: Run start timestamp
            - end_time: Run end timestamp (if completed)
            - tasks: Task execution details
            - cluster_spec: Cluster configuration used
            - job_id: Parent job ID

        Example:
            >>> run = await service.get_run(123456789)
            >>> print(f"Run state: {run['state']['result_state']}")
        """
        logger.debug("get_run", extra={"run_id": run_id})
        return await self._run_sync(lambda: self._client.jobs.get_run(run_id).as_dict())

    async def get_run_output(self, run_id: int) -> dict[str, Any]:
        """Get output and logs for a specific job run, including all task outputs.

        This is a key diagnostic tool for understanding job failures.
        Retrieves the job run, iterates through all tasks, and collects
        task-level outputs (since get_run_output requires task run IDs).

        Args:
            run_id: Databricks job run ID (parent run)

        Returns:
            Run output dictionary with:
            - run_id: The job run ID
            - state: Job run state (life_cycle_state, result_state)
            - tasks: List of task outputs, each containing:
              - task_key: Task identifier
              - run_id: Task-level run ID
              - state: Task state
              - output: Task output (notebook_output, error, logs, etc.)
              - error: Error message if task failed
            - error: Top-level error if the entire run failed
            - summary: Aggregated error messages from failed tasks

        Example:
            >>> output = await service.get_run_output(123456789)
            >>> for task in output.get("tasks", []):
            ...     if task.get("error"):
            ...         print(f"Task {task['task_key']} failed: {task['error']}")
        """
        logger.debug("get_run_output", extra={"run_id": run_id})

        def _get_output() -> dict[str, Any]:
            result: dict[str, Any] = {
                "run_id": run_id,
                "state": None,
                "tasks": [],
                "error": None,
                "summary": None,
            }

            try:
                # Step 1: Get the job run to access task list
                job_run = self._client.jobs.get_run(run_id)
                run_dict = job_run.as_dict()

                result["state"] = run_dict.get("state")
                result["job_id"] = run_dict.get("job_id")
                result["start_time"] = run_dict.get("start_time")
                result["end_time"] = run_dict.get("end_time")

                # Check for top-level run error
                state = run_dict.get("state", {})
                if state.get("state_message"):
                    result["error"] = state.get("state_message")

                # Step 2: Get tasks from the run
                tasks = run_dict.get("tasks", [])
                if not tasks:
                    logger.debug(
                        "get_run_output_no_tasks",
                        extra={"run_id": run_id},
                    )
                    return result

                # Step 3: For each task, get its output using the task's run_id
                failed_task_errors: list[str] = []

                for task in tasks:
                    task_key = task.get("task_key", "unknown")
                    task_run_id = task.get("run_id")
                    task_state = task.get("state", {})

                    task_output: dict[str, Any] = {
                        "task_key": task_key,
                        "run_id": task_run_id,
                        "state": task_state,
                        "output": None,
                        "error": None,
                    }

                    # Check for task-level error in state
                    if task_state.get("state_message"):
                        task_output["error"] = task_state.get("state_message")
                        failed_task_errors.append(
                            f"[{task_key}] {task_state.get('state_message')}"
                        )

                    # Get task output if we have a task run_id
                    if task_run_id:
                        try:
                            output = self._client.jobs.get_run_output(task_run_id)
                            output_dict = output.as_dict()
                            task_output["output"] = output_dict

                            # Extract error from output if present
                            if output_dict.get("error"):
                                task_output["error"] = output_dict.get("error")
                                if task_key not in str(failed_task_errors):
                                    failed_task_errors.append(
                                        f"[{task_key}] {output_dict.get('error')}"
                                    )

                            # Extract notebook output if present
                            if output_dict.get("notebook_output"):
                                nb_output = output_dict["notebook_output"]
                                if nb_output.get("result"):
                                    task_output["notebook_result"] = nb_output["result"]
                                if nb_output.get("truncated"):
                                    task_output["notebook_truncated"] = True

                            # Extract logs if present
                            if output_dict.get("logs"):
                                task_output["logs"] = output_dict["logs"]

                        except (DatabricksAPIError, OSError) as task_error:
                            logger.warning(
                                "get_task_output_failed",
                                extra={
                                    "run_id": run_id,
                                    "task_key": task_key,
                                    "task_run_id": task_run_id,
                                    "error": str(task_error),
                                },
                            )
                            task_output["output_error"] = str(task_error)

                    result["tasks"].append(task_output)

                # Create summary of errors
                if failed_task_errors:
                    result["summary"] = "\n".join(failed_task_errors)

                logger.debug(
                    "get_run_output_complete",
                    extra={
                        "run_id": run_id,
                        "task_count": len(tasks),
                        "failed_count": len(failed_task_errors),
                    },
                )

                return result

            except (DatabricksAPIError, OSError) as e:
                # Return error info instead of raising
                logger.warning(
                    "get_run_output_failed",
                    extra={"run_id": run_id, "error": str(e)},
                )
                result["error"] = str(e)
                return result

        return await self._run_sync(_get_output)

    async def get_task_logs(self, run_id: int, task_key: str) -> dict[str, Any]:
        """Get logs for a specific task within a job run.

        This tool retrieves detailed logs and output for a single task,
        which is useful when you need to focus on a specific failing task
        rather than retrieving all task outputs.

        Args:
            run_id: Databricks job run ID (parent run).
            task_key: The task_key identifier for the specific task.

        Returns:
            Task log dictionary with:
            - task_key: The task identifier
            - task_run_id: The task-level run ID
            - state: Task state (result_state, state_message)
            - logs: Task execution logs (if available)
            - error: Error message if task failed
            - notebook_output: Notebook result if applicable
            - duration_ms: Task execution duration

        Example:
            >>> logs = await service.get_task_logs(123456789, "etl_transform")
            >>> if logs.get("error"):
            ...     print(f"Task failed: {logs['error']}")
            >>> if logs.get("logs"):
            ...     print(logs["logs"])
        """
        logger.debug(
            "get_task_logs",
            extra={"run_id": run_id, "task_key": task_key},
        )

        def _get_task_logs() -> dict[str, Any]:
            result: dict[str, Any] = {
                "run_id": run_id,
                "task_key": task_key,
                "task_run_id": None,
                "state": None,
                "logs": None,
                "error": None,
                "notebook_output": None,
                "duration_ms": None,
            }

            try:
                # Step 1: Get the job run to find the task
                job_run = self._client.jobs.get_run(run_id)
                run_dict = job_run.as_dict()

                tasks = run_dict.get("tasks", [])
                if not tasks:
                    result["error"] = f"No tasks found in run {run_id}"
                    return result

                # Step 2: Find the specific task by task_key
                target_task = None
                for task in tasks:
                    if task.get("task_key") == task_key:
                        target_task = task
                        break

                if not target_task:
                    result["error"] = (
                        f"Task '{task_key}' not found in run {run_id}. "
                        f"Available tasks: {[t.get('task_key') for t in tasks]}"
                    )
                    return result

                # Extract task metadata
                task_run_id = target_task.get("run_id")
                task_state = target_task.get("state", {})
                start_time = target_task.get("start_time")
                end_time = target_task.get("end_time")

                result["task_run_id"] = task_run_id
                result["state"] = {
                    "result_state": task_state.get("result_state"),
                    "life_cycle_state": task_state.get("life_cycle_state"),
                    "state_message": task_state.get("state_message"),
                }

                # Calculate duration
                if start_time and end_time:
                    result["duration_ms"] = end_time - start_time

                # Check for error in task state
                if task_state.get("state_message"):
                    result["error"] = task_state.get("state_message")

                # Step 3: Get task output using task_run_id
                if task_run_id:
                    try:
                        output = self._client.jobs.get_run_output(task_run_id)
                        output_dict = output.as_dict()

                        # Extract logs
                        if output_dict.get("logs"):
                            result["logs"] = output_dict["logs"]

                        # Extract error from output
                        if output_dict.get("error"):
                            result["error"] = output_dict.get("error")

                        # Extract notebook output
                        if output_dict.get("notebook_output"):
                            nb_output = output_dict["notebook_output"]
                            result["notebook_output"] = {
                                "result": nb_output.get("result"),
                                "truncated": nb_output.get("truncated", False),
                            }

                        # Extract SQL output if present
                        if output_dict.get("sql_output"):
                            result["sql_output"] = output_dict["sql_output"]

                        # Extract dbt output if present
                        if output_dict.get("dbt_output"):
                            result["dbt_output"] = output_dict["dbt_output"]

                    except (DatabricksAPIError, OSError) as output_error:
                        logger.warning(
                            "get_task_logs_output_failed",
                            extra={
                                "run_id": run_id,
                                "task_key": task_key,
                                "task_run_id": task_run_id,
                                "error": str(output_error),
                            },
                        )
                        result["output_error"] = str(output_error)

                logger.debug(
                    "get_task_logs_complete",
                    extra={
                        "run_id": run_id,
                        "task_key": task_key,
                        "has_logs": result["logs"] is not None,
                        "has_error": result["error"] is not None,
                    },
                )

                return result

            except (DatabricksAPIError, OSError) as e:
                logger.warning(
                    "get_task_logs_failed",
                    extra={"run_id": run_id, "task_key": task_key, "error": str(e)},
                )
                result["error"] = str(e)
                return result

        return await self._run_sync(_get_task_logs)
