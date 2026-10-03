# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Protocol interfaces for pluggable state management and internal-data ports.

The state/memory/cache ports back pluggable persistence. The four data-enablement
ports (Phase-2 C5, D-2.10) — ``LogRetrievalPort``, ``DiagnosticBackendPort``,
``NLQueryPort``, ``FleetSqlPort`` — are typing-only, SDK-free Protocols; their
PUBLIC adapters live in ``starboard`` and internal adapters attach in Phase 3.
"""

from starboard_core.ports.cache_store import CacheMetrics, CacheStore
from starboard_core.ports.diagnostic_backend import (
    Candidate,
    DiagnosticBackendPort,
    DiagnosticResult,
)
from starboard_core.ports.fleet_sql import FleetQuery, FleetResult, FleetSqlPort
from starboard_core.ports.log_retrieval import (
    LogBundle,
    LogQuery,
    LogRetrievalPort,
)
from starboard_core.ports.memory_store import MemoryStore
from starboard_core.ports.nl_query import NLAnswer, NLQueryPort, WorkspaceCtx
from starboard_core.ports.state_store import StateStore

__all__ = [
    # Persistence ports
    "StateStore",
    "MemoryStore",
    "CacheStore",
    "CacheMetrics",
    # Internal-data enablement ports (C5) + their DTOs
    "LogRetrievalPort",
    "LogQuery",
    "LogBundle",
    "DiagnosticBackendPort",
    "Candidate",
    "DiagnosticResult",
    "NLQueryPort",
    "WorkspaceCtx",
    "NLAnswer",
    "FleetSqlPort",
    "FleetQuery",
    "FleetResult",
]
