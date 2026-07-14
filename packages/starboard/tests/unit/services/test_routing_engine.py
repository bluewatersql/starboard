# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for routing engine.

Phase 3 Component 2: Routing Decision Engine

Tests cover:
- RoutingDecision domain model
- RoutingEngine routing logic
- Explicit routing detection
- Non-routing cases (tool_call, continue)
- Handoff context building
- Capability inference
- Missing target agent handling
"""

import pytest
from pydantic import BaseModel
from starboard.agents.config.registry import (
    AgentCapability,
    AgentMetadata,
    AgentRegistry,
    AgentStatus,
)
from starboard.domain.models.conversation_patterns import (
    ActionType,
    NextStepOption,
)
from starboard.services.messaging.routing_engine import (
    RoutingDecision,
    RoutingEngine,
)


# Mock schemas for testing (named without Test prefix to avoid pytest collection)
class MockInputSchema(BaseModel):
    """Mock input schema for testing."""

    query: str


class MockOutputSchema(BaseModel):
    """Mock output schema for testing."""

    results: list[str]


class TestRoutingDecision:
    """Tests for RoutingDecision domain model."""

    def test_decision_creation_with_routing(self):
        """RoutingDecision can be created for routing case."""
        decision = RoutingDecision(
            should_route=True,
            target_agent_id="performance_analyzer",
            capability_id="identify_slow_queries",
            handoff_context={"warehouse_id": "prod_dw"},
            confidence=1.0,
            reasoning="Explicit routing to Performance Analyzer",
        )

        assert decision.should_route is True
        assert decision.target_agent_id == "performance_analyzer"
        assert decision.capability_id == "identify_slow_queries"
        assert decision.handoff_context["warehouse_id"] == "prod_dw"
        assert decision.confidence == 1.0
        assert "Explicit routing" in decision.reasoning

    def test_decision_creation_no_routing(self):
        """RoutingDecision can be created for non-routing case."""
        decision = RoutingDecision(
            should_route=False,
            target_agent_id=None,
            capability_id=None,
            handoff_context={},
            confidence=1.0,
            reasoning="Option does not require routing",
        )

        assert decision.should_route is False
        assert decision.target_agent_id is None
        assert decision.capability_id is None
        assert len(decision.handoff_context) == 0

    def test_decision_immutable(self):
        """RoutingDecision is immutable (frozen dataclass)."""
        decision = RoutingDecision(
            should_route=True,
            target_agent_id="test",
            capability_id=None,
            handoff_context={},
            confidence=1.0,
            reasoning="Test",
        )

        with pytest.raises(AttributeError):
            decision.should_route = False  # type: ignore


class TestRoutingEngine:
    """Tests for RoutingEngine."""

    @pytest.fixture
    def registry(self):
        """Create registry with test agents."""
        registry = AgentRegistry()

        # Register performance analyzer
        perf_capability = AgentCapability(
            capability_id="identify_slow_queries",
            name="Identify Slow Queries",
            description="Find slowest queries",
            keywords=("slow", "slowest", "performance", "queries"),
            input_schema=MockInputSchema,
            output_schema=MockOutputSchema,
            example_queries=(),
        )
        perf_metadata = AgentMetadata(
            agent_id="performance_analyzer",
            agent_name="Performance Analyzer",
            agent_class="PerformanceAnalyzerAgent",
            description="Analyzes query performance",
            capabilities=(perf_capability,),
            status=AgentStatus.ACTIVE,
            version="1.0.0",
        )
        registry.register(perf_metadata)

        # Register cost analyzer
        cost_capability = AgentCapability(
            capability_id="analyze_costs",
            name="Analyze Costs",
            description="Analyze query costs",
            keywords=("cost", "spend", "budget"),
            input_schema=MockInputSchema,
            output_schema=MockOutputSchema,
            example_queries=(),
        )
        cost_metadata = AgentMetadata(
            agent_id="cost_analyzer",
            agent_name="Cost Analyzer",
            agent_class="CostAnalyzerAgent",
            description="Analyzes query costs",
            capabilities=(cost_capability,),
            status=AgentStatus.ACTIVE,
            version="1.0.0",
        )
        registry.register(cost_metadata)

        return registry

    @pytest.fixture
    def engine(self, registry):
        """Create routing engine."""
        return RoutingEngine(registry=registry)

    def test_explicit_routing_decision(self, engine):
        """Route option with action_type='route' triggers routing."""
        option = NextStepOption(
            id="route_to_perf",
            number=1,
            title="Identify slowest queries",
            description="Find the slowest queries in warehouse",
            action_type=ActionType.ROUTE,
            target_agent="performance_analyzer",
            tool_name=None,
            parameters={"warehouse_id": "prod_dw"},
        )

        decision = engine.should_route(
            selected_option=option,
            current_agent="query_optimizer",
            conversation_summary="User asked about query performance",
        )

        assert decision.should_route is True
        assert decision.target_agent_id == "performance_analyzer"
        assert decision.confidence == 1.0
        assert decision.handoff_context["parameters"]["warehouse_id"] == "prod_dw"

    def test_tool_call_no_routing(self, engine):
        """Tool call options don't trigger routing."""
        option = NextStepOption(
            id="optimize",
            number=1,
            title="Optimize query",
            description="Generate optimized query",
            action_type=ActionType.TOOL_CALL,
            target_agent=None,
            tool_name="generate_optimized_query",
            parameters={"query_id": "123"},
        )

        decision = engine.should_route(
            selected_option=option,
            current_agent="query_optimizer",
            conversation_summary="",
        )

        assert decision.should_route is False
        assert decision.target_agent_id is None

    def test_continue_no_routing(self, engine):
        """Continue options don't trigger routing."""
        option = NextStepOption(
            id="continue",
            number=1,
            title="Continue analysis",
            description="Continue with current agent",
            action_type=ActionType.CONTINUE,
            target_agent=None,
            tool_name=None,
            parameters={},
        )

        decision = engine.should_route(
            selected_option=option,
            current_agent="query_optimizer",
            conversation_summary="",
        )

        assert decision.should_route is False
        assert decision.target_agent_id is None

    def test_routing_with_missing_agent(self, engine):
        """Gracefully handle routing to nonexistent agent."""
        option = NextStepOption(
            id="route_to_missing",
            number=1,
            title="Do something",
            description=None,
            action_type=ActionType.ROUTE,
            target_agent="nonexistent_agent",
            tool_name=None,
            parameters={},
        )

        decision = engine.should_route(
            selected_option=option,
            current_agent="query_optimizer",
            conversation_summary="",
        )

        assert decision.should_route is False
        assert "not found" in decision.reasoning.lower()

    def test_handoff_context_includes_parameters(self, engine):
        """Handoff context includes option parameters."""
        option = NextStepOption(
            id="route_to_perf",
            number=1,
            title="Identify slowest queries",
            description=None,
            action_type=ActionType.ROUTE,
            target_agent="performance_analyzer",
            tool_name=None,
            parameters={"warehouse_id": "prod_dw", "limit": 10},
        )

        decision = engine.should_route(
            selected_option=option,
            current_agent="query_optimizer",
            conversation_summary="User analyzing performance",
        )

        assert decision.should_route is True
        assert decision.handoff_context["parameters"]["warehouse_id"] == "prod_dw"
        assert decision.handoff_context["parameters"]["limit"] == 10

    def test_handoff_context_includes_source_agent(self, engine):
        """Handoff context includes source agent ID."""
        option = NextStepOption(
            id="route_to_perf",
            number=1,
            title="Identify slowest queries",
            description=None,
            action_type=ActionType.ROUTE,
            target_agent="performance_analyzer",
            tool_name=None,
            parameters={},
        )

        decision = engine.should_route(
            selected_option=option,
            current_agent="query_optimizer",
            conversation_summary="",
        )

        assert decision.handoff_context["source_agent"] == "query_optimizer"

    def test_handoff_context_includes_handoff_reason(self, engine):
        """Handoff context includes reason (option title)."""
        option = NextStepOption(
            id="route_to_perf",
            number=1,
            title="Identify slowest queries for warehouse",
            description=None,
            action_type=ActionType.ROUTE,
            target_agent="performance_analyzer",
            tool_name=None,
            parameters={},
        )

        decision = engine.should_route(
            selected_option=option,
            current_agent="query_optimizer",
            conversation_summary="",
        )

        assert (
            decision.handoff_context["handoff_reason"]
            == "Identify slowest queries for warehouse"
        )

    def test_handoff_context_includes_conversation_summary(self, engine):
        """Handoff context includes conversation summary."""
        option = NextStepOption(
            id="route_to_perf",
            number=1,
            title="Identify slowest queries",
            description=None,
            action_type=ActionType.ROUTE,
            target_agent="performance_analyzer",
            tool_name=None,
            parameters={},
        )

        summary = "User asked about query performance in prod warehouse"

        decision = engine.should_route(
            selected_option=option,
            current_agent="query_optimizer",
            conversation_summary=summary,
        )

        assert decision.handoff_context["conversation_summary"] == summary

    def test_capability_inference_from_keywords(self, engine):
        """Capability is inferred from option keywords."""
        option = NextStepOption(
            id="route_to_perf",
            number=1,
            title="Find the slowest queries",
            description="Identify performance bottlenecks",
            action_type=ActionType.ROUTE,
            target_agent="performance_analyzer",
            tool_name=None,
            parameters={},
        )

        decision = engine.should_route(
            selected_option=option,
            current_agent="query_optimizer",
            conversation_summary="",
        )

        # Should match "identify_slow_queries" capability
        # based on keywords "slowest" and "queries"
        assert decision.capability_id == "identify_slow_queries"

    def test_capability_inference_no_match(self, engine):
        """Capability inference returns None if no keyword match."""
        option = NextStepOption(
            id="route_to_cost",
            number=1,
            title="Analyze costs",
            description="Check spending",
            action_type=ActionType.ROUTE,
            target_agent="cost_analyzer",
            tool_name=None,
            parameters={},
        )

        decision = engine.should_route(
            selected_option=option,
            current_agent="query_optimizer",
            conversation_summary="",
        )

        # Should match "analyze_costs" capability
        assert decision.capability_id == "analyze_costs"

    def test_routing_decision_confidence(self, engine):
        """Explicit routing has confidence 1.0."""
        option = NextStepOption(
            id="route_to_perf",
            number=1,
            title="Identify slowest queries",
            description=None,
            action_type=ActionType.ROUTE,
            target_agent="performance_analyzer",
            tool_name=None,
            parameters={},
        )

        decision = engine.should_route(
            selected_option=option,
            current_agent="query_optimizer",
            conversation_summary="",
        )

        assert decision.confidence == 1.0

    def test_routing_with_empty_parameters(self, engine):
        """Routing works with None parameters."""
        option = NextStepOption(
            id="route_to_perf",
            number=1,
            title="Identify slowest queries",
            description=None,
            action_type=ActionType.ROUTE,
            target_agent="performance_analyzer",
            tool_name=None,
            parameters=None,  # None instead of dict
        )

        decision = engine.should_route(
            selected_option=option,
            current_agent="query_optimizer",
            conversation_summary="",
        )

        assert decision.should_route is True
        assert decision.handoff_context["parameters"] == {}

    def test_routing_reasoning_includes_target_agent(self, engine):
        """Routing reasoning mentions target agent."""
        option = NextStepOption(
            id="route_to_perf",
            number=1,
            title="Identify slowest queries",
            description=None,
            action_type=ActionType.ROUTE,
            target_agent="performance_analyzer",
            tool_name=None,
            parameters={},
        )

        decision = engine.should_route(
            selected_option=option,
            current_agent="query_optimizer",
            conversation_summary="",
        )

        assert "Performance Analyzer" in decision.reasoning

    def test_handoff_context_structure(self, engine):
        """Handoff context has expected structure."""
        option = NextStepOption(
            id="route_to_perf",
            number=1,
            title="Test routing",
            description=None,
            action_type=ActionType.ROUTE,
            target_agent="performance_analyzer",
            tool_name=None,
            parameters={"test": "value"},
        )

        decision = engine.should_route(
            selected_option=option,
            current_agent="source_agent",
            conversation_summary="Test summary",
        )

        # Check all expected keys
        assert "source_agent" in decision.handoff_context
        assert "handoff_reason" in decision.handoff_context
        assert "parameters" in decision.handoff_context
        assert "conversation_summary" in decision.handoff_context
