# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Public port adapters (Phase-2 C5).

Working PUBLIC adapters for the four kernel-tier data-enablement ports. Each
wraps existing native code behind its Protocol; no new capability is added.
Internal adapters are Phase 3 and do not ship here.
"""

from starboard.adapters.ports.analytics_sql import AnalyticsSqlAdapter
from starboard.adapters.ports.native_diagnostic import NativeDiagnosticAdapter
from starboard.adapters.ports.sdk_dbfs_log import SdkDbfsLogAdapter
from starboard.adapters.ports.single_workspace_fleet import SingleWorkspaceFleetAdapter

__all__ = [
    "SdkDbfsLogAdapter",
    "NativeDiagnosticAdapter",
    "AnalyticsSqlAdapter",
    "SingleWorkspaceFleetAdapter",
]
