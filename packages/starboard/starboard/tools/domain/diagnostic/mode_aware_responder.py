# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
ModeAwareResponder - Adapts diagnostic responses based on context mode.

Provides different response strategies based on whether we're in:
- ONLINE mode: Can fetch additional context via tools
- OFFLINE mode: Must provide manual guidance
- HYBRID mode: Partial context available
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from starboard.tools.domain.diagnostic.context_extractor import ContextMode


@dataclass
class OfflineGuidance:
    """Guidance for manual investigation when context is unavailable.

    Attributes:
        investigation_steps: Step-by-step investigation guide.
        questions_to_answer: Questions the user should investigate.
        data_to_collect: Specific data points to collect.
        where_to_look: Locations to find relevant information.
    """

    investigation_steps: list[str] = field(default_factory=list)
    questions_to_answer: list[str] = field(default_factory=list)
    data_to_collect: list[str] = field(default_factory=list)
    where_to_look: list[str] = field(default_factory=list)


@dataclass
class ModeAwareResponse:
    """A response adapted to the context mode.

    Attributes:
        mode: The context mode (ONLINE/OFFLINE/HYBRID).
        diagnosis: The diagnostic finding.
        can_fetch_context: Whether additional context can be fetched.
        suggested_tool_calls: Tools to call for more context (ONLINE mode).
        offline_guidance: Manual investigation guidance (OFFLINE mode).
        partial_context_note: Note about partial context (HYBRID mode).
    """

    mode: ContextMode
    diagnosis: str
    can_fetch_context: bool = False
    suggested_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    offline_guidance: OfflineGuidance | None = None
    partial_context_note: str | None = None


