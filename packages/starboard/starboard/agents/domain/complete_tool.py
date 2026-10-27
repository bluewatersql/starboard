# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""
Complete tool wrapper for LLM output unwrapping.

This module extracts the CompleteToolWrapper from DomainAgent,
handling OpenAI strict mode unwrapping and LLM output normalization
for the completion tool.

Responsibilities:
- Unwrap OpenAI strict mode {"response": {...}} wrappers
- Normalize nested "report" and "analysis" structures
- Parse JSON string values in report/analysis fields
- Register the complete tool with the tool registry

Does NOT:
- Execute reasoning or tools (that's ReasoningEngine/ToolExecutor)
- Emit events (that's EventStreamer)
- Format outputs (that's OutputBuilder)
"""

from __future__ import annotations

import json
from typing import Any

from starboard.agents.tools import ToolMetadata, ToolRegistry
from starboard.infra.observability.logging import get_logger
from starboard.infra.serialization import json_loads

logger = get_logger(__name__)


class CompleteToolWrapper:
    """
    Wrapper for the 'complete' tool that normalizes LLM output.

    Handles various LLM output quirks:
    - OpenAI strict mode wraps in {"response": {...}}
    - LLM sometimes nests under "report" key
    - LLM sometimes returns JSON strings instead of dicts
    - LLM sometimes double-nests analysis structures

    Example:
        >>> wrapper = CompleteToolWrapper(domain="query", metadata=tool_metadata)
        >>> result = await wrapper.execute(
        ...     response={"summary": {...}, "next_steps": [...]}
        ... )
        >>> assert result["completed"] is True
    """

    def __init__(self, domain: str, metadata: ToolMetadata):
        """
        Initialize complete tool wrapper.

        Args:
            domain: Agent domain (e.g., "query", "job", "cluster")
            metadata: Tool metadata for registration
        """
        self.domain = domain
        self.metadata = metadata

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        """Execute complete tool with OpenAI strict mode unwrapping."""

        # LOG: Capture raw LLM output before any processing
        if "visualization" in kwargs:
            viz = kwargs["visualization"]
            if isinstance(viz, dict) and "chart_config" in viz:
                chart_config = viz["chart_config"]
                logger.debug(
                    "complete_tool_llm_raw_output",
                    has_visualization=True,
                    has_chart_config=chart_config is not None,
                    chart_config_type=type(chart_config).__name__
                    if chart_config
                    else None,
                    chart_config_keys=list(chart_config.keys())
                    if isinstance(chart_config, dict)
                    else [],
                    chart_config_full=chart_config,
                )

        # OpenAI strict mode wraps Pydantic models in {"response": {...}}
        # Unwrap if present (check for response key and that it's a dict)
        if "response" in kwargs and isinstance(kwargs.get("response"), dict):
            # Only unwrap if the response dict contains the expected report fields
            response_data = kwargs["response"]
            expected_base_fields = {"summary", "next_steps"}
            if expected_base_fields.intersection(response_data.keys()):
                logger.debug(
                    "unwrapping_openai_strict_mode_response",
                    domain=self.domain,
                )
                kwargs = response_data

        # BUGFIX: LLM sometimes nests everything under "report" or "analysis" key
        # Expected: {summary: {...}, analysis: {findings: [...]}, next_steps: [...]}
        # Actual: {report: {summary: {...}, analysis: {...}}, next_steps: [...]}
        # Or: {report: "<json_string>"} (report as JSON string!)
        # Or: {analysis: {summary: {...}, findings: [...]}, next_steps: [...]}

        # Check for "report" wrapper first (most common)
        if "report" in kwargs:
            report_data = kwargs["report"]

            # Case 1: Report is a JSON string - parse it first
            if isinstance(report_data, str):
                try:
                    report_data = json_loads(report_data)
                    logger.debug(
                        "parsed_json_string_report",
                        domain=self.domain,
                        note="LLM returned report as JSON string, parsed successfully",
                    )
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(
                        "failed_to_parse_json_string_report",
                        domain=self.domain,
                        error=str(e),
                    )
                    # Keep the string as-is if parsing fails
                    pass

            # Case 2: Report is a dict - unwrap it
            if isinstance(report_data, dict):  # noqa: SIM102
                if (
                    "summary" in report_data
                    or "analysis" in report_data
                    or "report_type" in report_data
                ):
                    logger.debug(
                        "unwrapping_report_wrapper",
                        domain=self.domain,
                        note="LLM wrapped everything in 'report' key, flattening to root",
                    )
                    # Extract all fields from report to root level
                    for key, value in report_data.items():
                        if key not in kwargs:  # Don't overwrite existing root keys
                            kwargs[key] = value
                    # Remove the report wrapper
                    del kwargs["report"]

        # Then check for nested "analysis" structure
        elif "analysis" in kwargs:
            analysis = kwargs["analysis"]

            # BUGFIX: LLM sometimes returns analysis as a JSON string
            if isinstance(analysis, str):
                try:
                    kwargs["analysis"] = json_loads(analysis)
                    analysis = kwargs["analysis"]  # Update reference
                except (json.JSONDecodeError, ValueError):
                    # Keep the string as-is if parsing fails
                    pass

            # BUGFIX: LLM sometimes double-nests: {analysis: {analysis: {findings: [...]}, next_steps: [...], summary: {...}}}
            if isinstance(analysis, dict) and "analysis" in analysis:
                # Extract the inner analysis (has findings, etc)
                inner_analysis = analysis["analysis"]

                # Preserve next_steps and summary from outer analysis if they exist
                if "next_steps" in analysis and "next_steps" not in kwargs:
                    kwargs["next_steps"] = analysis["next_steps"]
                if "summary" in analysis and "summary" not in kwargs:
                    kwargs["summary"] = analysis["summary"]

                # Use inner analysis for findings/query_rewrite
                kwargs["analysis"] = inner_analysis
                analysis = inner_analysis

            # If summary is inside analysis but not at root, flatten it
            if (
                isinstance(analysis, dict)
                and "summary" in analysis
                and "summary" not in kwargs
            ):
                # Extract summary to root level
                kwargs["summary"] = analysis["summary"]
                # Keep analysis for findings/other fields
                # But remove summary from it since we moved it up
                analysis_copy = dict(analysis)
                del analysis_copy["summary"]
                kwargs["analysis"] = analysis_copy

        kwargs["completed"] = True
        if "report_type" not in kwargs:
            kwargs["report_type"] = (
                "analytics" if self.domain == "analytics" else "advisor"
            )
        return kwargs


def register_complete_tool(
    domain: str,
    tool_registry: ToolRegistry,
) -> None:
    """
    Register the 'complete' tool for a domain agent.

    Creates the tool metadata with the appropriate optimization schema
    and registers a CompleteToolWrapper instance.

    Args:
        domain: Agent domain (e.g., "query", "job", "cluster")
        tool_registry: Tool registry to register the tool with

    Raises:
        ValueError: If domain is not a valid routable domain
    """
    from starboard.agents.output.optimization_schemas import (
        get_optimization_schema,
    )
    from starboard.prompts.base import ROUTABLE_DOMAINS

    if not domain or domain not in ROUTABLE_DOMAINS:
        raise ValueError(f"Invalid domain: {domain}")

    schema = get_optimization_schema(
        domain=domain,  # type: ignore
        include_query_rewrite=(domain == "query"),
    )

    complete_tool = ToolMetadata(
        name="complete",
        description="Call this when analysis is complete with a comprehensive report.",
        parameters=schema,
    )

    wrapper = CompleteToolWrapper(domain, complete_tool)

    if "complete" not in tool_registry._tools:
        tool_registry.register("complete", wrapper)
