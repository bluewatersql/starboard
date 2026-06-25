# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Root cause synthesizer for diagnostic agent.

This module correlates tool outputs with exploration history to produce
a unified diagnosis with confidence-adjusted root causes.

Design reference: changes/diagnostic_agent/UNIFIED_DESIGN.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from starboard_server.tools.domain.diagnostic.models import (
    _PATTERN_TO_SYMPTOM,
    ExplorationSummary,
    PrimarySymptom,
)

# Confidence modifiers
TOOL_CONFIRMATION_BOOST = 0.15
TOOL_FAILURE_PENALTY = 0.0  # Don't penalize for failed tools
CONTRADICTION_PENALTY = 0.2
MULTI_PATTERN_BOOST = 0.1
MULTI_TOOL_BOOST = 0.05

# Pattern to recommended actions mapping
_PATTERN_ACTIONS: dict[str, list[str]] = {
    "java_heap_space": [
        "Increase driver/executor memory (spark.driver.memory, spark.executor.memory)",
        "Enable dynamic allocation for better resource utilization",
        "Reduce data processed per partition (increase parallelism)",
    ],
    "gc_overhead": [
        "Increase memory allocation",
        "Tune GC settings (G1GC recommended for large heaps)",
        "Reduce object creation in hot paths",
    ],
    "container_killed": [
        "Increase memory overhead (spark.executor.memoryOverhead)",
        "Check for memory leaks in user code",
        "Enable off-heap memory for large datasets",
    ],
    "shuffle_fetch_failed": [
        "Check network connectivity between executors",
        "Increase shuffle timeout (spark.network.timeout)",
        "Reduce shuffle data with pre-aggregation",
    ],
    "data_skew": [
        "Use salting to distribute skewed keys",
        "Enable adaptive query execution (AQE)",
        "Repartition data before joins",
    ],
    "uc_permission_denied": [
        "Grant necessary permissions on the object",
        "Check effective permissions for the user",
        "Verify catalog/schema/table path is correct",
    ],
    "task_not_serializable": [
        "Make closures serializable",
        "Use broadcast variables for shared state",
        "Avoid referencing non-serializable objects in transformations",
    ],
}


@dataclass
class ToolOutput:
    """Represents output from a diagnostic tool call.

    Captures the tool result and metadata for synthesis.
    """

    tool_name: str
    """Name of the tool that was called."""

    run_id: str | None
    """Run ID if applicable (may be None for cluster-level tools)."""

    result: dict[str, Any] | None
    """Tool result (None if tool failed)."""

    latency_ms: int
    """Tool call latency in milliseconds."""

    error: str | None = None
    """Error message if tool failed."""

    def is_successful(self) -> bool:
        """Check if tool call succeeded."""
        return self.error is None and self.result is not None


@dataclass
class SynthesisResult:
    """Result of root cause synthesis.

    Aggregates evidence from exploration and tools into a unified diagnosis.
    """

    primary_symptom: PrimarySymptom
    """The identified primary symptom."""

    root_causes: list[str]
    """Prioritized list of root causes."""

    confidence: float
    """Final synthesis confidence (0.0 to 1.0)."""

    evidence_chain: list[str]
    """Chain of evidence supporting the diagnosis."""

    recommended_actions: list[str]
    """Actionable recommendations."""

    tool_calls_made: list[str] = field(default_factory=list)
    """Tools that were called during synthesis."""

    patterns_matched: list[str] = field(default_factory=list)
    """Patterns that matched during exploration."""

    steps_completed: int = 0
    """Number of exploration steps completed."""

    def to_exploration_summary(self) -> ExplorationSummary:
        """Convert to ExplorationSummary for handoff.

        Returns:
            ExplorationSummary containing synthesis metadata.
        """
        return ExplorationSummary(
            steps_completed=self.steps_completed,
            final_confidence=self.confidence,
            strategies_used=["synthesize"],  # Final synthesis step
            patterns_matched=self.patterns_matched if self.patterns_matched else None,
            tool_calls_made=self.tool_calls_made if self.tool_calls_made else None,
        )


