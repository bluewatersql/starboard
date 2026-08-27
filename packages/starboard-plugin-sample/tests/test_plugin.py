# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the reference per-domain plugin scaffold (Phase-3 B5).

Prove the scaffold's provider object satisfies the ``starboard.mcp_tools``
contract and is discoverable/instantiable through the layered-catalog seam, and
that its pyproject declares the entry point under the correct group.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from starboard.tools.plugins import (
    ENTRY_POINT_GROUP,
    ToolCatalog,
    ToolPlugin,
    register_tool_plugins,
)
from starboard_plugin_sample.plugin import (
    DOMAIN,
    TOOL_NAME,
    SampleJobsHealthTool,
    sample_plugin,
)

_PKG_DIR = Path(__file__).parents[1]


@pytest.mark.unit
class TestSamplePluginContract:
    def test_provider_satisfies_tool_plugin_protocol(self) -> None:
        assert isinstance(sample_plugin, ToolPlugin)
        assert sample_plugin.name == TOOL_NAME
        assert sample_plugin.domain == DOMAIN

    def test_registers_and_instantiates_via_catalog(self) -> None:
        catalog = register_tool_plugins(ToolCatalog(), [sample_plugin])
        assert catalog.names() == [TOOL_NAME]
        tool = catalog.create(TOOL_NAME)
        assert isinstance(tool, SampleJobsHealthTool)
        assert tool.describe() == {
            "name": TOOL_NAME,
            "domain": DOMAIN,
            "summary": "Sample per-domain plugin tool (B5 reference scaffold).",
        }


@pytest.mark.unit
class TestEntryPointDeclaration:
    def test_pyproject_declares_the_entry_point_under_the_contract_group(self) -> None:
        with (_PKG_DIR / "pyproject.toml").open("rb") as fh:
            data = tomllib.load(fh)
        group = data["project"]["entry-points"][ENTRY_POINT_GROUP]
        assert group[TOOL_NAME] == "starboard_plugin_sample.plugin:sample_plugin"
