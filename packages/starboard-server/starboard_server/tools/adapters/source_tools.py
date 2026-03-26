"""Async reasoning interface for source code tools.

This module provides the LLM-facing interface for source code operations:
- Extracting source code from Databricks job tasks
- Analyzing code quality with LLM
- Getting task definitions

Architecture:
    SourceTools (adapter) → SourceTransformer (domain) + Databricks API
"""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import TYPE_CHECKING, Any

from starboard_core.domain.transformers.job_transformers import transform_task_sources

from starboard_server.infra.observability.events import EventEmitter
from starboard_server.exceptions import AdapterError, ToolError
from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.adapters.base import BaseToolAdapter
from starboard_server.tools.domain.source import SourceTransformer
from starboard_server.tools.domain.source.models import CodeQualityIssue
from starboard_server.tools.domain.utils import pack_dict

if TYPE_CHECKING:
    from starboard_server.adapters.databricks import AsyncDatabricksClient
    from starboard_server.adapters.llm.base import BaseLLMClient

logger = get_logger(__name__)

# =============================================================================
# LLM Prompts and Schemas
# =============================================================================

CODE_PASS_SYSTEM_PROMPT = """You are a senior Databricks & Spark performance and optimization expert.

MISSION: Audit code for performance issues and provide precise, safe, incremental optimizations.

FOCUS AREAS:
1. Databricks-native features:
   - Photon vectorization, AQE, Dynamic Partition Pruning
   - Liquid Clustering, Predictive I/O
   - SQL Warehouse & Unity Catalog integration
   - Intelligent caching and shuffle minimization

2. Anti-patterns to flag:
   - Data collection: collect(), toPandas() on large datasets
   - Aggregations: wide groupBy without stats, missing broadcast hints
   - Joins: non-broadcastable joins, Cartesian products
   - UDFs: excessive Python UDFs (prefer native Spark)
   - Operations: nested explode, file-at-a-time loops
   - Partitioning: misuse of repartition/coalesce
   - I/O: tiny file writes (<128MB), caching without reuse
   - Correctness: nondeterministic order reliance

PRIORITIZATION:
If you find >10 issues:
1. Score each by: (performance_impact × confidence) - risk_score
2. Select top 5-10 highest-scoring issues
3. Ensure mix of quick wins (low effort, high impact) and strategic fixes

SAFETY REQUIREMENTS:
- Maintain correctness (no semantic changes unless explicitly safe)
- Provide before/after code snippets
- Document risks and rollback steps

OUTPUT:
Return JSON with "hotspots" array (5-10 items max) and optional "notes" array.
If code is fully optimized, return empty hotspots array with explanatory note."""

CODE_PASS_SCHEMA = {
    "type": "object",
    "properties": {
        "hotspots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "artifact": {"type": "string"},
                    "line_range": {"type": "string"},
                    "issue": {"type": "string"},
                    "signal": {"type": "array", "items": {"type": "string"}},
                    "evidence": {"type": "string"},
                    "risk": {"type": "string"},
                    "fix": {
                        "type": "object",
                        "properties": {
                            "strategy": {"type": "string"},
                            "snippet_before": {"type": "string"},
                            "snippet_after": {"type": "string"},
                        },
                        "required": ["strategy", "snippet_before", "snippet_after"],
                        "additionalProperties": False,
                    },
                },
                "required": [
                    "artifact",
                    "line_range",
                    "issue",
                    "signal",
                    "evidence",
                    "risk",
                    "fix",
                ],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["hotspots", "notes"],
    "additionalProperties": False,
}


# =============================================================================
# SourceTools
# =============================================================================


class AnalysisMode(str, Enum):
    """Analysis strategy for code quality.

    Use ``BATCH`` (default) to analyze all code in a single LLM call, or
    ``INDIVIDUAL`` to analyze each artifact separately in parallel.
    """

    BATCH = "batch"
    """Analyze all code in single LLM call."""

    INDIVIDUAL = "individual"
    """Analyze each artifact separately in parallel."""


