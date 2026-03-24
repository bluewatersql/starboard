"""
Tool infrastructure for multi-agent reasoning framework.
"""

# Metadata registry and helper functions
# Domain-based tool access control
from starboard_server.agents.tool_categories import (
    TOOL_CATEGORIES,
    get_tools_for_domain,
)
from starboard_server.agents.tools.registry import (
    ALL_TOOL_METADATA,
    get_tool_metadata,
    list_all_tools,
)

# All individual tool schemas
from starboard_server.agents.tools.schemas import (
    ANALYZE_CODE_QUALITY,
    ANALYZE_EXPLAIN_PLAN,
    ANALYZE_JOB_HISTORY,
    ANALYZE_QUERY_PLAN,
    BUILD_ANALYTICS_CONTEXT,
    BUILD_SQL_QUERY,
    DISCOVER_TABLES,
    EXECUTE_SQL_QUERY,
    GET_CLUSTER_CONFIG,
    GET_CLUSTER_EVENTS,
    GET_CLUSTER_METRICS,
    GET_ENRICHED_TABLE_METADATA,
    GET_JOB_CONFIG,
    GET_QUERY_RUNTIME_METRICS,
    GET_SOURCE_CODE,
    GET_SPARK_LOGS,
    GET_TABLE_HISTORY,
    GET_TABLE_LINEAGE,
    GET_TABLE_METADATA,
    GET_WAREHOUSE_CONFIG,
    GET_WAREHOUSE_METRICS,
    REQUEST_USER_INPUT,
    RESOLVE_JOB,
    RESOLVE_QUERY,
    RESOLVE_USER_INTENT,
    VALIDATE_SQL_QUERY,
)
from starboard_server.agents.tools.tool_factory import (
    create_tool_registry,
    get_tool_count,
    validate_tool_metadata,
)

# Tool registry and factory
from starboard_server.agents.tools.tool_registry import (
    NativeToolAdapter,
    ToolMetadata,
    ToolRegistry,
)

__all__ = [
    # Metadata registry and helpers
    "ALL_TOOL_METADATA",
    "get_tool_metadata",
    "list_all_tools",
    # Domain-based tool access
    "TOOL_CATEGORIES",
    "get_tools_for_domain",
    # Tool registry and factory
    "ToolRegistry",
    "ToolMetadata",
    "NativeToolAdapter",
    "create_tool_registry",
    "get_tool_count",
    "validate_tool_metadata",
    # Query tools
    "RESOLVE_QUERY",
    "ANALYZE_QUERY_PLAN",
    "ANALYZE_EXPLAIN_PLAN",
    # Table tools
    "GET_TABLE_METADATA",
    "GET_TABLE_HISTORY",
    "DISCOVER_TABLES",
    "GET_TABLE_LINEAGE",
    "GET_ENRICHED_TABLE_METADATA",
    # Job tools
    "RESOLVE_JOB",
    "GET_JOB_CONFIG",
    "ANALYZE_JOB_HISTORY",
    # Source code tools
    "ANALYZE_CODE_QUALITY",
    "GET_SOURCE_CODE",
    # Compute tools
    "GET_CLUSTER_CONFIG",
    "GET_WAREHOUSE_CONFIG",
    "GET_SPARK_LOGS",
    "GET_CLUSTER_EVENTS",
    "GET_CLUSTER_METRICS",
    "GET_WAREHOUSE_METRICS",
    "GET_QUERY_RUNTIME_METRICS",
    # User interaction tools
    "RESOLVE_USER_INTENT",
    "REQUEST_USER_INPUT",
    # Analytics tools
    "BUILD_SQL_QUERY",
    "VALIDATE_SQL_QUERY",
    "EXECUTE_SQL_QUERY",
    "BUILD_ANALYTICS_CONTEXT",
]
