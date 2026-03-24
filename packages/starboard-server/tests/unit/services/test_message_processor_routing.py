"""Tests for message processor routing integration.

Phase 3 Component 4: Message Processor Integration

Tests cover:
- Routing detection from option selection
- Routing decision execution
- Handoff initiation and completion
- Context preservation across handoffs
- Routing failure handling
- Circular routing prevention
- Backward compatibility with Phase 1 & 2
"""

from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from pydantic import BaseModel
from starboard_server.agents.config.registry import (
    AgentCapability,
    AgentMetadata,
    AgentRegistry,
    AgentStatus,
)
from starboard_server.domain.models.conversation_patterns import (
    ActionType,
    NextStepOption,
)
from starboard_server.services.coordination.handoff_manager import (
    AgentHandoff,
    HandoffManager,
    HandoffStatus,
)
from starboard_server.services.messaging.message_processor import MessageProcessor
from starboard_server.services.messaging.routing_engine import (
    RoutingEngine,
)


# Mock schemas for testing (named without Test prefix to avoid pytest collection)
class MockInputSchema(BaseModel):
    """Mock input schema for testing."""

    query: str


class MockOutputSchema(BaseModel):
    """Mock output schema for testing."""

    results: list[str]


class TestMessageProcessorRouting:
    """Tests for message processor routing integration."""

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

        return registry

    @pytest.fixture
    def routing_engine(self, registry):
        """Create routing engine."""
        return RoutingEngine(registry=registry)

    @pytest.fixture
    def handoff_manager(self):
        """Create handoff manager with mock repository."""
        repo = Mock()
        repo.save_handoff_model = AsyncMock()
        repo.update_handoff_status = AsyncMock()
        repo.get_handoffs_for_conversation = AsyncMock(return_value=[])
        return HandoffManager(repository=repo)

    @pytest.fixture
    def processor(self, routing_engine, handoff_manager):
        """Create message processor with routing support."""
        return MessageProcessor(
            routing_engine=routing_engine,
            handoff_manager=handoff_manager,
        )

    @pytest.mark.asyncio
    async def test_route_option_triggers_routing(self, processor):
        """Route option triggers routing workflow."""
        option = NextStepOption(
            id="route_to_perf",
            number=1,
            title="Identify slowest queries",
            description=None,
            action_type=ActionType.ROUTE,
            target_agent="performance_analyzer",
            tool_name=None,
            parameters={"warehouse_id": "prod_dw"},
        )

        result = await processor.process_message(
            user_input="1",
            available_options=(option,),
            conversation_history=None,
            previous_agent_response_content=None,
            conversation_id="conv_123",
            current_agent="query_optimizer",
        )

        # Check routing was detected
        assert result.processing_type == "routing"
        assert result.routing_decision is not None
        assert result.routing_decision.should_route is True
        assert result.routing_decision.target_agent_id == "performance_analyzer"

    @pytest.mark.asyncio
    async def test_handoff_initiated_on_routing(self, processor, handoff_manager):
        """Handoff is initiated when routing is needed."""
        option = NextStepOption(
            id="route_to_perf",
            number=1,
            title="Identify slowest queries",
            description=None,
            action_type=ActionType.ROUTE,
            target_agent="performance_analyzer",
            tool_name=None,
            parameters={"warehouse_id": "prod_dw"},
        )

        result = await processor.process_message(
            user_input="1",
            available_options=(option,),
            conversation_history=None,
            previous_agent_response_content=None,
            conversation_id="conv_123",
            current_agent="query_optimizer",
        )

        # Check handoff was initiated
        assert result.handoff_id is not None
        handoff_manager.repository.save_handoff_model.assert_called_once()

    @pytest.mark.asyncio
    async def test_tool_call_does_not_trigger_routing(self, processor):
        """Tool call options don't trigger routing."""
        option = NextStepOption(
            id="optimize",
            number=1,
            title="Optimize query",
            description=None,
            action_type=ActionType.TOOL_CALL,
            target_agent=None,
            tool_name="generate_optimized_query",
            parameters={"query_id": "123"},
        )

        result = await processor.process_message(
            user_input="1",
            available_options=(option,),
            conversation_history=None,
            previous_agent_response_content=None,
            conversation_id="conv_123",
            current_agent="query_optimizer",
        )

        # Should process as option selection, not routing
        assert result.processing_type == "option_selected"
        assert result.routing_decision is None
        assert result.handoff_id is None

    @pytest.mark.asyncio
    async def test_context_preserved_in_handoff(self, processor):
        """Context is preserved when handoff is initiated."""
        option = NextStepOption(
            id="route_to_perf",
            number=1,
            title="Identify slowest queries",
            description=None,
            action_type=ActionType.ROUTE,
            target_agent="performance_analyzer",
            tool_name=None,
            parameters={"warehouse_id": "prod_dw"},
        )

        result = await processor.process_message(
            user_input="1",
            available_options=(option,),
            conversation_history=None,
            previous_agent_response_content="Previous analysis of queries",
            conversation_id="conv_123",
            current_agent="query_optimizer",
        )

        # Check handoff context includes conversation info
        assert result.routing_decision is not None
        context = result.routing_decision.handoff_context
        assert context["source_agent"] == "query_optimizer"
        assert context["parameters"]["warehouse_id"] == "prod_dw"

    @pytest.mark.asyncio
    async def test_circular_routing_prevented(self, processor, handoff_manager):
        """Circular routing is prevented after max handoffs."""
        # Mock 3 existing handoffs (at limit)
        mock_handoffs = [
            AgentHandoff(
                handoff_id=uuid4(),
                conversation_id="conv_123",
                source_agent_id=f"agent{i}",
                target_agent_id=f"agent{i + 1}",
                capability_id=None,
                status=HandoffStatus.COMPLETED,
                handoff_context={},
                initiated_at=Mock(),
                completed_at=Mock(),
                failure_reason=None,
            )
            for i in range(3)
        ]
        handoff_manager.repository.get_handoffs_for_conversation.return_value = (
            mock_handoffs
        )

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

        result = await processor.process_message(
            user_input="1",
            available_options=(option,),
            conversation_history=None,
            previous_agent_response_content=None,
            conversation_id="conv_123",
            current_agent="query_optimizer",
        )

        # Should reject routing
        assert result.processing_type == "routing_rejected"
        assert result.routing_decision is not None
        assert result.routing_decision.should_route is False
        assert (
            "circular" in result.routing_decision.reasoning.lower()
            or "max" in result.routing_decision.reasoning.lower()
        )

    @pytest.mark.asyncio
    async def test_routing_failure_handled_gracefully(self, processor):
        """Routing to nonexistent agent is handled gracefully."""
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

        result = await processor.process_message(
            user_input="1",
            available_options=(option,),
            conversation_history=None,
            previous_agent_response_content=None,
            conversation_id="conv_123",
            current_agent="query_optimizer",
        )

        # Should gracefully handle missing agent
        assert result.processing_type == "routing_rejected"
        assert result.routing_decision is not None
        assert result.routing_decision.should_route is False
        assert "not found" in result.routing_decision.reasoning.lower()

    @pytest.mark.asyncio
    async def test_no_options_uses_intent_classification(
        self, routing_engine, handoff_manager
    ):
        """When no options available, falls back to intent classification."""
        # Create processor with intent classification enabled
        processor = MessageProcessor(
            classify_intent=True,
            routing_engine=routing_engine,
            handoff_manager=handoff_manager,
        )

        result = await processor.process_message(
            user_input="Tell me more about performance",
            available_options=None,
            conversation_history=None,
            previous_agent_response_content=None,
            conversation_id="conv_123",
            current_agent="query_optimizer",
        )

        # Should use intent classification (Phase 2 behavior)
        assert result.processing_type == "intent_classified"
        assert result.intent_classification is not None
        assert result.routing_decision is None

    @pytest.mark.asyncio
    async def test_backward_compatibility_with_phase2(self, processor):
        """Processor maintains backward compatibility with Phase 2."""
        # Test with non-route option (Phase 1 behavior)
        option = NextStepOption(
            id="continue",
            number=1,
            title="Continue analysis",
            description=None,
            action_type=ActionType.CONTINUE,
            target_agent=None,
            tool_name=None,
            parameters={},
        )

        result = await processor.process_message(
            user_input="1",
            available_options=(option,),
            conversation_history=None,
            previous_agent_response_content=None,
            conversation_id="conv_123",
            current_agent="query_optimizer",
        )

        # Should process as option selection
        assert result.processing_type == "option_selected"
        assert result.selected_option is not None
        assert result.routing_decision is None

    @pytest.mark.asyncio
    async def test_handoff_id_returned_on_routing(self, processor):
        """Handoff ID is returned when routing is initiated."""
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

        result = await processor.process_message(
            user_input="1",
            available_options=(option,),
            conversation_history=None,
            previous_agent_response_content=None,
            conversation_id="conv_123",
            current_agent="query_optimizer",
        )

        # Should include handoff ID for tracking
        assert result.handoff_id is not None
        assert isinstance(result.handoff_id, type(uuid4()))

    @pytest.mark.asyncio
    async def test_routing_context_includes_conversation_summary(self, processor):
        """Routing context includes conversation summary."""
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

        previous_content = "User asked about query performance in warehouse"

        result = await processor.process_message(
            user_input="1",
            available_options=(option,),
            conversation_history=None,
            previous_agent_response_content=previous_content,
            conversation_id="conv_123",
            current_agent="query_optimizer",
        )

        # Should include previous content in handoff context
        assert result.routing_decision is not None
        assert previous_content in result.routing_decision.handoff_context.get(
            "conversation_summary", ""
        )

    @pytest.mark.asyncio
    async def test_processor_without_routing_engine(self):
        """Processor works without routing engine (backward compat)."""
        # Create processor without routing support
        processor = MessageProcessor()

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

        result = await processor.process_message(
            user_input="1",
            available_options=(option,),
            conversation_history=None,
            previous_agent_response_content=None,
            conversation_id="conv_123",
            current_agent="query_optimizer",
        )

        # Should process as option selection (no routing)
        assert result.processing_type == "option_selected"
        assert result.routing_decision is None
        assert result.handoff_id is None

    @pytest.mark.asyncio
    async def test_routing_preserves_capability_id(self, processor):
        """Routing preserves capability ID from routing decision."""
        option = NextStepOption(
            id="route_to_perf",
            number=1,
            title="Find the slowest queries",  # Should match capability keywords
            description=None,
            action_type=ActionType.ROUTE,
            target_agent="performance_analyzer",
            tool_name=None,
            parameters={},
        )

        result = await processor.process_message(
            user_input="1",
            available_options=(option,),
            conversation_history=None,
            previous_agent_response_content=None,
            conversation_id="conv_123",
            current_agent="query_optimizer",
        )

        # Should infer capability from keywords
        assert result.routing_decision is not None
        assert result.routing_decision.capability_id == "identify_slow_queries"