@dataclass
class RootCauseSynthesizer:
    """Synthesizes root causes from exploration and tool outputs.

    Correlates evidence from:
    - Pattern matching results
    - Evidence extraction
    - Tool call outputs (ONLINE mode)

    Produces a unified diagnosis with confidence adjustments.
    """

    def synthesize(
        self,
        tool_outputs: list[ToolOutput],
        exploration_findings: dict[str, Any],
    ) -> SynthesisResult:
        """Synthesize root cause from exploration and tool outputs.

        Args:
            tool_outputs: List of tool outputs from ONLINE mode.
            exploration_findings: Dictionary with exploration results:
                - artifact_type: Type of artifact analyzed
                - matched_patterns: List of pattern IDs that matched
                - evidence_refs: List of evidence references
                - initial_confidence: Starting confidence from exploration

        Returns:
            SynthesisResult with unified diagnosis.
        """
        matched_patterns = exploration_findings.get("matched_patterns", [])
        initial_confidence = exploration_findings.get("initial_confidence", 0.5)
        evidence_refs = exploration_findings.get("evidence_refs", [])

        # Determine primary symptom from patterns
        symptom = self._determine_symptom(matched_patterns)

        # Calculate confidence with modifiers
        confidence = self._calculate_confidence(
            initial_confidence, matched_patterns, tool_outputs
        )

        # Build root causes from patterns and tool outputs
        root_causes = self._build_root_causes(matched_patterns, tool_outputs)

        # Build evidence chain
        evidence_chain = self._build_evidence_chain(evidence_refs, tool_outputs)

        # Get recommended actions
        recommended_actions = self._get_recommended_actions(matched_patterns)

        # Track tool calls
        tool_calls_made = [
            output.tool_name for output in tool_outputs if output.is_successful()
        ]

        return SynthesisResult(
            primary_symptom=symptom,
            root_causes=root_causes,
            confidence=min(confidence, 0.95),  # Cap at 95%
            evidence_chain=evidence_chain,
            recommended_actions=recommended_actions,
            tool_calls_made=tool_calls_made,
            patterns_matched=matched_patterns,
            steps_completed=len(evidence_refs) + len(tool_outputs),
        )

    def _determine_symptom(self, matched_patterns: list[str]) -> PrimarySymptom:
        """Determine primary symptom from matched patterns.

        Args:
            matched_patterns: List of pattern IDs.

        Returns:
            Primary symptom enum value.
        """
        for pattern_id in matched_patterns:
            if pattern_id in _PATTERN_TO_SYMPTOM:
                return _PATTERN_TO_SYMPTOM[pattern_id]
        return PrimarySymptom.UNKNOWN

    def _calculate_confidence(
        self,
        initial_confidence: float,
        matched_patterns: list[str],
        tool_outputs: list[ToolOutput],
    ) -> float:
        """Calculate final confidence with modifiers.

        Args:
            initial_confidence: Starting confidence from exploration.
            matched_patterns: List of matched pattern IDs.
            tool_outputs: Tool outputs for confirmation/contradiction.

        Returns:
            Adjusted confidence value.
        """
        confidence = initial_confidence

        # Boost for multiple correlated patterns
        if len(matched_patterns) >= 2:
            confidence += MULTI_PATTERN_BOOST
        if len(matched_patterns) >= 3:
            confidence += MULTI_PATTERN_BOOST

        # Process tool outputs
        confirming_tools = 0
        contradicting_tools = 0

        for output in tool_outputs:
            if not output.is_successful():
                continue  # Skip failed tools

            # Check if tool confirms or contradicts
            if self._tool_confirms_patterns(output, matched_patterns):
                confirming_tools += 1
            elif self._tool_contradicts_patterns(output, matched_patterns):
                contradicting_tools += 1

        # Apply tool modifiers
        if confirming_tools > 0:
            confidence += TOOL_CONFIRMATION_BOOST
            if confirming_tools >= 2:
                confidence += MULTI_TOOL_BOOST

        if contradicting_tools > 0:
            confidence -= CONTRADICTION_PENALTY

        return max(0.0, min(confidence, 1.0))

    def _tool_confirms_patterns(
        self, output: ToolOutput, matched_patterns: list[str]
    ) -> bool:
        """Check if tool output confirms matched patterns.

        Args:
            output: Tool output to check.
            matched_patterns: Patterns to confirm.

        Returns:
            True if tool confirms patterns.
        """
        if not output.result:
            return False

        result = output.result
        result_str = str(result).lower()

        # Check for failure state
        state = result.get("state", "")
        if isinstance(state, str) and state.upper() == "FAILED":
            return True

        # Check for error indicators
        error = result.get("error", "") or ""
        summary = result.get("summary", "") or ""  # Aggregated task errors
        combined_error = f"{error} {summary}".lower()

        if combined_error.strip():
            # Check if error matches any pattern
            for pattern in matched_patterns:
                if pattern == "java_heap_space" and "outofmemory" in combined_error:
                    return True
                if pattern == "gc_overhead" and "gc overhead" in combined_error:
                    return True
                if pattern == "shuffle_fetch_failed" and "shuffle" in combined_error:
                    return True
                if pattern == "uc_permission_denied" and "permission" in combined_error:
                    return True
                if (
                    pattern == "task_not_serializable"
                    and "serializable" in combined_error
                ):
                    return True
                if pattern == "executor_lost" and (
                    "executor lost" in combined_error
                    or "lost executor" in combined_error
                ):
                    return True
                if pattern == "data_skew" and "skew" in combined_error:
                    return True

        # Check task-level errors from get_run_output
        tasks = result.get("tasks", [])
        failed_tasks = result.get("failed_tasks", [])
        if tasks or failed_tasks:
            for task in tasks + failed_tasks:
                task_error = str(task.get("error", "")).lower()
                if task_error:
                    for pattern in matched_patterns:
                        if pattern == "java_heap_space" and "outofmemory" in task_error:
                            return True
                        if (
                            pattern == "shuffle_fetch_failed"
                            and "shuffle" in task_error
                        ):
                            return True
                        if (
                            pattern == "task_not_serializable"
                            and "serializable" in task_error
                        ):
                            return True

        # Check for OOM events in cluster events
        events = result.get("events", [])
        for event in events:
            event_type = str(event.get("type", ""))
            if "OOM" in event_type or "MEMORY" in event_type:
                return True

        # Generic error check
        return "error" in result_str or "failed" in result_str

    def _tool_contradicts_patterns(
        self, output: ToolOutput, matched_patterns: list[str]
    ) -> bool:
        """Check if tool output contradicts matched patterns.

        Args:
            output: Tool output to check.
            matched_patterns: Patterns being checked.

        Returns:
            True if tool contradicts (e.g., shows success when expecting failure).
        """
        if not output.result:
            return False

        result = output.result
        state = result.get("state", "").upper()

        # If we matched failure patterns but tool shows success
        return state == "SUCCESS" and bool(matched_patterns)

    def _build_root_causes(
        self, matched_patterns: list[str], tool_outputs: list[ToolOutput]
    ) -> list[str]:
        """Build prioritized list of root causes.

        Args:
            matched_patterns: Matched pattern IDs.
            tool_outputs: Tool outputs with additional context.

        Returns:
            List of root cause descriptions.
        """
        causes: list[str] = []
        seen_errors: set[str] = set()

        # Add pattern-based causes
        pattern_causes = {
            "java_heap_space": "Java heap space exhausted",
            "gc_overhead": "GC overhead limit exceeded",
            "container_killed": "Container killed by resource manager",
            "shuffle_fetch_failed": "Shuffle fetch operation failed",
            "data_skew": "Data skew causing uneven partition sizes",
            "uc_permission_denied": "Permission denied on Unity Catalog object",
            "task_not_serializable": "Task contains non-serializable objects",
            "executor_lost": "Executor lost during job execution",
            "delta_concurrent_write": "Concurrent write conflict on Delta table",
            "disk_space_exhausted": "Disk space exhausted on worker node",
            "s3_access_denied": "Access denied to S3/cloud storage",
            "network_throttling": "Network throttling or connectivity issues",
            "python_worker_crash": "Python worker process crashed",
        }

        for pattern in matched_patterns:
            if pattern in pattern_causes:
                causes.append(pattern_causes[pattern])

        # Add tool-derived causes
        for output in tool_outputs:
            if output.is_successful() and output.result:
                result = output.result

                # Check top-level error
                error = result.get("error", "")
                if error and error not in seen_errors:
                    causes.append(f"Tool confirmed: {error[:150]}")
                    seen_errors.add(error)

                # Check summary (aggregated task errors from get_run_output)
                summary = result.get("summary", "")
                if summary and summary not in seen_errors:
                    # Extract first line of summary for brevity
                    first_error = summary.split("\n")[0]
                    if first_error and len(first_error) > 10:
                        causes.append(f"Task failure: {first_error[:150]}")
                        seen_errors.add(summary)

                # Check individual task errors for more detail
                tasks = result.get("tasks", [])
                for task in tasks[:3]:  # Limit to first 3 tasks
                    task_key = task.get("task_key", "unknown")
                    task_error = task.get("error", "")
                    if task_error and task_error not in seen_errors:
                        causes.append(f"Task [{task_key}]: {task_error[:100]}")
                        seen_errors.add(task_error)

        # Ensure at least one cause
        if not causes:
            causes.append("Root cause undetermined - requires further investigation")

        return causes

    def _build_evidence_chain(
        self, evidence_refs: list[str], tool_outputs: list[ToolOutput]
    ) -> list[str]:
        """Build chain of evidence supporting diagnosis.

        Args:
            evidence_refs: Evidence window references.
            tool_outputs: Tool outputs.

        Returns:
            List of evidence descriptions.
        """
        chain: list[str] = []

        # Add exploration evidence
        for ref in evidence_refs:
            chain.append(f"Evidence from artifact: {ref}")

        # Add tool evidence
        for output in tool_outputs:
            if output.is_successful():
                chain.append(f"Tool {output.tool_name} confirmed findings")
            elif output.error:
                chain.append(f"Tool {output.tool_name} failed: {output.error}")

        return chain

    def _get_recommended_actions(self, matched_patterns: list[str]) -> list[str]:
        """Get recommended actions for matched patterns.

        Args:
            matched_patterns: List of pattern IDs.

        Returns:
            List of recommended actions.
        """
        actions: list[str] = []
        seen: set[str] = set()

        for pattern in matched_patterns:
            pattern_actions = _PATTERN_ACTIONS.get(pattern, [])
            for action in pattern_actions:
                if action not in seen:
                    actions.append(action)
                    seen.add(action)

        # Ensure at least one action
        if not actions:
            actions.append("Review logs and error details for more specific guidance")

        return actions
