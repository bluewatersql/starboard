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

from starboard_server.tools.domain.warehouse.chargeback import (
    ChargebackCalculator,
    PortfolioChargeback,
    UserAllocation,
    WarehouseChargeback,
    aggregate_user_chargebacks,
)
from starboard_server.tools.domain.warehouse.topology import (
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
    # Chargeback (local to starboard_server)
    "ChargebackCalculator",
    "PortfolioChargeback",
    "UserAllocation",
    "WarehouseChargeback",
    "aggregate_user_chargebacks",
    # Topology (local to starboard_server)
    "SimilarityMatch",
    "TopologyAnalysis",
    "TopologyAnalyzer",
    "TopologyInsight",
    "WorkloadCluster",
]
