# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Contract tests for MCP agent tools — schema stability and domain alignment."""

from starboard_server.agents.output.envelope_translator import DOMAIN_REPORT_TYPE_MAP
from starboard_server.mcp.agent_bridge import (
    AGENT_DOMAINS,
    AGENT_TOOL_METADATA,
    TOOL_NAME_TO_DOMAIN,
)


class TestAgentToolContract:
    """Contract tests ensuring MCP agent tools stay aligned with core routing."""

    def test_agent_tool_names_match_routing_models_domains(self) -> None:
        """Every AgentDomain has a corresponding MCP tool."""
        for domain in AGENT_DOMAINS:
            tool_name = f"{domain}_agent"
            assert tool_name in TOOL_NAME_TO_DOMAIN, (
                f"Domain {domain!r} has no MCP agent tool"
            )

    def test_agent_tool_input_schema_stable(self) -> None:
        """Schema structure must not change without notice."""
        for tool in AGENT_TOOL_METADATA:
            params = tool["parameters"]
            assert params["type"] == "object"
            assert "message" in params["properties"]
            assert params["required"] == ["message"]
            # message must be string
            assert params["properties"]["message"]["type"] == "string"

    def test_all_domains_in_report_type_map(self) -> None:
        """Every agent domain must have a report type mapping."""
        for domain in AGENT_DOMAINS:
            assert domain in DOMAIN_REPORT_TYPE_MAP, (
                f"Domain {domain!r} missing from DOMAIN_REPORT_TYPE_MAP"
            )

    def test_report_type_map_values(self) -> None:
        """Report type values match spec (D6)."""
        assert DOMAIN_REPORT_TYPE_MAP["query"] == "advisor"
        assert DOMAIN_REPORT_TYPE_MAP["job"] == "advisor"
        assert DOMAIN_REPORT_TYPE_MAP["uc"] == "advisor"
        assert DOMAIN_REPORT_TYPE_MAP["diagnostic"] == "advisor"
        assert DOMAIN_REPORT_TYPE_MAP["analytics"] == "analytics"
        assert DOMAIN_REPORT_TYPE_MAP["warehouse"] == "compute"
        assert DOMAIN_REPORT_TYPE_MAP["cluster"] == "compute"
        assert DOMAIN_REPORT_TYPE_MAP["discovery"] == "advisor"

    def test_no_duplicate_tool_names(self) -> None:
        names = [t["name"] for t in AGENT_TOOL_METADATA]
        assert len(names) == len(set(names)), "Duplicate agent tool names detected"
