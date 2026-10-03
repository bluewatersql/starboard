# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""A sample per-domain tool registered via the ``starboard.mcp_tools`` contract.

This is a minimal, dependency-light tool in the ``jobs`` domain. It exists to
prove the layered-catalog seam (Phase-3 B5) end-to-end: a separately-distributed
thin wheel declares an entry point, and Starboard's :class:`ToolCatalog`
discovers and instantiates it at runtime — without the tool being baked into any
Starboard wheel. A real plugin swaps this no-op logic for its domain tool.
"""

from __future__ import annotations

from typing import Any

from starboard.tools.plugins import SimpleToolPlugin

#: The domain this plugin's tool belongs to (hosts can enable tools by domain).
DOMAIN = "jobs"

#: The catalog key the tool registers under (matches the entry-point name).
TOOL_NAME = "sample_jobs_health"


class SampleJobsHealthTool:
    """A trivial, side-effect-free sample tool.

    Sample only: it names no internal namespace, backend, or shortlink and does
    no I/O. It returns a static descriptor so a host can confirm the tool was
    discovered and instantiated through the entry-point seam.
    """

    name = TOOL_NAME
    domain = DOMAIN

    def describe(self) -> dict[str, Any]:
        """Return a static self-description (stands in for real tool behavior)."""
        return {
            "name": self.name,
            "domain": self.domain,
            "summary": "Sample per-domain plugin tool (B5 reference scaffold).",
        }


#: Module-level plugin the entry point resolves to (see pyproject.toml).
sample_plugin = SimpleToolPlugin(
    name=TOOL_NAME,
    domain=DOMAIN,
    factory=SampleJobsHealthTool,
)
