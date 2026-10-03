# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Discovery heuristics — deterministic best-practice rules.

Heuristics pre-screen query results against thresholds before LLM analysis.
"""

from starboard.discovery.heuristics.base import (
    Dimension,
    HeuristicFinding,
    HeuristicRegistry,
    HeuristicRule,
    Severity,
    get_col,
    get_df,
)
from starboard.discovery.heuristics.billing import BILLING_RULES
from starboard.discovery.heuristics.compute import COMPUTE_RULES
from starboard.discovery.heuristics.governance import GOVERNANCE_RULES
from starboard.discovery.heuristics.jobs import JOB_RULES
from starboard.discovery.heuristics.query_perf import QUERY_PERF_RULES

__all__ = [
    "BILLING_RULES",
    "COMPUTE_RULES",
    "Dimension",
    "GOVERNANCE_RULES",
    "HeuristicFinding",
    "HeuristicRegistry",
    "HeuristicRule",
    "JOB_RULES",
    "QUERY_PERF_RULES",
    "Severity",
    "create_default_heuristic_registry",
    "get_col",
    "get_df",
]


def create_default_heuristic_registry() -> HeuristicRegistry:
    """Create a registry pre-loaded with all standard heuristic rules.

    Returns:
        HeuristicRegistry with billing, jobs, compute, query_perf,
        and governance rules registered.
    """
    return HeuristicRegistry(
        rules=(
            *BILLING_RULES,
            *JOB_RULES,
            *COMPUTE_RULES,
            *QUERY_PERF_RULES,
            *GOVERNANCE_RULES,
        )
    )