class ModeAwareResponder:
    """Adapts diagnostic responses based on context mode.

    Creates appropriate response structures with tool suggestions
    for ONLINE mode or manual guidance for OFFLINE mode.
    """

    # Tool suggestions by ID type
    _CLUSTER_TOOLS = [
        {"tool": "get_cluster_events", "purpose": "Fetch cluster event logs"},
        {"tool": "get_cluster_config", "purpose": "Check cluster configuration"},
    ]

    _JOB_TOOLS = [
        {"tool": "get_job_run_output", "purpose": "Fetch job run output and logs"},
        {"tool": "get_job_config", "purpose": "Check job configuration"},
    ]

    _QUERY_TOOLS = [
        {"tool": "get_query_history", "purpose": "Fetch query execution history"},
        {"tool": "get_query_plan", "purpose": "Analyze query execution plan"},
    ]

    _WAREHOUSE_TOOLS = [
        {"tool": "get_warehouse_config", "purpose": "Check warehouse configuration"},
    ]

    # Diagnosis-specific investigation steps
    _MEMORY_INVESTIGATION = [
        "Check Spark UI for memory usage patterns",
        "Review GC logs for memory pressure indicators",
        "Examine executor memory configuration",
        "Look for large broadcast variables or collect() calls",
        "Check for data skew causing memory concentration",
    ]

    _NETWORK_INVESTIGATION = [
        "Verify network connectivity between cluster nodes",
        "Check for firewall or security group restrictions",
        "Review DNS resolution and timeouts",
        "Examine shuffle service health",
        "Check for network throttling or rate limiting",
    ]

    _PERMISSION_INVESTIGATION = [
        "Verify user permissions on the resource",
        "Check Unity Catalog grants and privileges",
        "Review service principal access",
        "Confirm the resource exists and is accessible",
        "Check for recent permission changes",
    ]

    _DISK_INVESTIGATION = [
        "Check disk space on cluster nodes",
        "Review shuffle data size and spill metrics",
        "Examine temporary file cleanup policies",
        "Check for large cache operations",
    ]

    _DEFAULT_INVESTIGATION = [
        "Review the full error logs for additional context",
        "Check cluster health and resource utilization",
        "Examine job configuration and dependencies",
        "Look for recent changes to code or configuration",
        "Check for concurrent jobs competing for resources",
    ]

    def create_response(
        self,
        mode: ContextMode,
        diagnosis: str,
        available_ids: dict[str, str | None],
    ) -> ModeAwareResponse:
        """Create a mode-aware response.

        Args:
            mode: The context mode (ONLINE/OFFLINE/HYBRID).
            diagnosis: The diagnostic finding.
            available_ids: Available Databricks IDs.

        Returns:
            ModeAwareResponse with appropriate content.
        """
        if mode == ContextMode.ONLINE:
            return self._create_online_response(diagnosis, available_ids)
        elif mode == ContextMode.OFFLINE:
            return self._create_offline_response(diagnosis, available_ids)
        else:  # HYBRID
            return self._create_hybrid_response(diagnosis, available_ids)

    def _create_online_response(
        self, diagnosis: str, available_ids: dict[str, str | None]
    ) -> ModeAwareResponse:
        """Create response for ONLINE mode."""
        tool_calls = self._suggest_tools(available_ids)

        return ModeAwareResponse(
            mode=ContextMode.ONLINE,
            diagnosis=diagnosis,
            can_fetch_context=True,
            suggested_tool_calls=tool_calls,
            offline_guidance=None,
        )

    def _create_offline_response(
        self, diagnosis: str, _available_ids: dict[str, str | None]
    ) -> ModeAwareResponse:
        """Create response for OFFLINE mode."""
        guidance = self._create_guidance(diagnosis)

        return ModeAwareResponse(
            mode=ContextMode.OFFLINE,
            diagnosis=diagnosis,
            can_fetch_context=False,
            suggested_tool_calls=[],
            offline_guidance=guidance,
        )

    def _create_hybrid_response(
        self, diagnosis: str, available_ids: dict[str, str | None]
    ) -> ModeAwareResponse:
        """Create response for HYBRID mode."""
        tool_calls = self._suggest_tools(available_ids)
        guidance = self._create_guidance(diagnosis)

        # Create note about partial context
        available = [k for k, v in available_ids.items() if v]
        missing = self._identify_missing_ids(available_ids)

        note = f"Some context is available ({', '.join(available) if available else 'none'})"
        if missing:
            note += f". Missing: {', '.join(missing)}"

        return ModeAwareResponse(
            mode=ContextMode.HYBRID,
            diagnosis=diagnosis,
            can_fetch_context=True,
            suggested_tool_calls=tool_calls,
            offline_guidance=guidance,
            partial_context_note=note,
        )

    def _suggest_tools(
        self, available_ids: dict[str, str | None]
    ) -> list[dict[str, Any]]:
        """Suggest tools based on available IDs."""
        tools: list[dict[str, Any]] = []

        # Filter to non-None IDs
        valid_ids = {k: v for k, v in available_ids.items() if v}

        if "cluster_id" in valid_ids:
            tools.extend(self._CLUSTER_TOOLS)

        if "job_id" in valid_ids or "run_id" in valid_ids:
            tools.extend(self._JOB_TOOLS)

        if "query_id" in valid_ids:
            tools.extend(self._QUERY_TOOLS)

        if "warehouse_id" in valid_ids:
            tools.extend(self._WAREHOUSE_TOOLS)

        return tools

    def _create_guidance(self, diagnosis: str) -> OfflineGuidance:
        """Create offline guidance based on diagnosis."""
        diagnosis_lower = diagnosis.lower()

        # Select investigation steps based on diagnosis
        if any(kw in diagnosis_lower for kw in ["memory", "oom", "heap", "gc"]):
            steps = self._MEMORY_INVESTIGATION.copy()
        elif any(
            kw in diagnosis_lower
            for kw in ["network", "connection", "timeout", "shuffle"]
        ):
            steps = self._NETWORK_INVESTIGATION.copy()
        elif any(
            kw in diagnosis_lower
            for kw in ["permission", "denied", "access", "unauthorized"]
        ):
            steps = self._PERMISSION_INVESTIGATION.copy()
        elif any(kw in diagnosis_lower for kw in ["disk", "storage", "space"]):
            steps = self._DISK_INVESTIGATION.copy()
        else:
            steps = self._DEFAULT_INVESTIGATION.copy()

        # Create questions
        questions = self._generate_questions(diagnosis)

        # Create data to collect
        data_to_collect = [
            "Full error message and stack trace",
            "Job/cluster configuration details",
            "Time of failure and duration before failure",
            "Any recent changes to code or configuration",
        ]

        # Where to look
        where_to_look = [
            "Databricks workspace > Jobs > Run details",
            "Databricks workspace > Clusters > Event log",
            "Spark UI > Stages > Task details",
            "Driver logs and executor logs",
        ]

        return OfflineGuidance(
            investigation_steps=steps,
            questions_to_answer=questions,
            data_to_collect=data_to_collect,
            where_to_look=where_to_look,
        )

    def _generate_questions(self, diagnosis: str) -> list[str]:
        """Generate diagnostic questions."""
        diagnosis_lower = diagnosis.lower()

        questions = [
            "Is this a new issue or has it happened before?",
            "What was the job doing when the error occurred?",
        ]

        if "memory" in diagnosis_lower or "oom" in diagnosis_lower:
            questions.extend(
                [
                    "What is the current executor memory configuration?",
                    "How large is the dataset being processed?",
                    "Are there any collect() or toPandas() calls?",
                ]
            )
        elif "network" in diagnosis_lower or "connection" in diagnosis_lower:
            questions.extend(
                [
                    "Are other jobs on this cluster working correctly?",
                    "Were there any recent network or firewall changes?",
                ]
            )
        elif "permission" in diagnosis_lower:
            questions.extend(
                [
                    "What resource is being accessed?",
                    "What user or service principal is running the job?",
                ]
            )

        return questions

    def _identify_missing_ids(self, available_ids: dict[str, str | None]) -> list[str]:
        """Identify potentially useful missing IDs."""
        missing = []
        valid_ids = {k for k, v in available_ids.items() if v}

        # Suggest missing IDs that would be helpful
        if "cluster_id" not in valid_ids:
            missing.append("cluster_id")
        if "job_id" not in valid_ids and "run_id" not in valid_ids:
            missing.append("job_id or run_id")

        return missing
