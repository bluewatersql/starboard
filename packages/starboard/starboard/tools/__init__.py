# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Agent tools for executable tasks in optimization workflows.

Tool architecture:
- Domain layer: Pure business logic
- Service layer: Orchestration and coordination
- Adapter layer: Tool interface implementations

Per-domain plugin discovery (Phase-3 B5): the ``starboard.mcp_tools``
entry-point contract for layering optional per-domain tool plugins onto the
built-in surface. See :mod:`starboard.tools.plugins`.
"""

# Tool implementations live in the adapters layer (import directly from
# tools.adapters). The layered-catalog plugin-discovery contract (B5) is
# re-exported here; it is kernel-light and drags in no heavy deps.
from starboard.tools.plugins import (
    ENTRY_POINT_GROUP,
    SimpleToolPlugin,
    ToolCatalog,
    ToolPlugin,
    discover_tool_plugins,
    install_entry_point_tools,
    register_tool_plugins,
)

__all__: list[str] = [
    "ENTRY_POINT_GROUP",
    "SimpleToolPlugin",
    "ToolCatalog",
    "ToolPlugin",
    "discover_tool_plugins",
    "install_entry_point_tools",
    "register_tool_plugins",
]
