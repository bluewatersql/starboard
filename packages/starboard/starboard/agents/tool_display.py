# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unified tool display configuration.

Single source of truth for all tool UI/display metadata including:
- Friendly names for tool call cards
- Thinking step titles and descriptions
- Hidden tool flags

Usage:
    >>> from starboard.agents.tool_display import get_tool_display
    >>> display = get_tool_display("resolve_query")
    >>> display.friendly_name
    'Resolving Query'
    >>> display.thinking_title
    'Resolving Query'
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolDisplayConfig:
    """Display configuration for a tool."""

    friendly_name: str
    """Static display name for tool call cards."""

    friendly_template: str | None = None
    """Template with {arg} placeholders for dynamic names."""

    thinking_title: str | None = None
    """Title for thinking step UI (defaults to friendly_name)."""

    thinking_description: str | None = None
    """Description for thinking step UI."""

    hidden_in_ui: bool = False
    """Whether to hide this tool from UI displays."""


# =============================================================================
# Unified Tool Display Configuration
# =============================================================================
# NOTE: Tool names must match those in agents/tools/registry.py ALL_TOOL_METADATA

TOOL_DISPLAY: dict[str, ToolDisplayConfig] = {
    # =========================================================================
    # Query Tools
    # =========================================================================
    "resolve_query": ToolDisplayConfig(
        friendly_name="Resolving Query",
        thinking_title="Resolving Query",
        thinking_description="Fetching query details and SQL",
    ),
    "analyze_query_plan": ToolDisplayConfig(
        friendly_name="Analyzing Query Plan",
        thinking_title="Analyzing Query Plan",
        thinking_description="Parsing execution plan structure",
    ),
    "analyze_explain_plan": ToolDisplayConfig(
        friendly_name="Analyzing Explain Plan",
        thinking_title="Analyzing Explain Plan",
        thinking_description="Extracting plan metrics",
    ),
    # =========================================================================
    # Job Tools
    # =========================================================================
    "resolve_job": ToolDisplayConfig(
        friendly_name="Resolving Job",
        friendly_template="Resolving Job: {job_id}",
        thinking_title="Resolving Job",
        thinking_description="Finding job details",
    ),
    "fetch_job_config": ToolDisplayConfig(
        friendly_name="Fetching Job Configuration",
        thinking_title="Loading Job Configuration",
        thinking_description="Fetching job settings",
    ),
    "analyze_job_history": ToolDisplayConfig(
        friendly_name="Analyzing Job History",
        thinking_title="Analyzing Job History",
        thinking_description="Reviewing past job runs",
    ),
    "inspect_source_code": ToolDisplayConfig(
        friendly_name="Inspecting Source Code",
        friendly_template="Inspecting Source Code: {task_key}",
        thinking_title="Inspecting Source Code",
        thinking_description="Fetching notebook/script code",
    ),
    "analyze_code_quality": ToolDisplayConfig(
        friendly_name="Analyzing Code Quality",
        thinking_title="Analyzing Code Quality",
        thinking_description="Checking for anti-patterns",
    ),
    # =========================================================================
    # UC/Table Tools
    # =========================================================================
    "enumerate_uc_assets": ToolDisplayConfig(
        friendly_name="Enumerating UC Assets",
        thinking_title="Enumerating UC Assets",
        thinking_description="Listing catalogs, schemas, tables",
    ),
    "fetch_table_metadata": ToolDisplayConfig(
        friendly_name="Fetching Table Metadata",
        friendly_template="Fetching Table Metadata for {table_name}",
        thinking_title="Fetching Table Metadata",
        thinking_description="Loading schema and statistics",
    ),
    "fetch_table_history": ToolDisplayConfig(
        friendly_name="Fetching Table History",
        friendly_template="Fetching Table History for {table_name}",
        thinking_title="Loading Table History",
        thinking_description="Retrieving table changes",
    ),
    "fetch_table_lineage": ToolDisplayConfig(
        friendly_name="Fetching Table Lineage",
        friendly_template="Fetching Table Lineage for {table_name}",
        thinking_title="Tracing Table Lineage",
        thinking_description="Finding data dependencies",
    ),
    "fetch_table_grants": ToolDisplayConfig(
        friendly_name="Fetching Table Grants",
        friendly_template="Fetching Table Grants for {table_name}",
        thinking_title="Fetching Table Grants",
        thinking_description="Loading access permissions",
    ),
    "fetch_table_fingerprint": ToolDisplayConfig(
        friendly_name="Fetching Table Fingerprint",
        friendly_template="Fetching Table Fingerprint for {table_name}",
        thinking_title="Fetching Table Fingerprint",
        thinking_description="Building workload profile",
    ),
    "discover_tables": ToolDisplayConfig(
        friendly_name="Discovering Tables",
        thinking_title="Discovering Tables",
        thinking_description="Finding tables in query/code",
    ),
    "enrich_table_metadata": ToolDisplayConfig(
        friendly_name="Enriching Table Metadata",
        thinking_title="Enriching Table Metadata",
        thinking_description="Adding extended metadata",
    ),
    "analyze_table_schema": ToolDisplayConfig(
        friendly_name="Analyzing Table Schema",
        thinking_title="Analyzing Table Schema",
        thinking_description="Checking schema structure",
    ),
    "analyze_access_patterns": ToolDisplayConfig(
        friendly_name="Analyzing Access Patterns",
        thinking_title="Analyzing Access Patterns",
        thinking_description="Reviewing query frequency",
    ),
    "detect_schema_drift": ToolDisplayConfig(
        friendly_name="Detecting Schema Drift",
        thinking_title="Detecting Schema Drift",
        thinking_description="Tracking schema changes",
    ),
    "recommend_storage_optimization": ToolDisplayConfig(
        friendly_name="Recommending Storage Optimization",
        thinking_title="Recommending Storage Optimization",
        thinking_description="Finding optimization opportunities",
    ),
    "analyze_query_impact": ToolDisplayConfig(
        friendly_name="Analyzing Query Impact",
        thinking_title="Analyzing Query Impact",
        thinking_description="Predicting performance impact",
    ),
    "attribute_table_costs": ToolDisplayConfig(
        friendly_name="Attributing Table Costs",
        thinking_title="Attributing Table Costs",
        thinking_description="Breaking down costs by table",
    ),
    "generate_schema_diff": ToolDisplayConfig(
        friendly_name="Generating Schema Diff",
        thinking_title="Generating Schema Diff",
        thinking_description="Comparing schema versions",
    ),
    "analyze_policy_coverage": ToolDisplayConfig(
        friendly_name="Analyzing Policy Coverage",
        thinking_title="Analyzing Policy Coverage",
        thinking_description="Checking security policies",
    ),
    # =========================================================================
    # Compute Tools
    # =========================================================================
    "list_clusters": ToolDisplayConfig(
        friendly_name="Listing Clusters",
        thinking_title="Listing Clusters",
        thinking_description="Loading cluster inventory",
    ),
    "get_cluster_health": ToolDisplayConfig(
        friendly_name="Getting Cluster Health",
        friendly_template="Getting Cluster Health: {cluster_id}",
        thinking_title="Getting Cluster Health",
        thinking_description="Analyzing health and risks",
    ),
    "fetch_cluster_config": ToolDisplayConfig(
        friendly_name="Fetching Cluster Configuration",
        thinking_title="Loading Cluster Config",
        thinking_description="Fetching cluster settings",
    ),
    "fetch_cluster_events": ToolDisplayConfig(
        friendly_name="Fetching Cluster Events",
        thinking_title="Fetching Cluster Events",
        thinking_description="Loading scaling events",
    ),
    "fetch_cluster_metrics": ToolDisplayConfig(
        friendly_name="Fetching Cluster Metrics",
        thinking_title="Fetching Cluster Metrics",
        thinking_description="Loading resource metrics",
    ),
    "fetch_warehouse_config": ToolDisplayConfig(
        friendly_name="Fetching Warehouse Configuration",
        thinking_title="Loading Warehouse Config",
        thinking_description="Fetching warehouse settings",
    ),
    "fetch_warehouse_metrics": ToolDisplayConfig(
        friendly_name="Fetching Warehouse Metrics",
        thinking_title="Fetching Warehouse Metrics",
        thinking_description="Loading warehouse metrics",
    ),
    "fetch_query_runtime_metrics": ToolDisplayConfig(
        friendly_name="Fetching Query Runtime Metrics",
        thinking_title="Fetching Query Runtime Metrics",
        thinking_description="Loading query resource usage",
    ),
    "fetch_spark_logs": ToolDisplayConfig(
        friendly_name="Fetching Spark Logs",
        thinking_title="Fetching Spark Logs",
        thinking_description="Loading Spark execution logs",
    ),
    # =========================================================================
    # Warehouse Portfolio Tools
    # =========================================================================
    "get_warehouse_portfolio": ToolDisplayConfig(
        friendly_name="Getting Warehouse Portfolio",
        thinking_title="Getting Warehouse Portfolio",
        thinking_description="Listing all warehouses",
    ),
    "get_warehouse_fingerprint": ToolDisplayConfig(
        friendly_name="Getting Warehouse Fingerprint",
        friendly_template="Getting Warehouse Fingerprint: {warehouse_id}",
        thinking_title="Getting Warehouse Fingerprint",
        thinking_description="Analyzing warehouse profile",
    ),
    "get_warehouse_health": ToolDisplayConfig(
        friendly_name="Getting Warehouse Health",
        friendly_template="Getting Warehouse Health: {warehouse_id}",
        thinking_title="Getting Warehouse Health",
        thinking_description="Checking SLO compliance",
    ),
    "get_warehouse_user_activity": ToolDisplayConfig(
        friendly_name="Getting User Activity",
        friendly_template="Getting User Activity: {warehouse_id}",
        thinking_title="Getting User Activity",
        thinking_description="Loading user breakdown",
    ),
    "analyze_warehouse_topology": ToolDisplayConfig(
        friendly_name="Analyzing Warehouse Topology",
        thinking_title="Analyzing Warehouse Topology",
        thinking_description="Cross-warehouse analysis",
    ),
    "set_warehouse_slo": ToolDisplayConfig(
        friendly_name="Setting Warehouse SLO",
        friendly_template="Setting Warehouse SLO: {warehouse_id}",
        thinking_title="Setting Warehouse SLO",
        thinking_description="Configuring SLO targets",
    ),
    "generate_warehouse_chargeback": ToolDisplayConfig(
        friendly_name="Generating Warehouse Chargeback",
        friendly_template="Generating Warehouse Chargeback: {warehouse_id}",
        thinking_title="Generating Warehouse Chargeback",
        thinking_description="Building cost allocation",
    ),
    "generate_portfolio_chargeback": ToolDisplayConfig(
        friendly_name="Generating Portfolio Chargeback",
        thinking_title="Generating Portfolio Chargeback",
        thinking_description="Building portfolio costs",
    ),
    # =========================================================================
    # Analytics/FinOps Tools
    # =========================================================================
    "build_sql_query": ToolDisplayConfig(
        friendly_name="Building SQL",
        thinking_title="Building SQL Query",
        thinking_description="Using context to build query",
    ),
    "execute_sql_query": ToolDisplayConfig(
        friendly_name="Executing Query",
        thinking_title="Executing SQL Query",
        thinking_description="Executing query and summarizing results for analysis",
    ),
    "validate_sql_query": ToolDisplayConfig(
        friendly_name="Validating Query",
        thinking_title="Validating SQL Query",
        thinking_description="Validating query for syntax and runtime errors",
    ),
    "build_analytics_context": ToolDisplayConfig(
        friendly_name="Building Context",
        thinking_title="Gathering RAG Context",
        thinking_description="Retrieving tables, nuances, and optional codebook/facets/learnings",
    ),
    # =========================================================================
    # Interaction Tools
    # =========================================================================
    "resolve_user_intent": ToolDisplayConfig(
        friendly_name="Understanding User Intent",
        thinking_title="Understanding Intent",
        thinking_description="Classifying user request",
    ),
    "request_user_input": ToolDisplayConfig(
        friendly_name="Requesting User Input",
        thinking_title="Requesting Input",
        thinking_description="Waiting for user response",
        hidden_in_ui=True,
    ),
    # =========================================================================
    # Runtime Tools (registered dynamically)
    # =========================================================================
    "complete": ToolDisplayConfig(
        friendly_name="Complete",
        thinking_title="Generating Report",
        thinking_description="Formatting final output",
        hidden_in_ui=True,
    ),
}


