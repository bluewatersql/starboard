# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
ExplorationToolAdapter - Exposes exploration strategies as LLM-callable tools.

This module provides:
- Tool definitions for each exploration strategy
- Execution of exploration strategies via tool calls
- Result formatting for LLM consumption
- Factory function for easy integration

Design reference:
- changes/diagnostic_agent/IMPLEMENTATION_CHECKLIST.md (LLM Step Selection)
- changes/diagnostic_agent/UNIFIED_DESIGN.md (Tool System)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from starboard_server.tools.domain.diagnostic.artifact_explorer import (
        ArtifactExplorer,
    )

from starboard_server.tools.domain.diagnostic.artifact_explorer import (
    ExplorationStrategy,
)

# Tool name prefix for exploration tools
_TOOL_PREFIX = "explore_"


def _strategy_to_tool_name(strategy: ExplorationStrategy) -> str:
    """Convert strategy enum to tool name."""
    return f"{_TOOL_PREFIX}{strategy.value}"


def _tool_name_to_strategy(tool_name: str) -> ExplorationStrategy | None:
    """Convert tool name to strategy enum."""
    if not tool_name.startswith(_TOOL_PREFIX):
        return None
    strategy_value = tool_name[len(_TOOL_PREFIX) :]
    try:
        return ExplorationStrategy(strategy_value)
    except ValueError:
        return None


# Tool descriptions for each strategy
_STRATEGY_DESCRIPTIONS: dict[ExplorationStrategy, str] = {
    ExplorationStrategy.DETECT_TYPE: (
        "Detect the type of artifact (error_message, logs, stack_trace, code, etc.) "
        "and programming language if applicable. Use this first on any new artifact."
    ),
    ExplorationStrategy.EXTRACT_EVIDENCE: (
        "Extract evidence windows from the artifact - key error messages, stack traces, "
        "and diagnostic information. Returns stable IDs for citation."
    ),
    ExplorationStrategy.EXTRACT_IDS: (
        "Extract Databricks IDs (job_id, cluster_id, run_id, etc.) from the artifact. "
        "Determines if ONLINE mode tools can be used."
    ),
    ExplorationStrategy.MATCH_PATTERNS: (
        "Match the artifact against known error patterns (OOM, shuffle failures, etc.). "
        "Returns matched patterns with confidence scores."
    ),
    ExplorationStrategy.EXPAND_WINDOW: (
        "Expand context around evidence windows for better analysis. "
        "Use when initial evidence is insufficient."
    ),
    ExplorationStrategy.SUMMARIZE: (
        "Summarize large artifacts to key evidence for token efficiency. "
        "Use on artifacts > 1000 lines before detailed analysis."
    ),
    ExplorationStrategy.CORRELATE: (
        "Cross-reference patterns and evidence to disambiguate root cause. "
        "Use when multiple patterns match or confidence is low."
    ),
}


