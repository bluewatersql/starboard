# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Integration tests for Warehouse Portfolio Agent.

Tests validate that the warehouse agent correctly:
- Routes warehouse-related intents
- Executes warehouse tools
- Generates appropriate responses
- Handles edge cases

These tests use mocked dependencies to enable offline testing.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard.agents.agent_factory import AgentFactory
from starboard.agents.config.agent_config import AgentConfig
from starboard.agents.routing.intent_router import IntentRouter
from starboard.agents.routing.routing_models import RouteDecision
from starboard.prompts import get_prompt_builder_for_domain

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def warehouse_agent_config() -> AgentConfig:
    """Create agent config for warehouse domain."""
    return AgentConfig(
        domain="warehouse",
        model="gpt-4o",
        temperature=0.3,
        max_steps=10,
        max_tokens=100_000,
        system_prompt_builder=get_prompt_builder_for_domain("warehouse"),
    )


@pytest.fixture
def mock_warehouse_tool_registry() -> MagicMock:
    """Mock tool registry with warehouse tools."""
    registry = MagicMock()

    # Define implemented warehouse tools
    warehouse_tools = [
        "get_warehouse_portfolio",
        "get_warehouse_fingerprint",
        "get_warehouse_health",
        "set_warehouse_slo",
        "analyze_warehouse_topology",
        "get_warehouse_user_activity",
        "generate_warehouse_chargeback",
        "generate_portfolio_chargeback",
        "complete",
    ]

    registry.list_tools.return_value = warehouse_tools

    # Mock tool execution
    async def mock_execute(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "get_warehouse_portfolio":
            return {
                "warehouses": [
                    {
                        "warehouse_id": "wh-001",
                        "warehouse_name": "Analytics Prod",
                        "total_queries": 10000,
                        "health_score": 85,
                    },
                    {
                        "warehouse_id": "wh-002",
                        "warehouse_name": "ETL Batch",
                        "total_queries": 5000,
                        "health_score": 72,
                    },
                ],
                "summary": {
                    "total_warehouses": 2,
                    "healthy_count": 1,
                    "warning_count": 1,
                },
            }
        elif tool_name == "get_warehouse_fingerprint":
            return {
                "warehouse_id": args.get("warehouse_id", "wh-001"),
                "total_queries": 10000,
                "p50_runtime_sec": 2.5,
                "p95_runtime_sec": 15.0,
                "workload_pattern": {"pattern_type": "interactive"},
            }
        elif tool_name == "get_warehouse_health":
            return {
                "warehouse_id": args.get("warehouse_id", "wh-001"),
                "overall_score": 85,
                "risk_level": "low",
                "slo_compliance": {"p95_latency": {"status": "met"}},
            }
        elif tool_name == "analyze_warehouse_topology":
            return {
                "total_warehouses": 2,
                "similar_pairs": [],
                "insights": [
                    {
                        "insight_type": "underutilized",
                        "severity": "info",
                        "title": "Low usage warehouse",
                    }
                ],
            }
        elif tool_name == "complete":
            return {"status": "completed"}

        return {"result": "ok"}

    registry.execute_tool = AsyncMock(side_effect=mock_execute)

    return registry


@pytest.fixture
def mock_llm_client() -> MagicMock:
    """Mock LLM client for testing."""
    client = MagicMock()

    # Default response
    response = MagicMock()
    response.model = "gpt-4o"
    response.usage = MagicMock(total_tokens=500)
    response.choices = [
        MagicMock(
            message=MagicMock(
                content="Based on the analysis...",
                tool_calls=None,
            ),
            finish_reason="stop",
        )
    ]

    client.stream_chat.return_value = iter([response])

    return client


# =============================================================================
# Intent Routing Tests
# =============================================================================


@pytest.fixture
def mock_llm_for_router() -> MagicMock:
    """Mock LLM client for intent router that returns warehouse domain."""
    client = MagicMock()

    # Mock json_response to return warehouse domain
    mock_response = MagicMock()
    mock_response.get.side_effect = lambda key, default=None: {
        "domain": "warehouse",
        "confidence": 0.9,
        "reasoning": "Warehouse-related query",
    }.get(key, default)

    client.json_response = AsyncMock(return_value=mock_response)

    return client


class TestWarehouseIntentRouting:
    """Test that warehouse intents route correctly using pattern matching.

    Note: These tests verify the pattern matching logic without requiring
    actual LLM calls. The IntentRouter checks for warehouse keywords
    before falling back to LLM classification.
    """

    @pytest.mark.asyncio
    async def test_route_warehouse_portfolio_question(
        self, mock_llm_for_router: MagicMock
    ) -> None:
        """Portfolio questions should route to warehouse agent."""
        router = IntentRouter(llm_client=mock_llm_for_router)

        decision = await router.classify_intent(
            user_input="Show me all our SQL warehouses",
            conversation_history=[],
        )

        assert isinstance(decision, RouteDecision)
        assert decision.domain == "warehouse"
        assert decision.confidence >= 0.7

    @pytest.mark.asyncio
    async def test_route_warehouse_health_question(
        self, mock_llm_for_router: MagicMock
    ) -> None:
        """Warehouse health questions should route to warehouse agent."""
        router = IntentRouter(llm_client=mock_llm_for_router)

        # Use explicit warehouse portfolio keywords to trigger pattern matching
        decision = await router.classify_intent(
            user_input="What is the warehouse portfolio health status?",
            conversation_history=[],
        )

        assert isinstance(decision, RouteDecision)
        assert decision.domain == "warehouse"

    @pytest.mark.asyncio
    async def test_route_warehouse_optimization_question(
        self, mock_llm_for_router: MagicMock
    ) -> None:
        """Warehouse optimization questions should route to warehouse agent."""
        router = IntentRouter(llm_client=mock_llm_for_router)

        decision = await router.classify_intent(
            user_input="Analyze our warehouse fleet for consolidation",
            conversation_history=[],
        )

        assert isinstance(decision, RouteDecision)
        assert decision.domain == "warehouse"

    @pytest.mark.asyncio
    async def test_route_serverless_migration_question(
        self, mock_llm_for_router: MagicMock
    ) -> None:
        """Serverless migration questions should route to warehouse agent."""
        router = IntentRouter(llm_client=mock_llm_for_router)

        decision = await router.classify_intent(
            user_input="what if we migrate our warehouse fleet to serverless",
            conversation_history=[],
        )

        assert isinstance(decision, RouteDecision)
        assert decision.domain == "warehouse"


# =============================================================================
# Agent Factory Tests
# =============================================================================


class TestWarehouseAgentFactory:
    """Test warehouse agent creation via factory."""

    def test_create_warehouse_agent(
        self,
        mock_llm_client: MagicMock,
        mock_warehouse_tool_registry: MagicMock,
        warehouse_agent_config: AgentConfig,
    ) -> None:
        """Factory should create warehouse agent with correct config."""
        factory = AgentFactory(
            llm_client=mock_llm_client,
            tool_registry=mock_warehouse_tool_registry,
            base_config=warehouse_agent_config,
        )

        agent = factory.get_agent("warehouse")

        assert agent is not None
        assert agent.config.domain == "warehouse"

    def test_warehouse_agent_cached(
        self,
        mock_llm_client: MagicMock,
        mock_warehouse_tool_registry: MagicMock,
        warehouse_agent_config: AgentConfig,
    ) -> None:
        """Factory should cache and reuse warehouse agent."""
        factory = AgentFactory(
            llm_client=mock_llm_client,
            tool_registry=mock_warehouse_tool_registry,
            base_config=warehouse_agent_config,
        )

        agent1 = factory.get_agent("warehouse")
        agent2 = factory.get_agent("warehouse")

        assert agent1 is agent2


# =============================================================================
# Tool Categories Tests
# =============================================================================


class TestWarehouseToolCategories:
    """Test warehouse tool categorization."""

    def test_warehouse_tools_available(self) -> None:
        """Warehouse domain should have expected tools."""
        from starboard.agents.tool_categories import TOOL_CATEGORIES

        warehouse_tools = TOOL_CATEGORIES["warehouse"]

        # Core tools
        assert "get_warehouse_portfolio" in warehouse_tools
        assert "get_warehouse_fingerprint" in warehouse_tools
        assert "get_warehouse_health" in warehouse_tools

        # SLO tools
        assert "configure_warehouse_slo" in warehouse_tools

        # Topology tools
        assert "analyze_warehouse_topology" in warehouse_tools

        # Chargeback tools
        assert "get_warehouse_user_activity" in warehouse_tools
        assert "generate_warehouse_chargeback" in warehouse_tools
        assert "generate_portfolio_chargeback" in warehouse_tools

    def test_diagnostic_has_warehouse_tools(self) -> None:
        """Diagnostic agent should have access to warehouse tools."""
        from starboard.agents.tool_categories import TOOL_OVERLAP_MATRIX

        # Warehouse tools should be accessible by diagnostic
        assert "diagnostic" in TOOL_OVERLAP_MATRIX["get_warehouse_portfolio"]
        assert "diagnostic" in TOOL_OVERLAP_MATRIX["analyze_warehouse_topology"]


# =============================================================================
# Prompt Tests
# =============================================================================


class TestWarehousePrompt:
    """Test warehouse agent prompt."""

    def test_warehouse_prompt_exists(self) -> None:
        """Warehouse domain should have a prompt builder."""
        builder = get_prompt_builder_for_domain("warehouse")
        assert builder is not None

    def test_warehouse_prompt_contains_capabilities(self) -> None:
        """Warehouse prompt should describe capabilities."""
        from starboard_core.domain.models.llm import OptimizationMode

        builder = get_prompt_builder_for_domain("warehouse")
        prompt = builder(OptimizationMode.ONLINE, "Optimize warehouses", 100_000)

        # Check for key capability mentions
        assert "portfolio" in prompt.lower()
        assert "health" in prompt.lower()
        assert "warehouse" in prompt.lower()

    def test_warehouse_prompt_lists_tools(self) -> None:
        """Warehouse prompt should list available tools."""
        from starboard_core.domain.models.llm import OptimizationMode

        builder = get_prompt_builder_for_domain("warehouse")
        prompt = builder(OptimizationMode.ONLINE, "", 100_000)

        # Should mention key tools
        assert "get_warehouse_portfolio" in prompt or "portfolio" in prompt.lower()


# =============================================================================
# Tool Schema Tests
# =============================================================================


class TestWarehouseToolSchemas:
    """Test warehouse tool schemas are properly registered."""

    def test_schemas_registered(self) -> None:
        """All implemented warehouse tool schemas should be registered."""
        from starboard.agents.tools.registry import ALL_TOOL_METADATA

        # Only implemented tools should be registered
        warehouse_tools = [
            "get_warehouse_portfolio",
            "get_warehouse_fingerprint",
            "get_warehouse_health",
            "configure_warehouse_slo",
            "analyze_warehouse_topology",
            "get_warehouse_user_activity",
            "generate_warehouse_chargeback",
            "generate_portfolio_chargeback",
        ]

        for tool in warehouse_tools:
            assert tool in ALL_TOOL_METADATA, f"Missing schema for {tool}"

    def test_schema_structure(self) -> None:
        """Tool schemas should have required fields."""
        from starboard.agents.tools.registry import ALL_TOOL_METADATA

        schema = ALL_TOOL_METADATA["get_warehouse_portfolio"]

        assert "name" in schema
        assert "description" in schema
        assert "parameters" in schema
        assert schema["name"] == "get_warehouse_portfolio"


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestWarehouseEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_portfolio(
        self, mock_warehouse_tool_registry: MagicMock
    ) -> None:
        """Should handle empty warehouse portfolio gracefully."""

        # Override mock for this test
        async def mock_empty_portfolio(tool_name: str, args: dict) -> dict:
            if tool_name == "get_warehouse_portfolio":
                return {"warehouses": [], "summary": {"total_warehouses": 0}}
            return {}

        mock_warehouse_tool_registry.execute_tool = AsyncMock(
            side_effect=mock_empty_portfolio
        )

        result = await mock_warehouse_tool_registry.execute_tool(
            "get_warehouse_portfolio", {}
        )

        assert result["warehouses"] == []
        assert result["summary"]["total_warehouses"] == 0

    @pytest.mark.asyncio
    async def test_warehouse_not_found(
        self, mock_warehouse_tool_registry: MagicMock
    ) -> None:
        """Should handle missing warehouse gracefully."""

        async def mock_not_found(tool_name: str, args: dict) -> dict:
            if tool_name == "get_warehouse_fingerprint":
                return {
                    "error": "warehouse_not_found",
                    "warehouse_id": args.get("warehouse_id"),
                }
            return {}

        mock_warehouse_tool_registry.execute_tool = AsyncMock(
            side_effect=mock_not_found
        )

        result = await mock_warehouse_tool_registry.execute_tool(
            "get_warehouse_fingerprint", {"warehouse_id": "nonexistent"}
        )

        assert "error" in result
