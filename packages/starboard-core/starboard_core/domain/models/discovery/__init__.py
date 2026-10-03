# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Discovery domain models.

Pure types for the workspace discovery and health assessment pipeline.
All consumption metrics expressed in DBUs (never dollars).
"""

from starboard_core.domain.models.discovery.analysis import (
    DataCoverage,
    DiscoveryFinding,
    DomainAnalysis,
    Evidence,
    FindingType,
    Grade,
    ImpactLevel,
    LikelyCause,
    Priority,
    Remediation,
)
from starboard_core.domain.models.discovery.query import (
    PackResult,
    QueryPack,
    QueryResult,
    SystemQuery,
)
from starboard_core.domain.models.discovery.report import (
    AnalysisContext,
    DiscoveryReport,
    ExecutiveSummary,
    ReportCard,
    ReportMetadata,
    SourceProof,
)

__all__ = [
    # Query types
    "SystemQuery",
    "QueryPack",
    "QueryResult",
    "PackResult",
    # Analysis types
    "Evidence",
    "LikelyCause",
    "Remediation",
    "DiscoveryFinding",
    "FindingType",
    "Priority",
    "ImpactLevel",
    "Grade",
    "DataCoverage",
    "DomainAnalysis",
    # Report types
    "AnalysisContext",
    "ReportCard",
    "ExecutiveSummary",
    "SourceProof",
    "ReportMetadata",
    "DiscoveryReport",
]
