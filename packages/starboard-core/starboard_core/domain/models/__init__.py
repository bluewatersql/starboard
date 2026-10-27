# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Domain models for starboard-core."""

import logging

# Analytics domain models
from starboard_core.domain.models.analytics import (
    QueryCatalogIndex,
    QueryMetadata,
    QueryParameter,
    SystemQueryResult,
)

# Auth domain models
from starboard_core.domain.models.auth import (
    User,
    UserSession,
    UserStatus,
)

# Clarification domain models
from starboard_core.domain.models.clarification import (
    AmbiguityScore,
    ClarificationOption,
    ClarificationRequest,
    ClarificationResponse,
    ClarificationType,
)

# Cluster domain models (new cluster agent)
from starboard_core.domain.models.cluster import (
    AccessMode,
    ClusterFingerprint,
    ClusterHealthReport,
    ClusterMode,
    ClusterType,
    CostProfile,
    FingerprintScope,
    HealthScore,
    NodeConfig,
    PerformanceProfile,
    RiskCategory,
    RiskIndicator,
    RiskSeverity,
    RuntimeConfig,
)

# Compute domain models
from starboard_core.domain.models.compute import (
    ClusterIdentifier,
    ClusterLogConfig,
    JobClusterInfo,
    WarehouseIdentifier,
)
from starboard_core.domain.models.context_types import ContextType
from starboard_core.domain.models.databricks import (
    ClusterJobReference,
    ClusterReference,
    TableReference,
)

# Discovery domain models
from starboard_core.domain.models.discovery import (
    AnalysisContext,
    DataCoverage,
    DiscoveryFinding,
    DiscoveryReport,
    DomainAnalysis,
    Evidence,
    ExecutiveSummary,
    FindingType,
    Grade,
    ImpactLevel,
    LikelyCause,
    PackResult,
    Priority,
    QueryPack,
    QueryResult,
    Remediation,
    ReportCard,
    ReportMetadata,
    SourceProof,
    SystemQuery,
)

# Feedback domain models
from starboard_core.domain.models.feedback import (
    AgentPerformanceReport,
    FeedbackCategory,
    FeedbackContext,
    FeedbackRating,
    UserFeedback,
)

# Job domain models
from starboard_core.domain.models.job import (
    AnalysisMode,
    JobHistoryResult,
    JobResolutionInput,
    JobResolutionResult,
    TaskDependencyResult,
)
from starboard_core.domain.models.llm import OptimizationMode
from starboard_core.domain.models.llm_schemas import (
    Analysis,
    CurrentState,
    EffortEstimate,
    Finding,
    ImpactEstimate,
    NextStep,
    Proofs,
    QueryRewrite,
    Summary,
)

# Query domain models
from starboard_core.domain.models.query import (
    ExplainPlanInput,
    ExplainPlanResult,
    QueryResolutionInput,
    QueryResolutionResult,
    QuerySource,
)
from starboard_core.domain.models.recommendations import (
    ActionCategory,
    ActionCommand,
    ActionPriority,
    ActionResult,
    ImpactMetrics,
    RecommendedAction,
)
from starboard_core.domain.models.report_types import (
    AdvisorReport,
    AgentReport,
    AnalyticsFinding,
    AnalyticsReport,
    CostImpact,
    CostSummary,
    VisualizationRecommendation,
)

# UC domain models
from starboard_core.domain.models.uc import (
    AccessPatterns,
    ColumnDiff,
    ColumnInfo,
    CostBreakdown,
    CostMetrics,
    DailyAccess,
    DeltaHistory,
    DeltaHistoryEntry,
    EffectivePermission,
    Grant,
    JoinPrediction,
    LineageNode,
    OptimizationScenario,
    PolicyCoverageReport,
    PolicyGap,
    QueryImpactAnalysis,
    ReadWorkloadMetrics,
    SchemaAnalysis,
    SchemaAnomaly,
    SchemaChange,
    SchemaDiff,
    SchemaDriftAnalysis,
    SimulationResult,
    StorageOptimizationReport,
    StorageRecommendation,
    StorageState,
    TableDiscoveryInput,
    TableDiscoveryResult,
    TableEnrichmentInput,
    TableFingerprint,
    TableGrants,
    TableLineage,
    TableMetadataRequest,
    UCAssetInfo,
    UCAssetList,
    UCTableMetadata,
    UserAccess,
    WorkloadProfile,
    WriteWorkloadMetrics,
)
from starboard_core.domain.models.uc import ImpactEstimate as UCImpactEstimate

# Warehouse domain models
from starboard_core.domain.models.warehouse import (
    DEFAULT_BATCH_SLOS,
    DEFAULT_INTERACTIVE_SLOS,
    HealthSummary,
    PortfolioChargebackInput,
    QueryTypeDistribution,
    RiskFactor,
    SLOConfig,
    SLOStatus,
    SLOTarget,
    SLOType,
    TimeDistribution,
    WarehouseChargebackInput,
    WarehouseFingerprint,
    WarehouseFingerprintInput,
    WarehouseHealthInput,
    WarehouseInfo,
    WarehousePortfolio,
    WarehousePortfolioInput,
    WarehouseSLOConfigInput,
    WarehouseSummary,
    WarehouseTopologyInput,
    WarehouseUserActivityInput,
    WorkloadPattern,
)

