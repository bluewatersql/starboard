# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Unit tests for MCP tool bridge."""

from starboard_server.agents.tools.registry import ALL_TOOL_METADATA
from starboard_server.mcp.tool_bridge import (
    _INTERNAL_TOOLS,
    PHASE_A_TOOLS,
    SAFE_MODE_ALLOWED_TOOLS,
    get_mcp_tools,
    tool_metadata_to_mcp_schema,
)


class TestPhaseAToolsConstant:
    """Tests for the PHASE_A_TOOLS constant."""

    def test_phase_a_tools_count_is_11(self) -> None:
        assert len(PHASE_A_TOOLS) == 11

    def test_phase_a_tools_exist_in_registry(self) -> None:
        for name in PHASE_A_TOOLS:
            assert name in ALL_TOOL_METADATA, f"{name} not in ALL_TOOL_METADATA"

    def test_phase_a_tools_excludes_internal_tools(self) -> None:
        for name in _INTERNAL_TOOLS:
            assert name not in PHASE_A_TOOLS


class TestToolMetadataToMCPSchema:
    """Tests for tool_metadata_to_mcp_schema."""

    def test_includes_workspace_id(self) -> None:
        meta = ALL_TOOL_METADATA["resolve_query"]
        schema = tool_metadata_to_mcp_schema(meta)
        props = schema["inputSchema"]["properties"]
        assert "workspace_id" in props
        assert props["workspace_id"]["type"] == "string"

    def test_preserves_required_params(self) -> None:
        meta = ALL_TOOL_METADATA["resolve_query"]
        schema = tool_metadata_to_mcp_schema(meta)
        assert "target" in schema["inputSchema"].get("required", [])

    def test_workspace_id_not_required(self) -> None:
        meta = ALL_TOOL_METADATA["resolve_query"]
        schema = tool_metadata_to_mcp_schema(meta)
        assert "workspace_id" not in schema["inputSchema"].get("required", [])

    def test_preserves_name_and_description(self) -> None:
        meta = ALL_TOOL_METADATA["resolve_query"]
        schema = tool_metadata_to_mcp_schema(meta)
        assert schema["name"] == "resolve_query"
        assert len(schema["description"]) > 0

    def test_does_not_mutate_original(self) -> None:
        meta = ALL_TOOL_METADATA["resolve_query"]
        original_props = set(meta["parameters"]["properties"].keys())
        tool_metadata_to_mcp_schema(meta)
        assert set(meta["parameters"]["properties"].keys()) == original_props


class TestGetMCPTools:
    """Tests for get_mcp_tools."""

    def test_normal_mode_returns_phase_a_tools(self) -> None:
        tools = get_mcp_tools(safe_mode=False)
        names = {t["name"] for t in tools}
        assert names == PHASE_A_TOOLS

    def test_safe_mode_returns_only_safe_tools(self) -> None:
        tools = get_mcp_tools(safe_mode=True)
        names = {t["name"] for t in tools}
        assert names == SAFE_MODE_ALLOWED_TOOLS

    def test_excludes_internal_tools(self) -> None:
        tools = get_mcp_tools(safe_mode=False)
        names = {t["name"] for t in tools}
        for internal in _INTERNAL_TOOLS:
            assert internal not in names

    def test_full_scope_excludes_internal_tools(self) -> None:
        tools = get_mcp_tools(safe_mode=False, tool_scope="full")
        names = {t["name"] for t in tools}
        for internal in _INTERNAL_TOOLS:
            assert internal not in names

    def test_run_workspace_discovery_is_internal(self) -> None:
        assert "run_workspace_discovery" in _INTERNAL_TOOLS

    def test_all_tools_have_input_schema(self) -> None:
        tools = get_mcp_tools(safe_mode=False)
        for tool in tools:
            assert "inputSchema" in tool
            assert "properties" in tool["inputSchema"]

    def test_tools_sorted_by_name(self) -> None:
        tools = get_mcp_tools(safe_mode=False)
        names = [t["name"] for t in tools]
        assert names == sorted(names)
