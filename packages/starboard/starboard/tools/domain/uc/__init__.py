# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unity Catalog domain module.

This module re-exports domain models, analyzers, and transformers for
Unity Catalog operations from their canonical location in starboard_core.

The UC domain includes asset discovery, lineage tracking,
schema analysis, and access control.
"""

# Re-export models from starboard_core
# Re-export analyzers from starboard_core
from starboard_core.domain.analyzers import (
    AnomalyThresholds,
    TableAnalyzer,
    UCAnalyzer,
)
from starboard_core.domain.models.uc import (
    # Phase 1 models
    AccessPatterns,
    # Phase 2 models
    ColumnDiff,
    ColumnInfo,
    CostBreakdown,
    CostMetrics,
    DailyAccess,
    DeltaHistory,
    DeltaHistoryEntry,
    EffectivePermission,
    Grant,
    ImpactEstimate,
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
    # Table discovery models
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

# Re-export transformers from starboard_core
from starboard_core.domain.transformers import (
    AccessPatternTransformer,
    LineageGraphTransformer,
    QueryFingerprint,
    QueryOperation,
    SchemaHistoryTransformer,
    TableFingerprintTransformer,
    classify_query,
    # Simple transform functions (LLM-optimized output)
    resolve_3part,
    transform_delta_history,
    transform_table_lineage,
    transform_table_metadata,
)

__all__ = [
    # Analyzers
    "UCAnalyzer",
    "TableAnalyzer",
    "AnomalyThresholds",
    # Transformers
    "LineageGraphTransformer",
    "TableFingerprintTransformer",
    "AccessPatternTransformer",
    "SchemaHistoryTransformer",
    # Query classification
    "QueryOperation",
    "QueryFingerprint",
    "classify_query",
    # Asset models
    "UCAssetInfo",
    "UCAssetList",
    "UCTableMetadata",
    "ColumnInfo",
    # Lineage models
    "TableLineage",
    "LineageNode",
    # Grants models
    "TableGrants",
    "Grant",
    "EffectivePermission",
    # Schema analysis models
    "SchemaAnalysis",
    "SchemaAnomaly",
    "SchemaDriftAnalysis",
    "SchemaChange",
    # Delta history models
    "DeltaHistory",
    "DeltaHistoryEntry",
    # Access pattern models
    "AccessPatterns",
    "UserAccess",
    "DailyAccess",
    # Phase 2: Storage optimization
    "StorageState",
    "StorageRecommendation",
    "StorageOptimizationReport",
    "ImpactEstimate",
    # Phase 2: Query impact
    "JoinPrediction",
    "QueryImpactAnalysis",
    # Phase 2: Simulation
    "OptimizationScenario",
    "SimulationResult",
    # Phase 2: Fingerprint
    "ReadWorkloadMetrics",
    "WriteWorkloadMetrics",
    "CostMetrics",
    "WorkloadProfile",
    "TableFingerprint",
    # Phase 2: Cost
    "CostBreakdown",
    # Phase 2: Schema diff
    "ColumnDiff",
    "SchemaDiff",
    # Phase 2: Policy
    "PolicyGap",
    "PolicyCoverageReport",
    # Table discovery models
    "TableDiscoveryInput",
    "TableDiscoveryResult",
    "TableEnrichmentInput",
    "TableMetadataRequest",
    # Simple transform functions
    "resolve_3part",
    "transform_delta_history",
    "transform_table_lineage",
    "transform_table_metadata",
]
