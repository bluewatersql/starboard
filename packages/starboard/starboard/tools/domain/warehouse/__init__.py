# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Warehouse domain logic.

This module contains pure domain logic for warehouse analysis.
Core analyzers are in starboard_core and re-exported here for backward compatibility.
"""

# Re-export analyzers from starboard_core
from starboard_core.domain.analyzers.warehouse_analyzer import (
    FingerprintCalculator,
    HealthScorer,
    QueryRecord,
)

from starboard.tools.domain.warehouse.chargeback import (
    ChargebackCalculator,
    PortfolioChargeback,
    UserAllocation,
    WarehouseChargeback,
    aggregate_user_chargebacks,
)
from starboard.tools.domain.warehouse.topology import (
    SimilarityMatch,
    TopologyAnalysis,
    TopologyAnalyzer,
    TopologyInsight,
    WorkloadCluster,
)

__all__ = [
    # Re-exported from starboard_core
    "FingerprintCalculator",
    "HealthScorer",
    "QueryRecord",
    # Chargeback (local to starboard)
    "ChargebackCalculator",
    "PortfolioChargeback",
    "UserAllocation",
    "WarehouseChargeback",
    "aggregate_user_chargebacks",
    # Topology (local to starboard)
    "SimilarityMatch",
    "TopologyAnalysis",
    "TopologyAnalyzer",
    "TopologyInsight",
    "WorkloadCluster",
]
