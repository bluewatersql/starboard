# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Pure domain logic for source code transformations."""

from __future__ import annotations

from typing import Any

from starboard_server.infra.observability.logging import get_logger
from starboard_server.tools.domain.source.models import CodeQualityIssue

logger = get_logger(__name__)


class SourceTransformer:
    """Pure functions for transforming source code data."""

    @staticmethod
    def transform_hotspot_to_issue(
        hotspot: dict[str, Any], context: str = "unknown"
    ) -> CodeQualityIssue:
        """
        Transform LLM hotspot response to standard issue format.

        Args:
            hotspot: Raw hotspot dictionary from LLM
            context: Context identifier (task_key or "adhoc")

        Returns:
            CodeQualityIssue object

        Examples:
            >>> hotspot = {
            ...     "artifact": "task1",
            ...     "risk": "high",
            ...     "issue": "SQL injection risk",
            ...     "evidence": "Unparameterized SQL query",
            ...     "fix": {
            ...         "strategy": "Use parameterized queries",
            ...         "snippet_before": "query = f'SELECT * FROM {table}'",
            ...         "snippet_after": "query = 'SELECT * FROM ?', params=[table]"
            ...     },
            ...     "line_range": "10-12",
            ...     "signal": ["security", "sql"]
            ... }
            >>> issue = SourceTransformer.transform_hotspot_to_issue(hotspot, "task1")
            >>> issue.severity
            'high'
            >>> issue.issue
            'SQL injection risk'
        """
        return CodeQualityIssue(
            context=context,
            severity=hotspot.get("risk", "medium"),
            issue=hotspot.get("issue", ""),
            description=hotspot.get("evidence", ""),
            recommendation=hotspot.get("fix", {}).get("strategy", ""),
            code_snippet=hotspot.get("fix", {}).get("snippet_before"),
            fix_snippet=hotspot.get("fix", {}).get("snippet_after"),
            line_range=hotspot.get("line_range"),
            signals=hotspot.get("signal", []),
        )

    @staticmethod
    def issue_to_dict(issue: CodeQualityIssue) -> dict[str, Any]:
        """
        Convert CodeQualityIssue to dictionary format.

        Args:
            issue: CodeQualityIssue object

        Returns:
            Dictionary representation

        Examples:
            >>> issue = CodeQualityIssue(
            ...     context="task1",
            ...     severity="high",
            ...     issue="Performance issue",
            ...     description="Inefficient query",
            ...     recommendation="Add indexes"
            ... )
            >>> result = SourceTransformer.issue_to_dict(issue)
            >>> result["severity"]
            'high'
        """
        return {
            "context": issue.context,
            "severity": issue.severity,
            "issue": issue.issue,
            "description": issue.description,
            "recommendation": issue.recommendation,
            "code_snippet": issue.code_snippet,
            "fix_snippet": issue.fix_snippet,
            "line_range": issue.line_range,
            "signals": issue.signals,
        }

    @staticmethod
    def get_task_source_type(task: dict[str, Any]) -> str | None:
        """
        Determine the source type of a task definition.

        Args:
            task: Task definition dictionary

        Returns:
            Source type string ("notebook", "python_file", "sql") or None

        Examples:
            >>> task = {"task_key": "task1", "notebook_task": {"notebook_path": "/path"}}
            >>> SourceTransformer.get_task_source_type(task)
            'notebook'
            >>> task = {"task_key": "task2", "spark_python_task": {"python_file": "main.py"}}
            >>> SourceTransformer.get_task_source_type(task)
            'python_file'
            >>> task = {"task_key": "task3", "sql_task": {"query": {"query": "SELECT 1"}}}
            >>> SourceTransformer.get_task_source_type(task)
            'sql'
            >>> task = {"task_key": "task4"}
            >>> SourceTransformer.get_task_source_type(task)
        """
        if "notebook_task" in task:
            return "notebook"
        elif "spark_python_task" in task:
            return "python_file"
        elif "sql_task" in task:
            return "sql"
        return None

    @staticmethod
    def build_source_result(task_sources: dict[str, Any]) -> dict[str, Any]:
        """
        Build consistent result structure for source code extraction.

        Args:
            task_sources: Dictionary of task sources

        Returns:
            Standardized result dictionary

        Examples:
            >>> sources = {"task1": {"type": "notebook", "source": "code"}}
            >>> result = SourceTransformer.build_source_result(sources)
            >>> result["has_source_code"]
            True
            >>> len(result["task_sources"])
            1
        """
        return {
            "results": {
                "task_sources": task_sources,
                "has_source_code": len(task_sources) > 0,
            },
            "task_sources": task_sources,
            "has_source_code": len(task_sources) > 0,
        }

    @staticmethod
    def build_empty_source_result(error: str | None = None) -> dict[str, Any]:
        """
        Build consistent empty result for source code extraction.

        Args:
            error: Optional error message

        Returns:
            Empty result dictionary

        Examples:
            >>> result = SourceTransformer.build_empty_source_result()
            >>> result["has_source_code"]
            False
            >>> result = SourceTransformer.build_empty_source_result("Not found")
            >>> result["error"]
            'Not found'
        """
        result: dict[str, Any] = {
            "task_sources": {},
            "has_source_code": False,
        }
        if error:
            result["error"] = error
            result["results"] = {
                "task_sources": {},
                "has_source_code": False,
                "error": error,
            }
        return result

    @staticmethod
    def build_analysis_result(
        issues: list[CodeQualityIssue], notes: list[str]
    ) -> dict[str, Any]:
        """
        Build consistent result structure for code analysis.

        Args:
            issues: List of CodeQualityIssue objects
            notes: List of analysis notes

        Returns:
            Standardized result dictionary

        Examples:
            >>> issues = [
            ...     CodeQualityIssue(
            ...         context="task1",
            ...         severity="high",
            ...         issue="Issue",
            ...         description="Desc",
            ...         recommendation="Fix"
            ...     )
            ... ]
            >>> result = SourceTransformer.build_analysis_result(issues, ["Note 1"])
            >>> len(result["code_quality_issues"])
            1
        """
        return {
            "results": {
                "code_quality_issues": [
                    SourceTransformer.issue_to_dict(issue) for issue in issues
                ],
                "code_quality_notes": notes,
            },
            "code_quality_issues": [
                SourceTransformer.issue_to_dict(issue) for issue in issues
            ],
            "code_quality_notes": notes,
        }

    @staticmethod
    def build_empty_analysis_result() -> dict[str, Any]:
        """
        Build consistent empty result for code analysis.

        Returns:
            Empty result dictionary

        Examples:
            >>> result = SourceTransformer.build_empty_analysis_result()
            >>> len(result["code_quality_issues"])
            0
        """
        return {
            "code_quality_issues": [],
            "code_quality_notes": [],
        }
