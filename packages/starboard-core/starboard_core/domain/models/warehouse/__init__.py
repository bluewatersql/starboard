"""Warehouse domain models.

Pure domain models for warehouse analysis, health scoring, and SLO management.
"""

from starboard_core.domain.models.warehouse.fingerprint import (
    QueryTypeDistribution,
    TimeDistribution,
    WarehouseFingerprint,
    WorkloadPattern,
)
from starboard_core.domain.models.warehouse.health import (
    HealthSummary,
    RiskFactor,
    SLOStatus,
)
from starboard_core.domain.models.warehouse.inputs import (
    PortfolioChargebackInput,
    WarehouseChargebackInput,
    WarehouseFingerprintInput,
    WarehouseHealthInput,
    WarehousePortfolioInput,
    WarehouseSLOConfigInput,
    WarehouseTopologyInput,
    WarehouseUserActivityInput,
)
from starboard_core.domain.models.warehouse.portfolio import (
    WarehouseInfo,
    WarehousePortfolio,
    WarehouseSummary,
)
from starboard_core.domain.models.warehouse.slo import (
    DEFAULT_BATCH_SLOS,
    DEFAULT_INTERACTIVE_SLOS,
    SLOConfig,
    SLOTarget,
    SLOType,
)

__all__ = [
    # Fingerprint
    "QueryTypeDistribution",
    "TimeDistribution",
    "WarehouseFingerprint",
    "WorkloadPattern",
    # Health
    "HealthSummary",
    "RiskFactor",
    "SLOStatus",
    # Portfolio
    "WarehouseInfo",
    "WarehousePortfolio",
    "WarehouseSummary",
    # SLO
    "DEFAULT_BATCH_SLOS",
    "DEFAULT_INTERACTIVE_SLOS",
    "SLOConfig",
    "SLOTarget",
    "SLOType",
    # Inputs
    "PortfolioChargebackInput",
    "WarehouseChargebackInput",
    "WarehouseFingerprintInput",
    "WarehouseHealthInput",
    "WarehousePortfolioInput",
    "WarehouseSLOConfigInput",
    "WarehouseTopologyInput",
    "WarehouseUserActivityInput",
]