class SourceTools(BaseToolAdapter):
    """Async reasoning interface for source code operations.

    Clean interface optimized for LLM reasoning. Combines the adapter
    and service layers for direct access to source code operations.

    Example:
        >>> tools = SourceTools(api, llm_client, events=events)
        >>> result = await tools.get_source_code(job_id="12345")
    """

    def __init__(
        self,
        api: AsyncDatabricksClient,
        llm_client: BaseLLMClient | None = None,
        *,
        events: EventEmitter | None = None,
    ):
        """Initialize source tools.

        Args:
            api: Async Databricks client for source code fetching
            llm_client: Optional LLM client for code analysis
            events: Optional event emitter for status updates
        """
        super().__init__(events=events)
        self.databricks_api = api
        self.llm_client = llm_client

    # =========================================================================
    # Public Methods (LLM-facing interface)
    # =========================================================================

    async def get_source_code(
        self,
        job_id: str,
        task_key: str | None = None,
    ) -> dict[str, Any]:
        """Get source code for job tasks.

        Args:
            job_id: Databricks job ID
            task_key: Optional specific task key to filter

        Returns:
            Dict with task sources and metadata

        Example:
            >>> result = await tools.get_source_code(
            ...     job_id="12345",
            ...     task_key="ingest_data"
            ... )
            >>> # Returns:
            >>> # {
            >>> #   "task_sources": {
            >>> #     "ingest_data": {
            >>> #       "type": "notebook",
            >>> #       "path": "/path/to/notebook",
            >>> #       "source": "# code here..."
            >>> #     }
            >>> #   },
            >>> #   "has_source_code": true,
            >>> #   "task_count": 1
            >>> # }
        """
        result = await self._inspect_source_code(job_id, task_key)

        # Extract the relevant data for response
        task_sources = result.get("task_sources", {})
        has_source_code = result.get("has_source_code", False)

        return {
            "task_sources": task_sources,
            "has_source_code": has_source_code,
            "task_count": len(task_sources),
        }

    async def analyze_code_quality(
        self,
        source_code: str | None = None,
        job_id: str | None = None,
        task_key: str | None = None,
        language: str | None = None,  # noqa: ARG002
        mode: AnalysisMode = AnalysisMode.BATCH,
    ) -> dict[str, Any]:
        """Analyze source code for quality issues using LLM.

        Supports two input modes:
        1. Direct source_code analysis (adhoc code)
        2. Job ID to fetch and analyze all task sources

        Args:
            source_code: Optional adhoc source code to analyze
            job_id: Optional job ID to fetch sources from
            task_key: Optional specific task key to filter (requires job_id)
            language: Optional language hint (auto-detected if not provided)
            mode: Analysis strategy (BATCH or INDIVIDUAL). Default: BATCH.

        Returns:
            Dict with quality issues and notes

        Example:
            >>> # Adhoc code analysis
            >>> result = await tools.analyze_code_quality(
            ...     source_code="SELECT * FROM large_table"
            ... )
            >>> # Returns:
            >>> # {
            ...   "issues": [
            ...     {
            ...       "context": "adhoc",
            ...       "severity": "high",
            ...       "issue": "Full table scan",
            ...       "description": "Query performs full scan without filters",
            ...       "recommendation": "Add WHERE clause to filter data"
            ...     }
            ...   ],
            ...   "notes": ["Code analyzed successfully"],
            ...   "issue_count": 1
            ... }

            >>> # Job source analysis
            >>> result = await tools.analyze_code_quality(job_id="12345")
        """
        task_sources = None

        # If job_id provided, fetch sources first
        if job_id:
            inspect_result = await self._inspect_source_code(job_id, task_key)
            task_sources = inspect_result.get("task_sources")

        # Analyze code
        result = await self._analyze_code_quality(
            source_code=source_code,
            task_sources=task_sources,
            task_key=task_key,
            mode=mode,
        )

        # Extract data from result
        issues = result.get("code_quality_issues", [])
        notes = result.get("code_quality_notes", [])

        return {
            "issues": issues,
            "notes": notes,
            "issue_count": len(issues),
        }

    async def get_task_definitions(
        self,
        job_id: str,
        task_key: str | None = None,
    ) -> dict[str, Any]:
        """Fetch task definitions from job configuration.

        Args:
            job_id: Databricks job ID
            task_key: Optional specific task key to filter

        Returns:
            Dict with task definitions

        Example:
            >>> result = await tools.get_task_definitions(job_id="12345")
            >>> # Returns:
            >>> # {
            >>> #   "tasks": [
            >>> #     {
            >>> #       "task_key": "ingest_data",
            >>> #       "notebook_task": {"notebook_path": "/path"},
            >>> #       ...
            >>> #     }
            >>> #   ],
            >>> #   "task_count": 1
            >>> # }
        """
        tasks = await self._get_task_definitions_from_job(job_id, task_key)

        return {
            "tasks": tasks,
            "task_count": len(tasks),
        }

    # =========================================================================
    # Internal Implementation Methods
    # =========================================================================

    def _emit_info(self, source: str, message: str) -> None:
        """Emit info event."""
        self.events.emit_info(source=source, message=message)

    async def _get_task_definitions_from_job(
        self, job_id: str, task_key: str | None = None
    ) -> list[dict[str, Any]]:
        """Fetch task definitions from job configuration.

        Args:
            job_id: Databricks job ID
            task_key: Optional specific task key to filter

        Returns:
            List of task definition dictionaries
        """
        logger.debug("Fetching task definitions for job_id={job_id}")

        try:
            job_id_int = int(job_id)
            job_config = await self.databricks_api.jobs.get_job(job_id_int)
        except (ValueError, TypeError):
            logger.error("Invalid job_id format: {job_id}, error: {e}")
            return []
        except (ToolError, AdapterError, ValueError):
            logger.error("Failed to fetch job config for job_id={job_id}: {e}")
            return []

        if not job_config:
            logger.warning("Could not fetch job config for job_id={job_id}")
            return []

        # Extract task definitions from job settings
        job_settings = job_config.get("settings", {})
        tasks = job_settings.get("tasks", [])

        # Filter to specific task if requested
        if task_key:
            filtered = [t for t in tasks if t.get("task_key") == task_key]
            if not filtered:
                logger.warning("Task key '{task_key}' not found in job {job_id}")
            return filtered

        return tasks

    async def _extract_notebook_source(
        self, task: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Extract source code from notebook task."""
        notebook_path = task["notebook_task"].get("notebook_path")
        if not notebook_path:
            return None

        try:
            source = await self.databricks_api.workspace.get_notebook_content(
                notebook_path
            )
            if source:
                return {
                    "type": "notebook",
                    "path": notebook_path,
                    "source": source,
                }
            logger.warning("Notebook {notebook_path} returned empty content")
        except (ToolError, AdapterError, ValueError):
            logger.warning("Failed to fetch notebook {notebook_path}: {e}")

        return None

    def _extract_python_source(self, task: dict[str, Any]) -> dict[str, Any] | None:
        """Extract source code placeholder for Python file task."""
        python_file = task["spark_python_task"].get("python_file")
        if not python_file:
            return None

        return {
            "type": "python_file",
            "path": python_file,
            "source": f"# Python file: {python_file}\n# Source not available",
        }

    def _extract_sql_source(self, task: dict[str, Any]) -> dict[str, Any] | None:
        """Extract inline SQL from SQL task."""
        query = task["sql_task"].get("query", {}).get("query")
        if not query:
            return None

        return {
            "type": "sql",
            "source": query,
        }

    async def _extract_task_source(self, task: dict[str, Any]) -> dict[str, Any] | None:
        """Extract source code from a task definition based on task type."""
        if "notebook_task" in task:
            return await self._extract_notebook_source(task)
        elif "spark_python_task" in task:
            return self._extract_python_source(task)
        elif "sql_task" in task:
            return self._extract_sql_source(task)

        return None

    async def _inspect_source_code(
        self, job_id: str, task_key: str | None = None
    ) -> dict[str, Any]:
        """Fetch and parse task source code from job definitions."""
        self._emit_info(
            source="inspect_source_code",
            message=f"Inspecting source for job {job_id}",
        )

        # Get task definitions
        task_definitions = await self._get_task_definitions_from_job(job_id, task_key)

        if not task_definitions:
            logger.warning("No task definitions found for source inspection")
            return SourceTransformer.build_empty_source_result()

        # Extract source code for each task
        task_sources = {}
        for task in task_definitions:
            task_key_str = task.get("task_key")
            if not task_key_str:
                continue

            source_info = await self._extract_task_source(task)
            if source_info:
                task_sources[task_key_str] = source_info

        logger.debug(
            f"Inspected source for {len(task_sources)} out of "
            f"{len(task_definitions)} tasks"
        )

        return SourceTransformer.build_source_result(task_sources)

    async def _analyze_code_quality(
        self,
        source_code: str | None = None,
        task_sources: dict[str, Any] | None = None,
        task_key: str | None = None,
        mode: AnalysisMode = AnalysisMode.BATCH,
    ) -> dict[str, Any]:
        """Analyze source code for quality issues using LLM."""
        if not self.llm_client:
            logger.error("LLM client required for code quality analysis")
            return SourceTransformer.build_empty_analysis_result()

        # Early return if no source code
        if not source_code and not task_sources:
            logger.warning("No source code found for quality analysis")
            return SourceTransformer.build_empty_analysis_result()

        # Build message with task_key context if available
        context_msg = f"task '{task_key}'" if task_key else "code"
        self._emit_info(
            source="analyze_code_quality",
            message=f"Analyzing {context_msg} quality "
            f"({mode.value.upper()} mode)",
        )

        # Transform task sources if provided
        transformed_sources = {}
        if task_sources:
            transformed_sources = transform_task_sources(task_sources)

        # Collect all code artifacts
        code_artifacts: dict[str, dict[str, Any]] = {}

        # Add adhoc source if provided
        if source_code:
            code_artifacts["adhoc"] = {
                "task_type": "adhoc",
                "code": source_code,
            }

        # Add transformed task sources
        for key, source_info in transformed_sources.items():
            if source_info.get("code"):
                code_artifacts[key] = source_info

        # Analyze based on mode
        if mode == AnalysisMode.BATCH:
            issues, notes = await self._analyze_batch(code_artifacts)
        else:
            issues, notes = await self._analyze_individual_parallel(code_artifacts)

        logger.debug("LLM identified {len(issues)} code quality issues")

        return SourceTransformer.build_analysis_result(issues, notes)

    def _build_analysis_messages(
        self, code_artifacts: dict[str, dict[str, Any]]
    ) -> list[dict[str, str]]:
        """Build LLM messages for code quality analysis.

        Args:
            code_artifacts: Code artifacts to analyze.

        Returns:
            List of message dicts for the LLM call.
        """
        user_content = f"""Analyze the following code artifacts for optimization opportunities:

CODE ARTIFACTS:
{pack_dict(code_artifacts)}

RUNTIME CONTEXT (if available):


Focus on: performance, anti-patterns, Databricks best practices, correctness

Return optimizations in json format."""

        return [
            {"role": "system", "content": CODE_PASS_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

    async def _call_llm_for_analysis(
        self,
        code_artifacts: dict[str, dict[str, Any]],
        default_context: str = "unknown",
    ) -> tuple[list[CodeQualityIssue], list[str]]:
        """Call LLM to analyze code artifacts and return issues.

        Args:
            code_artifacts: Code artifacts to analyze.
            default_context: Default context label for hotspot transformation.

        Returns:
            Tuple of (issues, notes).
        """
        if self.llm_client is None:
            raise ValueError("LLM client not initialized")

        messages = self._build_analysis_messages(code_artifacts)

        response = await self.llm_client.json_response(
            phase="synth",
            messages=messages,
            budget=None,
            schema=CODE_PASS_SCHEMA,
        )

        issues = [
            SourceTransformer.transform_hotspot_to_issue(
                hotspot, context=hotspot.get("artifact", default_context)
            )
            for hotspot in response.get("hotspots", [])
        ]

        return issues, response.get("notes", [])

    async def _analyze_batch(
        self, code_artifacts: dict[str, dict[str, Any]]
    ) -> tuple[list[CodeQualityIssue], list[str]]:
        """Analyze all code snippets in a single LLM call."""
        logger.debug("Batch analyzing {len(code_artifacts)} code artifacts")

        try:
            return await self._call_llm_for_analysis(code_artifacts)
        except (ToolError, AdapterError, ValueError) as e:
            logger.error("Batch code analysis failed: {e}")
            return [], [f"Analysis failed: {str(e)}"]

    async def _analyze_individual_parallel(
        self, code_artifacts: dict[str, dict[str, Any]]
    ) -> tuple[list[CodeQualityIssue], list[str]]:
        """Analyze each code snippet individually in parallel."""
        logger.debug(
            f"Analyzing {len(code_artifacts)} code artifacts individually in parallel"
        )

        tasks = [
            self._analyze_single(context, source_info)
            for context, source_info in code_artifacts.items()
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_issues: list[CodeQualityIssue] = []
        all_notes: list[str] = []

        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                context = list(code_artifacts.keys())[i]
                logger.error("Analysis failed for {context}: {result}")
                all_notes.append(f"Failed to analyze {context}: {str(result)}")
            elif isinstance(result, tuple):
                issues, notes = result
                all_issues.extend(issues)
                all_notes.extend(notes)

        return all_issues, all_notes

    async def _analyze_single(
        self, context: str, source_info: dict[str, Any]
    ) -> tuple[list[CodeQualityIssue], list[str]]:
        """Analyze a single code snippet with LLM."""
        try:
            return await self._call_llm_for_analysis(
                {context: source_info}, default_context=context
            )
        except (ToolError, AdapterError, ValueError) as e:
            logger.error("Single code analysis failed for {context}: {e}")
            return [], [f"Analysis failed for {context}: {str(e)}"]
