# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Starboard internal-adapter package (Phase-3 D-3.1 seam skeleton).

This package is distributed on an **internal index only** and is NOT a
dependency of any public wheel (``starboard`` / ``starboard-core`` /
``starboard-skills``). It registers gated internal adapters through the public
``starboard.port_adapters`` entry-point contract; an import-linter contract
forbids the public packages from importing ``starboard_internal.*``.

This package ships the four gated internal adapters (D6/D7/D8), each a strict
superset of its public counterpart:

* ``LogsSummariserAdapter`` (``LogRetrievalPort``, D6) — indexed ClickHouse triage.
* ``DbrDoctorAdapter`` (``DiagnosticBackendPort``, D6) — semantic layer + trace-RCA.
* ``CentralizedFleetSqlAdapter`` (``FleetSqlPort``, D7) — centralized namespace rewrite.
* ``CuratedGenieRoomAdapter`` (``NLQueryPort``, D8) — curated Genie rooms.

Nothing in this package is selected unless the internal-data enablement gate is
open (§3.5 additive invariant): with the gate closed, the public adapter remains
the universal path and no capability is lost.
"""

__version__ = "0.1.0"