class ExplorationToolAdapter:
    """Adapts exploration strategies as LLM-callable tools.

    This adapter wraps an ArtifactExplorer and exposes its exploration
    strategies as tools that can be called by the LLM agent.

    Example:
        >>> from starboard_server.tools.domain.diagnostic.artifact_explorer import ArtifactExplorer
        >>> from starboard_server.tools.domain.diagnostic.artifact_detector import ArtifactDetector
        >>> from starboard_server.tools.domain.diagnostic.evidence_extractor import EvidenceWindowExtractor
        >>> from starboard_server.tools.domain.diagnostic.context_extractor import DatabricksContextExtractor
        >>>
        >>> explorer = ArtifactExplorer(
        ...     detector=ArtifactDetector(),
        ...     evidence_extractor=EvidenceWindowExtractor(),
        ...     context_extractor=DatabricksContextExtractor(),
        ... )
        >>> adapter = ExplorationToolAdapter(explorer)
        >>>
        >>> # Get tool definitions for LLM
        >>> tools = adapter.get_tool_definitions()
        >>> print(tools[0]["name"])
        'explore_detect_type'
        >>>
        >>> # Execute a tool
        >>> result = adapter.execute("explore_detect_type", {"artifact": "Error msg"})
        >>> print(result["artifact_type"])
        'error_message'
    """

    def __init__(self, explorer: ArtifactExplorer) -> None:
        """Initialize the adapter.

        Args:
            explorer: ArtifactExplorer instance to wrap.
        """
        self._explorer = explorer
        self._supported_strategies = [
            ExplorationStrategy.DETECT_TYPE,
            ExplorationStrategy.EXTRACT_EVIDENCE,
            ExplorationStrategy.EXTRACT_IDS,
            ExplorationStrategy.MATCH_PATTERNS,
            ExplorationStrategy.EXPAND_WINDOW,
            ExplorationStrategy.SUMMARIZE,
            ExplorationStrategy.CORRELATE,
        ]

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Get tool definitions for all exploration strategies.

        Returns:
            List of tool definition dicts with name, description, parameters.
        """
        tools: list[dict[str, Any]] = []

        for strategy in self._supported_strategies:
            # Skip match_patterns if no pattern matcher
            if (
                strategy == ExplorationStrategy.MATCH_PATTERNS
                and self._explorer._pattern_matcher is None
            ):
                continue

            tool_name = _strategy_to_tool_name(strategy)
            description = _STRATEGY_DESCRIPTIONS.get(
                strategy, f"Explore: {strategy.value}"
            )

            tool_def = {
                "name": tool_name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "artifact": {
                            "type": "string",
                            "description": "The artifact text to explore (logs, error, code).",
                        },
                    },
                    "required": ["artifact"],
                },
            }
            tools.append(tool_def)

        return tools

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute an exploration tool.

        Args:
            tool_name: Name of the tool to execute (e.g., "explore_detect_type").
            arguments: Tool arguments, must include "artifact".

        Returns:
            Dict with exploration results.

        Raises:
            ValueError: If tool name is unknown or artifact is missing.
        """
        # Validate artifact
        artifact = arguments.get("artifact")
        if not artifact:
            raise ValueError("Missing required argument: artifact")

        # Get strategy
        strategy = self._get_strategy(tool_name)
        if strategy is None:
            raise ValueError(f"Unknown exploration tool: {tool_name}")

        # Execute exploration
        result = self._explorer.explore(artifact, strategy=strategy)

        # Format result for LLM
        return self._format_result(result)

    def _get_strategy(self, tool_name: str) -> ExplorationStrategy | None:
        """Get exploration strategy for a tool name."""
        return _tool_name_to_strategy(tool_name)

    def _format_result(self, result: Any) -> dict[str, Any]:
        """Format exploration result for LLM consumption.

        Args:
            result: ExplorationResult from explorer.

        Returns:
            Dict with findings, confidence, and next steps.
        """
        from starboard_server.tools.domain.diagnostic.artifact_explorer import (
            ExplorationResult,
        )

        if not isinstance(result, ExplorationResult):
            return {"error": "Unexpected result type"}

        formatted = {
            **result.findings,
            "confidence": result.confidence,
            "next_steps": [s.value for s in result.next_steps],
            "evidence_refs": result.evidence_refs,
        }

        # Add synthesis recommendation for high confidence
        if result.confidence >= 0.8:
            formatted["should_synthesize"] = True
            formatted["synthesis_note"] = (
                "Confidence is high enough to synthesize a diagnosis. "
                "Consider calling 'complete' with findings."
            )

        return formatted


def create_exploration_tools(
    explorer: ArtifactExplorer,
) -> tuple[list[dict[str, Any]], Callable[[str, dict[str, Any]], dict[str, Any]]]:
    """Factory function to create exploration tools and executor.

    This is a convenience function that creates an ExplorationToolAdapter
    and returns both the tool definitions and an executor function.

    Args:
        explorer: ArtifactExplorer instance.

    Returns:
        Tuple of (tool_definitions, executor_function).

    Example:
        >>> tools, executor = create_exploration_tools(explorer)
        >>> result = executor("explore_detect_type", {"artifact": "Error"})
    """
    adapter = ExplorationToolAdapter(explorer)
    return adapter.get_tool_definitions(), adapter.execute
