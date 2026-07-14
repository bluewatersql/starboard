# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tool metadata schemas organized by category."""

# Compute infrastructure tools
# Analytics SQL tools
from starboard.agents.tools.schemas.analytics_sql import (
    BUILD_SQL_QUERY,
    EXECUTE_SQL_QUERY,
    VALIDATE_SQL_QUERY,
)
from starboard.agents.tools.schemas.compute import (
    GET_CLUSTER_CONFIG,
    GET_CLUSTER_EVENTS,
    GET_CLUSTER_METRICS,
    GET_QUERY_RUNTIME_METRICS,
    GET_SPARK_LOGS,
    GET_WAREHOUSE_CONFIG,
    GET_WAREHOUSE_METRICS,
)

# User interaction tools
from starboard.agents.tools.schemas.interaction import (
    REQUEST_USER_INPUT,
    RESOLVE_USER_INTENT,
)

# Job tools
from starboard.agents.tools.schemas.job import (
    ANALYZE_JOB_HISTORY,
    GET_JOB_CONFIG,
    RESOLVE_JOB,
)
from starboard.agents.tools.schemas.query import (
    ANALYZE_EXPLAIN_PLAN,
    ANALYZE_QUERY_PLAN,
    RESOLVE_QUERY,
)

# RAG tools
from starboard.agents.tools.schemas.rag import BUILD_ANALYTICS_CONTEXT

# Source code tools
from starboard.agents.tools.schemas.source import (
    ANALYZE_CODE_QUALITY,
    GET_SOURCE_CODE,
)

# Table tools
from starboard.agents.tools.schemas.table import (
    DISCOVER_TABLES,
    GET_ENRICHED_TABLE_METADATA,
    GET_TABLE_HISTORY,
    GET_TABLE_LINEAGE,
    GET_TABLE_METADATA,
)

__all__ = [
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
    # RAG tools
    "BUILD_ANALYTICS_CONTEXT",
    # Analytics SQL tools
    "BUILD_SQL_QUERY",
    "VALIDATE_SQL_QUERY",
    "EXECUTE_SQL_QUERY",
]
