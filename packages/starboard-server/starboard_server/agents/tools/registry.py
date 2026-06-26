# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tool metadata registry and accessor functions."""

from typing import Any

from starboard_server.agents.tools.schemas.analytics_sql import (
    BUILD_SQL_QUERY,
    EXECUTE_SQL_QUERY,
    VALIDATE_SQL_QUERY,
)
from starboard_server.agents.tools.schemas.compute import (
    GET_CLUSTER_CONFIG,
    GET_CLUSTER_EVENTS,
    GET_CLUSTER_HEALTH,
    GET_CLUSTER_METRICS,
    GET_QUERY_RUNTIME_METRICS,
    GET_SPARK_LOGS,
    GET_WAREHOUSE_CONFIG,
    GET_WAREHOUSE_METRICS,
    LIST_CLUSTERS,
)
from starboard_server.agents.tools.schemas.diagnostic import EXPLORE_ARTIFACT
from starboard_server.agents.tools.schemas.discovery import (
    ANALYZE_DISCOVERY_DOMAIN,
    DISCOVER_ACTIVE_PRODUCTS,
    GET_DISCOVERY_ANALYSIS_PROGRESS,
    RUN_DISCOVERY_QUERIES,
    RUN_WORKSPACE_DISCOVERY,
    START_DISCOVERY_ANALYSIS,
    SYNTHESIZE_DISCOVERY_REPORT,
)
from starboard_server.agents.tools.schemas.interaction import (
    REQUEST_USER_INPUT,
    RESOLVE_USER_INTENT,
)
from starboard_server.agents.tools.schemas.job import (
    ANALYZE_JOB_HISTORY,
    GET_JOB_CONFIG,
    GET_RUN_OUTPUT,
    GET_TASK_LOGS,
    RESOLVE_JOB,
)
from starboard_server.agents.tools.schemas.query import (
    ANALYZE_EXPLAIN_PLAN,
    ANALYZE_QUERY_PLAN,
    RESOLVE_QUERY,
)
from starboard_server.agents.tools.schemas.rag import BUILD_ANALYTICS_CONTEXT
from starboard_server.agents.tools.schemas.source import (
    ANALYZE_CODE_QUALITY,
    GET_SOURCE_CODE,
)
from starboard_server.agents.tools.schemas.table import (
    ANALYZE_ACCESS_PATTERNS,
    ANALYZE_POLICY_COVERAGE,
    ANALYZE_QUERY_IMPACT,
    ANALYZE_SCHEMA_DRIFT,
    ANALYZE_STORAGE_OPTIMIZATION,
    ANALYZE_TABLE_COSTS,
    ANALYZE_TABLE_SCHEMA,
    DISCOVER_TABLES,
    GENERATE_SCHEMA_DIFF,
    GET_ENRICHED_TABLE_METADATA,
    GET_TABLE_FINGERPRINT,
    GET_TABLE_GRANTS,
    GET_TABLE_HISTORY,
    GET_TABLE_LINEAGE,
    GET_TABLE_METADATA,
    LIST_UC_ASSETS,
)
from starboard_server.agents.tools.schemas.warehouse import (
    ANALYZE_WAREHOUSE_TOPOLOGY,
    CONFIGURE_WAREHOUSE_SLO,
    GENERATE_PORTFOLIO_CHARGEBACK,
    GENERATE_WAREHOUSE_CHARGEBACK,
    GET_WAREHOUSE_FINGERPRINT,
    GET_WAREHOUSE_HEALTH,
    GET_WAREHOUSE_PORTFOLIO,
    GET_WAREHOUSE_USER_ACTIVITY,
)

