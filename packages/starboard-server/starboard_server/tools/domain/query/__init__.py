"""Query domain logic - pure business rules with no I/O dependencies."""

from starboard_core.domain.models.query import (
    ExplainPlanInput,
    ExplainPlanResult,
    QueryResolutionInput,
    QueryResolutionResult,
    QuerySource,
)

from starboard_server.tools.domain.query.analyzer import QueryAnalyzer
from starboard_server.tools.domain.query.resolver import QueryResolver
from starboard_server.tools.domain.query.transformers import (
    transform_explain_text,
    transform_query_history,
    transform_warehouse_configuration,
)
from starboard_server.tools.domain.query.warehouse_query_analyzer import (
    WarehouseQueryAnalyzer,
)
from starboard_server.tools.domain.query.warehouse_query_models import (
    CacheMetrics,
    DurationStats,
    PerformanceBytes,
    PerformanceRows,
    PerformanceScan,
    PhotonMetrics,
    StatementTypeStats,
    TimesAverage,
    WarehouseConfig,
    WarehousePerformance,
    WarehouseSummary,
)

__all__ = [
    # Analyzers and resolvers
    "QueryAnalyzer",
    "QueryResolver",
    "WarehouseQueryAnalyzer",
    # Models
    "QuerySource",
    "QueryResolutionInput",
    "QueryResolutionResult",
    "ExplainPlanInput",
    "ExplainPlanResult",
    # Warehouse query models
    "CacheMetrics",
    "DurationStats",
    "PerformanceBytes",
    "PerformanceRows",
    "PerformanceScan",
    "PhotonMetrics",
    "StatementTypeStats",
    "TimesAverage",
    "WarehouseConfig",
    "WarehousePerformance",
    "WarehouseSummary",
    # Transform functions
    "transform_explain_text",
    "transform_query_history",
    "transform_warehouse_configuration",
]
