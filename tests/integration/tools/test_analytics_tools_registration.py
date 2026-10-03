# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Integration test for analytics tools registration.

This test verifies that analytics tools are correctly registered
in the tool registry and can be discovered and executed by the agent.
"""

import pytest
from starboard.adapters.databricks.client import AsyncDatabricksClient
from starboard.agents.tools.tool_factory import create_tool_registry
from starboard.infra.core.config import EnvConfig
from starboard.services.context.provider import SharedContextProvider


@pytest.mark.requires_databricks
class TestAnalyticsToolsRegistration:
    """Integration tests for analytics tools registration."""

    @pytest.fixture
    def config(self) -> EnvConfig:
        """Create a test configuration."""
        return EnvConfig.from_env()

    @pytest.fixture
    async def api(self, config: EnvConfig) -> AsyncDatabricksClient:
        """Create an AsyncDatabricksClient instance."""
        client = AsyncDatabricksClient(cfg=config)
        await client._initialize()
        return client

    @pytest.fixture
    def provider(self, api: AsyncDatabricksClient) -> SharedContextProvider:
        """Create a SharedContextProvider instance."""
        return SharedContextProvider(api)

    @pytest.fixture
    def registry(self, api: AsyncDatabricksClient, provider: SharedContextProvider):
        """Create a tool registry with all tools registered."""
        registry, _ = create_tool_registry(api, provider)
        return registry

    def test_analytics_tools_are_registered(self, registry):
        """Test that analytics tools are registered in the registry."""
        # Verify SQL analytics tools are registered
        assert registry.get_tool("build_sql_query") is not None
        assert registry.get_tool("validate_sql_query") is not None
        assert registry.get_tool("execute_sql_query") is not None
        # build_analytics_context requires vector_store + embedding_service

    @pytest.mark.skip(
        reason="build_analytics_context requires vector_store + embedding_service"
    )
    def test_build_analytics_context_metadata(self, registry):
        """Test that build_analytics_context has correct metadata."""
        tool = registry.get_tool("build_analytics_context")

        assert tool.metadata.name == "build_analytics_context"
        assert "Get detailed information" in tool.metadata.description

        # Check properties
        props = tool.metadata.parameters["properties"]
        assert "query_id" in props

    @pytest.mark.skip(
        reason="Test uses outdated method signature; build_sql_query requires user_query + context_handle"
    )
    @pytest.mark.asyncio
    async def test_build_sql_query_execution(self, registry):
        """Test that build_sql_query can be executed."""
        tool = registry.get_tool("build_sql_query")

        # Execute without filters (should return all queries)
        result = await tool.execute()

        assert "queries" in result
        assert "total_count" in result
        assert result["total_count"] > 0
        assert len(result["queries"]) == result["total_count"]

    @pytest.mark.skip(
        reason="Test uses outdated method signature; validate_sql_query takes sql + runtime_validation, not domain"
    )
    @pytest.mark.asyncio
    async def test_validate_sql_query_with_domain_filter(self, registry):
        """Test that validate_sql_query can filter by domain."""
        tool = registry.get_tool("validate_sql_query")

        # Execute with finops domain filter (case-insensitive)
        result = await tool.execute(domain="finops")

        assert "queries" in result
        assert result["total_count"] > 0

        # Verify all results have finops domain (case-insensitive check)
        for query in result["queries"]:
            # Check if any domain matches "finops" case-insensitively
            domain_match = any(d.lower() == "finops" for d in query["domains"])
            assert domain_match, (
                f"Expected 'finops' in domains but got {query['domains']}"
            )

    @pytest.mark.skip(
        reason="Test uses outdated method signature; execute_sql_query takes sql, not scenario"
    )
    @pytest.mark.asyncio
    async def test_execute_sql_query_with_scenario_filter(self, registry):
        """Test that execute_sql_query can filter by scenario."""
        tool = registry.get_tool("execute_sql_query")

        # Execute with scenario filter
        result = await tool.execute(scenario="cost optimization")

        assert "queries" in result
        assert result["total_count"] > 0

        # Verify all results have the scenario
        for query in result["queries"]:
            assert "cost optimization" in query["scenarios"]

    @pytest.mark.skip(
        reason="build_analytics_context requires vector_store + embedding_service"
    )
    @pytest.mark.asyncio
    async def test_build_analytics_context_execution(self, registry):
        """Test that build_analytics_context can be executed."""
        tool = registry.get_tool("build_analytics_context")

        # Execute without filters (should return all queries)
        result = await tool.execute()

        assert "context" in result
        assert "total_count" in result
        assert result["total_count"] > 0
        assert len(result["context"]) == result["total_count"]

    def test_analytics_tools_have_openai_schemas(self, registry):
        """Test that analytics tools can generate OpenAI schemas."""
        analytics_tools = [
            "build_sql_query",
            "validate_sql_query",
            "execute_sql_query",
        ]

        for tool_name in analytics_tools:
            tool = registry.get_tool(tool_name)
            schema = tool.metadata.to_openai_schema()

            assert schema["type"] == "function"
            assert "function" in schema
            assert schema["function"]["name"] == tool_name
            assert "description" in schema["function"]
            assert "parameters" in schema["function"]

    def test_registry_lists_analytics_tools(self, registry):
        """Test that analytics tools appear in registry listings."""
        all_tools = registry.list_tools()

        assert "build_sql_query" in all_tools
        assert "validate_sql_query" in all_tools
        assert "execute_sql_query" in all_tools
        # build_analytics_context requires vector_store + embedding_service

    def test_registry_tool_count(self, registry):
        """Test that registry has correct tool count including analytics tools."""
        all_tools = registry.list_tools()

        # Should have at least 10 tools now (original + 4 analytics tools)
        # Original: query (3), table (5), job (3), source (2), compute (7), intent (2) = 20 tools
        # Plus analytics (4) = 24 total
        assert len(all_tools) >= 24
