# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Entry-point providers for the gated internal port adapters (Phase-3 D6/D7/D8).

This module is the target of the ``starboard.port_adapters`` entry points declared
in ``pyproject.toml``. It exposes one module-level :class:`PortAdapterProvider`
per port, each ``internal``-tier so it is selected **only** when the internal-data
enablement gate is open (UNIFIED_PLAN §3.5): with the gate closed, the public
adapter shipped in ``starboard`` remains the universal path.

Each provider's zero-arg ``create()`` builds the adapter with its default backend:
the **real** backend constructed from the internal deployment env
(``STARBOARD_INTERNAL_*`` — see :mod:`starboard_internal._config`) when present,
else an *unwired* backend whose methods raise a clean, actionable
:class:`~starboard_internal._config.MissingInternalConfigError` (never a silent
stub). ``create()`` itself never does I/O or raises, so the seam registers
cleanly with the gate closed. Tests inject their own backends. The four adapters
are strict supersets of their public counterparts:

* :class:`LogsSummariserAdapter` (D6) supersedes the public DBFS log parser,
* :class:`DbrDoctorAdapter` (D6) supersedes the native diagnostic backend,
* :class:`CentralizedFleetSqlAdapter` (D7) supersedes single-workspace fleet SQL,
* :class:`CuratedGenieRoomAdapter` (D8) supersedes native NL->SQL generation.
"""

from __future__ import annotations

from starboard.ports.discovery import INTERNAL_TIER, SimplePortAdapterProvider
from starboard.ports.registry import Port

from starboard_internal.centralized_fleet_adapter import CentralizedFleetSqlAdapter
from starboard_internal.curated_genie_adapter import CuratedGenieRoomAdapter
from starboard_internal.dbr_doctor_adapter import DbrDoctorAdapter
from starboard_internal.logs_summariser_adapter import LogsSummariserAdapter

#: LogRetrievalPort -> logs-summariser indexed triage (D6).
log_retrieval_provider = SimplePortAdapterProvider(
    port=Port.LOG_RETRIEVAL,
    factory=LogsSummariserAdapter,
    tier=INTERNAL_TIER,
)

#: DiagnosticBackendPort -> dbr-doctor semantic layer + trace-RCA (D6).
diagnostic_backend_provider = SimplePortAdapterProvider(
    port=Port.DIAGNOSTIC_BACKEND,
    factory=DbrDoctorAdapter,
    tier=INTERNAL_TIER,
)

#: FleetSqlPort -> centralized cross-account namespace rewrite (D7 / D-3.4).
fleet_sql_provider = SimplePortAdapterProvider(
    port=Port.FLEET_SQL,
    factory=CentralizedFleetSqlAdapter,
    tier=INTERNAL_TIER,
)

#: NLQueryPort -> curated Genie rooms (D8 / D-3.5).
nl_query_provider = SimplePortAdapterProvider(
    port=Port.NL_QUERY,
    factory=CuratedGenieRoomAdapter,
    tier=INTERNAL_TIER,
)

__all__ = [
    "log_retrieval_provider",
    "diagnostic_backend_provider",
    "fleet_sql_provider",
    "nl_query_provider",
    "CentralizedFleetSqlAdapter",
    "CuratedGenieRoomAdapter",
    "DbrDoctorAdapter",
    "LogsSummariserAdapter",
]