# =============================================================================
# Argument Labels for Auto-Generated Names
# =============================================================================

ARGUMENT_LABELS: dict[str, str] = {
    # Identifiers
    "job_id": "Job",
    "job_run_id": "Job Run",
    "run_id": "Run",
    "task_key": "Task",
    "cluster_id": "Cluster",
    "warehouse_id": "Warehouse",
    "query_id": "Query",
    "statement_id": "Statement",
    "table_name": "Table",
    "schema": "Schema",
    "catalog": "Catalog",
    "database": "Database",
    # Generic
    "target": "Target",
    "name": "Name",
    "id": "ID",
    "filter": "Filter",
    "path": "Path",
}


# =============================================================================
# Public API
# =============================================================================


def get_tool_display(tool_name: str) -> ToolDisplayConfig:
    """
    Get display configuration for a tool.

    Args:
        tool_name: Technical tool name

    Returns:
        ToolDisplayConfig with display metadata

    Example:
        >>> config = get_tool_display("resolve_query")
        >>> config.friendly_name
        'Resolving Query'
    """
    if tool_name in TOOL_DISPLAY:
        return TOOL_DISPLAY[tool_name]

    # Generate default config for unknown tools
    default_name = tool_name.replace("_", " ").title()
    return ToolDisplayConfig(
        friendly_name=default_name,
        thinking_title=default_name,
        thinking_description=f"Executing {tool_name}",
    )