logger = logging.getLogger(__name__)

__all__ = [
    # Discovery domain models
    "AnalysisContext",
    "DataCoverage",
    "DiscoveryFinding",
    "DiscoveryReport",
    "DomainAnalysis",
    "Evidence",
    "ExecutiveSummary",
    "FindingType",
    "Grade",
    "ImpactLevel",
    "LikelyCause",
    "PackResult",
    "Priority",
    "QueryPack",
    "QueryResult",
    "Remediation",
    "ReportCard",
    "ReportMetadata",
    "SourceProof",
    "SystemQuery",
    # Context types
    "ContextType",
    # Databricks models
    "ClusterJobReference",
    "ClusterReference",
    "TableReference",
    # LLM models
    "OptimizationMode",
    # LLM schemas (used by reports)
    "Analysis",
    "CurrentState",
    "EffortEstimate",
    "Finding",
    "ImpactEstimate",
    "NextStep",
    "Proofs",
    "QueryRewrite",
    "Summary",
    # Report types (polymorphic)
    "AgentReport",
    "AdvisorReport",
    "AnalyticsReport",
    "AnalyticsFinding",
    "CostImpact",
    "CostSummary",
    "VisualizationRecommendation",
    # Recommendation models
    "ActionCategory",
    "ActionCommand",
    "ActionPriority",
    "ActionResult",
    "ImpactMetrics",
    "RecommendedAction",
    # UC domain models
    "UCAssetInfo",
    "UCAssetList",
    "UCTableMetadata",
    "ColumnInfo",
    "LineageNode",
    "TableLineage",
    "Grant",
    "EffectivePermission",
    "TableGrants",
    "SchemaAnomaly",
    "SchemaAnalysis",
    "SchemaChange",
    "SchemaDriftAnalysis",
    "DeltaHistoryEntry",
    "DeltaHistory",
    "UserAccess",
    "DailyAccess",
    "AccessPatterns",
    "StorageState",
    "StorageRecommendation",
    "UCImpactEstimate",
    "StorageOptimizationReport",
    "JoinPrediction",
    "QueryImpactAnalysis",
    "OptimizationScenario",
    "SimulationResult",
    "ReadWorkloadMetrics",
    "WriteWorkloadMetrics",
    "CostMetrics",
    "WorkloadProfile",
    "TableFingerprint",
    "CostBreakdown",
    "ColumnDiff",
    "SchemaDiff",
    "PolicyGap",
    "PolicyCoverageReport",
    "TableDiscoveryInput",
    "TableDiscoveryResult",
    "TableMetadataRequest",
    "TableEnrichmentInput",
    # Warehouse domain models
    "DEFAULT_BATCH_SLOS",
    "DEFAULT_INTERACTIVE_SLOS",
    "HealthSummary",
    "PortfolioChargebackInput",
    "QueryTypeDistribution",
    "RiskFactor",
    "SLOConfig",
    "SLOStatus",
    "SLOTarget",
    "SLOType",
    "TimeDistribution",
    "WarehouseChargebackInput",
    "WarehouseFingerprint",
    "WarehouseFingerprintInput",
    "WarehouseHealthInput",
    "WarehouseInfo",
    "WarehousePortfolio",
    "WarehousePortfolioInput",
    "WarehouseSLOConfigInput",
    "WarehouseSummary",
    "WarehouseTopologyInput",
    "WarehouseUserActivityInput",
    "WorkloadPattern",
    # Job domain models
    "AnalysisMode",
    "JobHistoryResult",
    "JobResolutionInput",
    "JobResolutionResult",
    "TaskDependencyResult",
    # Query domain models
    "ExplainPlanInput",
    "ExplainPlanResult",
    "QueryResolutionInput",
    "QueryResolutionResult",
    "QuerySource",
    # Cluster domain models (new cluster agent)
    "AccessMode",
    "ClusterFingerprint",
    "ClusterHealthReport",
    "ClusterMode",
    "ClusterType",
    "CostProfile",
    "FingerprintScope",
    "HealthScore",
    "NodeConfig",
    "PerformanceProfile",
    "RiskCategory",
    "RiskIndicator",
    "RiskSeverity",
    "RuntimeConfig",
    # Compute domain models (legacy)
    "ClusterIdentifier",
    "ClusterLogConfig",
    "JobClusterInfo",
    "WarehouseIdentifier",
    # Analytics domain models
    "QueryCatalogIndex",
    "QueryMetadata",
    "QueryParameter",
    "SystemQueryResult",
    # Feedback domain models
    "AgentPerformanceReport",
    "FeedbackCategory",
    "FeedbackContext",
    "FeedbackRating",
    "UserFeedback",
    # Clarification domain models
    "AmbiguityScore",
    "ClarificationOption",
    "ClarificationRequest",
    "ClarificationResponse",
    "ClarificationType",
    # Auth domain models
    "User",
    "UserSession",
    "UserStatus",
]