# All tool metadata organized by category
ALL_TOOL_METADATA: dict[str, dict[str, Any]] = {
    # Query tools
    "resolve_query": RESOLVE_QUERY,
    "analyze_query_plan": ANALYZE_QUERY_PLAN,
    "analyze_explain_plan": ANALYZE_EXPLAIN_PLAN,
    # Table/UC tools - Phase 1 (Core)
    "list_uc_assets": LIST_UC_ASSETS,
    "get_table_metadata": GET_TABLE_METADATA,
    "get_table_history": GET_TABLE_HISTORY,
    "discover_tables": DISCOVER_TABLES,
    "get_table_lineage": GET_TABLE_LINEAGE,
    "get_enriched_table_metadata": GET_ENRICHED_TABLE_METADATA,
    "get_table_grants": GET_TABLE_GRANTS,
    "analyze_table_schema": ANALYZE_TABLE_SCHEMA,
    "analyze_access_patterns": ANALYZE_ACCESS_PATTERNS,
    "analyze_schema_drift": ANALYZE_SCHEMA_DRIFT,
    # Table/UC tools - Phase 2 (Advanced)
    "analyze_storage_optimization": ANALYZE_STORAGE_OPTIMIZATION,
    "analyze_query_impact": ANALYZE_QUERY_IMPACT,
    "get_table_fingerprint": GET_TABLE_FINGERPRINT,
    "analyze_table_costs": ANALYZE_TABLE_COSTS,
    "generate_schema_diff": GENERATE_SCHEMA_DIFF,
    "analyze_policy_coverage": ANALYZE_POLICY_COVERAGE,
    # Job tools
    "resolve_job": RESOLVE_JOB,
    "get_job_config": GET_JOB_CONFIG,
    "analyze_job_history": ANALYZE_JOB_HISTORY,
    "get_run_output": GET_RUN_OUTPUT,
    "get_task_logs": GET_TASK_LOGS,
    # Source code tools
    "analyze_code_quality": ANALYZE_CODE_QUALITY,
    "get_source_code": GET_SOURCE_CODE,
    # Compute tools
    "list_clusters": LIST_CLUSTERS,
    "get_cluster_config": GET_CLUSTER_CONFIG,
    "get_cluster_health": GET_CLUSTER_HEALTH,
    "get_warehouse_config": GET_WAREHOUSE_CONFIG,
    "get_spark_logs": GET_SPARK_LOGS,
    "get_cluster_events": GET_CLUSTER_EVENTS,
    "get_cluster_metrics": GET_CLUSTER_METRICS,
    "get_warehouse_metrics": GET_WAREHOUSE_METRICS,
    "get_query_runtime_metrics": GET_QUERY_RUNTIME_METRICS,
    # Analytics SQL Generation (Agentic RAG Workflow)
    "build_sql_query": BUILD_SQL_QUERY,
    "validate_sql_query": VALIDATE_SQL_QUERY,
    "execute_sql_query": EXECUTE_SQL_QUERY,
    # RAG context builder
    "build_analytics_context": BUILD_ANALYTICS_CONTEXT,
    # User interaction tools
    "resolve_user_intent": RESOLVE_USER_INTENT,
    "request_user_input": REQUEST_USER_INPUT,
    # Warehouse portfolio tools (only implemented tools)
    "get_warehouse_portfolio": GET_WAREHOUSE_PORTFOLIO,
    "get_warehouse_fingerprint": GET_WAREHOUSE_FINGERPRINT,
    "get_warehouse_health": GET_WAREHOUSE_HEALTH,
    "configure_warehouse_slo": CONFIGURE_WAREHOUSE_SLO,
    "analyze_warehouse_topology": ANALYZE_WAREHOUSE_TOPOLOGY,
    "get_warehouse_user_activity": GET_WAREHOUSE_USER_ACTIVITY,
    "generate_warehouse_chargeback": GENERATE_WAREHOUSE_CHARGEBACK,
    "generate_portfolio_chargeback": GENERATE_PORTFOLIO_CHARGEBACK,
    # Diagnostic tools (artifact exploration)
    "explore_artifact": EXPLORE_ARTIFACT,
    # Discovery tools (workspace health assessment)
    "discover_active_products": DISCOVER_ACTIVE_PRODUCTS,
    "run_discovery_queries": RUN_DISCOVERY_QUERIES,
    "analyze_discovery_domain": ANALYZE_DISCOVERY_DOMAIN,
    "start_discovery_analysis": START_DISCOVERY_ANALYSIS,
    "get_discovery_analysis_progress": GET_DISCOVERY_ANALYSIS_PROGRESS,
    "synthesize_discovery_report": SYNTHESIZE_DISCOVERY_REPORT,
    "run_workspace_discovery": RUN_WORKSPACE_DISCOVERY,
}


def get_tool_metadata(tool_name: str) -> dict[str, Any]:
    """
    Get metadata for a specific tool.

    Args:
        tool_name: Name of the tool

    Returns:
        Tool metadata dictionary

    Raises:
        KeyError: If tool not found

    Example:
        >>> metadata = get_tool_metadata("resolve_query")
        >>> print(metadata["description"])
    """
    return ALL_TOOL_METADATA[tool_name]


def list_all_tools() -> list[str]:
    """
    Get list of all available tool names.

    Returns:
        List of all tool names

    Example:
        >>> all_tools = list_all_tools()
        >>> print(len(all_tools))
        24
    """
    return list(ALL_TOOL_METADATA.keys())