def _clean_query_id_for_display(query_id: str) -> str:
    """
    Clean query_id for user-friendly display by removing version suffixes.

    Removes patterns like _v1, _v2, _v3, etc. from the end of query IDs
    to make the display cleaner.

    Args:
        query_id: Query ID (e.g., "top_k_jobs_by_cost_v2")

    Returns:
        Cleaned query ID (e.g., "top_k_jobs_by_cost")

    Example:
        >>> _clean_query_id_for_display("top_k_jobs_by_cost_v2")
        'top_k_jobs_by_cost'
        >>> _clean_query_id_for_display("workspace_usage")
        'workspace_usage'
    """
    # Remove version suffix like _v1, _v2, _v3, etc.
    cleaned = re.sub(r"_v\d+$", "", query_id)
    # Convert underscores to spaces for readability
    cleaned = cleaned.replace("_", " ").title()
    return cleaned


def get_friendly_name(tool_name: str, arguments: dict[str, Any] | None = None) -> str:
    """
    Generate a human-friendly display name for a tool call.

    Args:
        tool_name: Technical tool name
        arguments: Optional tool arguments for template substitution

    Returns:
        Human-friendly display name

    Example:
        >>> get_friendly_name("resolve_job", {"job_id": "12345"})
        'Resolving Job: 12345'
    """
    arguments = arguments or {}
    config = get_tool_display(tool_name)

    # Clean up query_id for display (remove version suffix)
    display_args = arguments.copy()
    if "query_id" in display_args:
        display_args["query_id"] = _clean_query_id_for_display(
            str(display_args["query_id"])
        )

    # Try template substitution
    template = config.friendly_template
    if template:
        try:
            required_keys = re.findall(r"\{(\w+)\}", template)
            if all(display_args.get(k) for k in required_keys):
                return template.format(**{k: display_args[k] for k in required_keys})
        except (KeyError, ValueError):
            pass
        # Fall through to friendly_name if template fails

    # Use static friendly name, potentially with auto-generated context
    base_name = config.friendly_name

    # Auto-append key arguments for better context
    if display_args:
        context = _format_arguments_as_context(display_args)
        if context and "{" not in (config.friendly_template or ""):
            # Only add context if no template was defined
            return f"{base_name} for {context}"

    return base_name


