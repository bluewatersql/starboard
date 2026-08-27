# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Reference per-domain tool plugin for Starboard's layered catalog (Phase-3 B5).

Scaffold only. See :mod:`starboard_plugin_sample.plugin` for the plugin object
that ``pyproject.toml`` registers under the ``starboard.mcp_tools`` entry point.
"""

from starboard_plugin_sample.plugin import SampleJobsHealthTool, sample_plugin

__all__ = ["SampleJobsHealthTool", "sample_plugin"]
