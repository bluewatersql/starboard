# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Port selection seam for the internal-data enablement gate (Phase-2 C5, Phase-3 D-3.1).

Exposes the manual :class:`PortRegistry` (C5) plus the ``starboard.port_adapters``
entry-point discovery contract (D-3.1) that layers distributed adapters — public
or gated-internal — onto the registry.
"""

from starboard.ports.discovery import (
    ENTRY_POINT_GROUP,
    INTERNAL_TIER,
    PUBLIC_TIER,
    PortAdapterProvider,
    SimplePortAdapterProvider,
    discover_providers,
    install_entry_point_adapters,
    register_providers,
)
from starboard.ports.registry import Port, PortRegistry

__all__ = [
    "Port",
    "PortRegistry",
    "ENTRY_POINT_GROUP",
    "PUBLIC_TIER",
    "INTERNAL_TIER",
    "PortAdapterProvider",
    "SimplePortAdapterProvider",
    "discover_providers",
    "register_providers",
    "install_entry_point_adapters",
]