def get_thinking_step_title(tool_name: str) -> str:
    """
    Get user-friendly title for thinking step UI.

    Args:
        tool_name: Technical tool name

    Returns:
        Human-readable step title
    """
    config = get_tool_display(tool_name)
    return config.thinking_title or config.friendly_name


def get_thinking_step_id(tool_name: str) -> str:
    """
    Get step ID for thinking step UI.

    Args:
        tool_name: Technical tool name

    Returns:
        Step identifier (same as tool_name)
    """
    return tool_name


def get_thinking_step_description(tool_name: str) -> str:
    """
    Get description for thinking step UI.

    Args:
        tool_name: Technical tool name

    Returns:
        Human-readable description
    """
    config = get_tool_display(tool_name)
    return config.thinking_description or f"Executing {tool_name}"


def should_hide_tool(tool_name: str, debug_mode: bool = False) -> bool:
    """
    Determine if a tool should be hidden in UI.

    Args:
        tool_name: Technical tool name
        debug_mode: Show all tools in debug mode

    Returns:
        True if tool should be hidden
    """
    if debug_mode:
        return False

    config = get_tool_display(tool_name)
    return config.hidden_in_ui


# =============================================================================
# Internal Helpers
# =============================================================================


def _format_arguments_as_context(arguments: dict[str, Any]) -> str | None:
    """Format tool arguments as human-readable context."""
    if not arguments:
        return None

    # Priority order for argument display
    priority_args = [
        "warehouse_id",
        "cluster_id",
        "job_id",
        "job_run_id",
        "run_id",
        "query_id",
        "statement_id",
        "table_name",
        "catalog",
        "schema",
        "database",
        "task_key",
        "target",
        "name",
        "id",
        "filter",
        "path",
    ]

    for arg_name in priority_args:
        if arg_name in arguments:
            value = arguments[arg_name]
            if value and isinstance(value, (str, int, float)):
                label = ARGUMENT_LABELS.get(
                    arg_name, arg_name.replace("_", " ").title()
                )
                str_value = str(value)
                if len(str_value) > 50:
                    str_value = str_value[:47] + "..."
                return f"{label} {str_value}"

    return None


