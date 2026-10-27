# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Unit tests for MCP agent tool definitions and schemas."""

from starboard.mcp.agent_bridge import (
    _AGENT_DESCRIPTIONS,
    _MCP_EXCLUDED_AGENT_DOMAINS,
    AGENT_DOMAINS,
    AGENT_TOOL_METADATA,
    TOOL_NAME_TO_DOMAIN,
)


class TestAgentToolSchemas:
    """Tests for agent tool parameter schemas."""

    def test_mcp_exposed_agent_tools_registered(self) -> None:
        """Only non-excluded agents should appear in AGENT_TOOL_METADATA."""
        expected_count = len(AGENT_DOMAINS) - len(_MCP_EXCLUDED_AGENT_DOMAINS)
        assert len(AGENT_TOOL_METADATA) == expected_count
        names = {t["name"] for t in AGENT_TOOL_METADATA}
        expected = {
            "query_agent",
            "job_agent",
            "uc_agent",
            "cluster_agent",
            "analytics_agent",
            "warehouse_agent",
            "diagnostic_agent",
        }
        assert names == expected

    def test_excluded_agents_not_in_metadata(self) -> None:
        """Excluded domains must not appear in AGENT_TOOL_METADATA."""
        names = {t["name"] for t in AGENT_TOOL_METADATA}
        for domain in _MCP_EXCLUDED_AGENT_DOMAINS:
            assert f"{domain}_agent" not in names

    def test_each_tool_has_required_message(self) -> None:
        for tool in AGENT_TOOL_METADATA:
            params = tool["parameters"]
            assert params["required"] == ["message"], (
                f"{tool['name']} missing required message"
            )
            assert "message" in params["properties"]

    def test_each_tool_has_optional_workspace_id(self) -> None:
        for tool in AGENT_TOOL_METADATA:
            props = tool["parameters"]["properties"]
            assert "workspace_id" in props, f"{tool['name']} missing workspace_id"
            assert "workspace_id" not in tool["parameters"]["required"]

    def test_each_tool_has_optional_conversation_id(self) -> None:
        for tool in AGENT_TOOL_METADATA:
            props = tool["parameters"]["properties"]
            assert "conversation_id" in props, f"{tool['name']} missing conversation_id"

    def test_each_tool_has_config_overrides(self) -> None:
        for tool in AGENT_TOOL_METADATA:
            props = tool["parameters"]["properties"]
            assert "config_overrides" in props, (
                f"{tool['name']} missing config_overrides"
            )
            overrides = props["config_overrides"]
            assert "model" in overrides["properties"]
            assert "temperature" in overrides["properties"]
            assert "max_iterations" in overrides["properties"]


class TestAgentToolDescriptions:
    """Tests for agent tool descriptions matching spec D2."""

    def test_query_agent_description(self) -> None:
        desc = _AGENT_DESCRIPTIONS["query_agent"]
        assert "SQL query" in desc
        assert "execution plans" in desc

    def test_job_agent_description(self) -> None:
        desc = _AGENT_DESCRIPTIONS["job_agent"]
        assert "job" in desc.lower()
        assert "run history" in desc

    def test_uc_agent_description(self) -> None:
        desc = _AGENT_DESCRIPTIONS["uc_agent"]
        assert "Unity Catalog" in desc
        assert "lineage" in desc

    def test_cluster_agent_description(self) -> None:
        desc = _AGENT_DESCRIPTIONS["cluster_agent"]
        assert "cluster" in desc.lower()
        assert "autoscaling" in desc

    def test_analytics_agent_description(self) -> None:
        desc = _AGENT_DESCRIPTIONS["analytics_agent"]
        assert "FinOps" in desc
        assert "billing" in desc

    def test_warehouse_agent_description(self) -> None:
        desc = _AGENT_DESCRIPTIONS["warehouse_agent"]
        assert "warehouse" in desc.lower()
        assert "chargeback" in desc

    def test_diagnostic_agent_description(self) -> None:
        desc = _AGENT_DESCRIPTIONS["diagnostic_agent"]
        assert "Troubleshoot" in desc
        assert "root cause" in desc

    def test_discovery_agent_description(self) -> None:
        desc = _AGENT_DESCRIPTIONS["discovery_agent"]
        assert "workspace" in desc.lower()
        assert "discovery" in desc.lower()


class TestAgentToolDomainMapping:
    """Tests for agent tool → domain mapping."""

    def test_tool_name_to_domain_maps_all_eight(self) -> None:
        assert len(TOOL_NAME_TO_DOMAIN) == 8

    def test_agent_domain_pre_set_correctly(self) -> None:
        for domain in AGENT_DOMAINS:
            tool_name = f"{domain}_agent"
            assert TOOL_NAME_TO_DOMAIN[tool_name] == domain

    def test_tool_names_match_agent_domains_type(self) -> None:
        """Verify all mapped domains are valid AgentDomain values."""
        # AgentDomain is a Literal type — check each value is in the tuple
        for tool_name, domain in TOOL_NAME_TO_DOMAIN.items():
            assert domain in AGENT_DOMAINS, (
                f"{tool_name} maps to invalid domain {domain}"
            )

    def test_metadata_count_matches_exposed_domain_count(self) -> None:
        expected = len(AGENT_DOMAINS) - len(_MCP_EXCLUDED_AGENT_DOMAINS)
        assert len(AGENT_TOOL_METADATA) == expected