def generate_sub_task(
    tool_name: str,
    status: str,
    result: Any = None,
    error: str | None = None,
) -> dict[str, Any]:
    """
    Generate a sub-task description from tool execution.

    Args:
        tool_name: Name of the tool
        status: Sub-task status (pending, in_progress, completed, failed)
        result: Tool result (for value extraction)
        error: Error message if failed

    Returns:
        Sub-task dict with id, description, status, value
    """
    description = get_thinking_step_description(tool_name)

    # Extract value from result
    value = None
    if result and status == "completed":
        value = _extract_result_value(tool_name, result)
    elif error and status == "failed":
        value = f"Error: {error[:50]}"

    return {
        "id": f"subtask_{tool_name}",
        "description": description,
        "status": status,
        "value": value,
    }


def _extract_resolve_query_value(content: str) -> str | None:
    lines = len(content.strip().split("\n"))
    return f"{lines} lines of SQL"


def _extract_analyze_query_plan_value(content: str) -> str | None:
    if "nodes" in content.lower():
        match = re.search(r"(\d+)\s*nodes?", content.lower())
        if match:
            return f"{match.group(1)} nodes"
    return "Plan analyzed"


def _extract_fetch_table_metadata_value(content: str) -> str | None:
    if "columns" in content.lower():
        match = re.search(r"(\d+)\s*columns?", content.lower())
        if match:
            return f"{match.group(1)} columns"
    return "Metadata loaded"


def _extract_discover_tables_value(content: str) -> str | None:
    match = re.search(r"(\d+)\s*tables?", content.lower())
    return f"{match.group(1)} tables found" if match else None


def _extract_analyze_code_quality_value(content: str) -> str | None:
    if "issues" in content.lower() or "violations" in content.lower():
        match = re.search(r"(\d+)\s*(issues?|violations?)", content.lower())
        if match:
            return f"{match.group(1)} issues"
    return "Analysis complete"


def _extract_get_warehouse_portfolio_value(content: str) -> str | None:
    match = re.search(r"(\d+)\s*warehouses?", content.lower())
    return f"{match.group(1)} warehouses" if match else None


def _extract_enumerate_uc_assets_value(content: str) -> str | None:
    match = re.search(r"(\d+)\s*(assets?|tables?|schemas?)", content.lower())
    return f"{match.group(1)} {match.group(2)}" if match else None


# Dispatch table mapping tool name → content extractor
_RESULT_VALUE_EXTRACTORS: dict[str, Any] = {
    "resolve_query": _extract_resolve_query_value,
    "analyze_query_plan": _extract_analyze_query_plan_value,
    "fetch_table_metadata": _extract_fetch_table_metadata_value,
    "discover_tables": _extract_discover_tables_value,
    "analyze_code_quality": _extract_analyze_code_quality_value,
    "get_warehouse_portfolio": _extract_get_warehouse_portfolio_value,
    "enumerate_uc_assets": _extract_enumerate_uc_assets_value,
}


def _extract_result_value(tool_name: str, result: Any) -> str | None:
    """
    Extract a display value from tool result.

    Args:
        tool_name: Name of the tool
        result: Tool result object

    Returns:
        Human-readable value string or None
    """
    # Try to get content from result
    content = getattr(result, "content", None)
    if not content:
        return None

    # Dispatch to tool-specific extractor
    extractor = _RESULT_VALUE_EXTRACTORS.get(tool_name)
    if extractor is not None and isinstance(content, str):
        extracted = extractor(content)
        if extracted is not None:
            return extracted

    # Default: truncate content
    if isinstance(content, str) and content:
        return content[:30] + "..." if len(content) > 30 else content

    return None
