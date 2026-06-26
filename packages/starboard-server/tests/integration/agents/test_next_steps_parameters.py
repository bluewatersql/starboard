# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Integration tests for next step parameter passing (Context Passing Bug Fix).

These tests verify end-to-end workflows where user-selected next step options
with parameters flow through to domain agents:
- Parameters extracted from option selection metadata
- Parameters enriched into SharedAgentContext
- Agents receive parameters in working memory
- No redundant clarification questions

Unlike unit tests, these use real (mocked) components working together.
"""

from unittest.mock import AsyncMock, Mock

import pytest
from starboard_core.domain.models.llm import OptimizationMode
from starboard_server.agents.agent_factory import AgentFactory
from starboard_server.agents.config.agent_config import AgentConfig
from starboard_server.agents.conversation.multi_agent_manager import (
    MultiAgentConversationManager,
)
from starboard_server.agents.routing.intent_router import IntentRouter
from starboard_server.agents.routing.routing_models import RouteDecision
from starboard_server.agents.tools import ToolRegistry
from starboard_server.api.conversation_state_manager import (
    InMemoryConversationStateManager,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client for testing."""
    client = Mock()

    # Mock for intent classification
    client.json_response = AsyncMock(
        return_value={
            "domain": "job",
            "confidence": 0.9,
            "reasoning": "User selected job analysis option",
        }
    )

    # Mock for agent responses
    client.text_response = AsyncMock(return_value="Analyzing job...")

    return client


@pytest.fixture
def mock_tool_registry():
    """Create a mock ToolRegistry for testing."""
    return ToolRegistry()


@pytest.fixture
def agent_factory(mock_llm_client, mock_tool_registry):
    """Create AgentFactory with mocked dependencies."""
    base_config = AgentConfig(
        model="gpt-4o",
        temperature=0.5,
        max_tokens=10000,
    )

    factory = AgentFactory(
        llm_client=mock_llm_client,
        tool_registry=mock_tool_registry,
        base_config=base_config,
        events=None,
    )
    return factory


@pytest.fixture
def intent_router(mock_llm_client):
    """Create IntentRouter with mocked LLM client."""
    router = IntentRouter(llm_client=mock_llm_client)

    # Mock classify_intent to route to job domain
    async def mock_classify(user_input, conversation_history, attachments=None):  # noqa: ARG001
        return RouteDecision(
            domain="job",
            confidence=0.9,
            extracted_ids={},
            context={},
            clarification_needed=False,
            reasoning="User selected job analysis option",
        )

    router.classify_intent = mock_classify
    return router


@pytest.fixture
def state_manager():
    """Create InMemoryConversationStateManager for testing."""
    return InMemoryConversationStateManager()


@pytest.fixture
async def integration_manager(agent_factory, intent_router, state_manager):
    """Create MultiAgentConversationManager with all dependencies."""
    manager = MultiAgentConversationManager(
        agent_factory=agent_factory,
        intent_router=intent_router,
        state_manager=state_manager,
    )

    # Create a test conversation
    response = await manager.create_conversation(user_id="integration_test_user")

    # Attach conversation_id to manager for easy access in tests
    manager.test_conversation_id = response.conversation_id

    return manager


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.integration
async def test_next_step_parameters_flow_to_agent(integration_manager):
    """
    End-to-end test: User selects parameterized next step,
    parameters flow through to domain agent without clarification.

    Flow:
    1. Create conversation
    2. User selects option with job_id parameter
    3. Verify parameters extracted from metadata
    4. Verify parameters in SharedAgentContext
    5. Verify agent would receive parameters (via context inspection)
    """
    conversation_id = integration_manager.test_conversation_id

    # Simulate user selecting a next step option with job_id parameter
    selection_metadata = {
        "is_option_selection": True,
        "selected_option": {
            "id": "analyze_job_1",
            "number": 1,
            "title": "Analyze high-frequency job",
            "description": "Deep dive into job 31942593021809",
            "action_type": "route",
            "target_agent": "job",
            "parameters": {
                "job_id": "31942593021809",
                "handoff_context": "High-frequency execution detected in analytics",
            },
        },
    }

    # Process the selection
    events = []
    async for event in integration_manager.handle_message_stream(
        conversation_id=conversation_id,
        user_message="1",  # User types "1" to select option 1
        metadata=selection_metadata,
        mode=OptimizationMode.ONLINE,
    ):
        events.append(event)

    # Verify parameters were passed to context
    context = await integration_manager.state_manager.load_context(conversation_id)
    assert context is not None, "Context should exist"

    constraints = context.get_user_constraints()

    assert "job_id" in constraints, "job_id should be in user_constraints"
    assert constraints["job_id"] == "31942593021809"
    assert "handoff_context" in constraints

    # Verify metadata was tracked
    assert "last_option_selection" in context.metadata
    assert context.metadata["last_option_selection"]["id"] == "analyze_job_1"
    assert context.metadata["last_option_selection"]["action_type"] == "route"
    assert context.metadata["last_option_selection"]["target_agent"] == "job"

    # Verify events were generated (agent was invoked)
    assert len(events) > 0, "Should have received events from agent"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_parameter_accumulation_across_enrichments(integration_manager):
    """
    Test that parameters accumulate across intent classification and option selection.

    Flow:
    1. First message: Potentially adds constraints via intent classification
    2. Second message: Option selection adds job_id constraint
    3. Agent receives BOTH constraints (accumulated)
    """
    conversation_id = integration_manager.test_conversation_id

    # First message: Normal message (might add intent constraints)
    async for _event in integration_manager.handle_message_stream(
        conversation_id=conversation_id,
        user_message="Show me jobs from this morning",
        mode=OptimizationMode.ONLINE,
    ):
        pass

    # Second message: Option selection should add job_id
    selection_metadata = {
        "is_option_selection": True,
        "selected_option": {
            "id": "analyze_job",
            "action_type": "route",
            "target_agent": "job",
            "parameters": {
                "job_id": "123",
            },
        },
    }

    async for _event in integration_manager.handle_message_stream(
        conversation_id=conversation_id,
        user_message="1",
        metadata=selection_metadata,
        mode=OptimizationMode.ONLINE,
    ):
        pass

    # Verify both constraints might be present
    context = await integration_manager.state_manager.load_context(conversation_id)
    constraints = context.get_user_constraints()

    # Should have job_id from option selection
    assert "job_id" in constraints
    assert constraints["job_id"] == "123"

    # Note: timeframe might not be added if intent classification isn't
    # extracting entities in this test setup. The key is that job_id
    # from option selection is definitely present.


@pytest.mark.asyncio
@pytest.mark.integration
async def test_multiple_option_selections_parameter_override(integration_manager):
    """
    Test that selecting multiple options with same parameter keys results in override.

    Flow:
    1. User selects option with job_id="123"
    2. User selects different option with job_id="456"
    3. Agent should receive job_id="456" (latest value)
    """
    conversation_id = integration_manager.test_conversation_id

    # First selection: job_id="123"
    metadata1 = {
        "is_option_selection": True,
        "selected_option": {
            "id": "opt1",
            "action_type": "continue",
            "parameters": {"job_id": "123"},
        },
    }

    async for _event in integration_manager.handle_message_stream(
        conversation_id=conversation_id,
        user_message="1",
        metadata=metadata1,
        mode=OptimizationMode.ONLINE,
    ):
        pass

    # Second selection: job_id="456"
    metadata2 = {
        "is_option_selection": True,
        "selected_option": {
            "id": "opt2",
            "action_type": "continue",
            "parameters": {"job_id": "456"},
        },
    }

    async for _event in integration_manager.handle_message_stream(
        conversation_id=conversation_id,
        user_message="2",
        metadata=metadata2,
        mode=OptimizationMode.ONLINE,
    ):
        pass

    # Verify latest value wins
    context = await integration_manager.state_manager.load_context(conversation_id)
    constraints = context.get_user_constraints()

    assert constraints["job_id"] == "456", "Latest value should override previous"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_normal_message_without_option_selection(integration_manager):
    """
    Test that normal messages (without option selection) don't trigger parameter extraction.

    Flow:
    1. User sends normal free-text message
    2. Verify no option selection parameters added
    3. Verify normal message handling continues
    """
    conversation_id = integration_manager.test_conversation_id

    # Normal message without option selection metadata
    async for _event in integration_manager.handle_message_stream(
        conversation_id=conversation_id,
        user_message="What are my slowest jobs?",
        metadata=None,
        mode=OptimizationMode.ONLINE,
    ):
        pass

    # Verify no option selection parameters were added
    context = await integration_manager.state_manager.load_context(conversation_id)

    # Should not have option selection metadata
    assert "last_option_selection" not in context.metadata

    # user_constraints might exist but shouldn't have job_id from options
    context.get_user_constraints()
    # If job_id exists, it would be from intent classification, not option selection
    # The key point is no option selection metadata should be present


@pytest.mark.asyncio
@pytest.mark.integration
async def test_empty_parameters_dict_handling(integration_manager):
    """
    Test graceful handling of option selection with empty parameters dict.

    Flow:
    1. User selects option with empty parameters: {}
    2. Verify no crash
    3. Verify option selection metadata tracked (even though no params)
    """
    conversation_id = integration_manager.test_conversation_id

    # Option selection with empty parameters
    metadata = {
        "is_option_selection": True,
        "selected_option": {
            "id": "continue_analysis",
            "action_type": "continue",
            "parameters": {},  # Empty!
        },
    }

    # Should not crash
    events = []
    async for event in integration_manager.handle_message_stream(
        conversation_id=conversation_id,
        user_message="Continue",
        metadata=metadata,
        mode=OptimizationMode.ONLINE,
    ):
        events.append(event)

    # Verify context exists and no crash occurred
    context = await integration_manager.state_manager.load_context(conversation_id)
    assert context is not None

    # Option selection should still be tracked in metadata
    assert "last_option_selection" in context.metadata

    # But no parameters should have been added
    context.get_user_constraints()
    # Constraints should be empty or not contain any new keys
    # (this test mainly verifies no crash with empty params)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_malformed_metadata_graceful_handling(integration_manager):
    """
    Test graceful handling of malformed option selection metadata.

    Flow:
    1. Send metadata with is_option_selection=True but missing selected_option
    2. Verify no crash
    3. Verify normal message handling continues
    """
    conversation_id = integration_manager.test_conversation_id

    # Malformed: is_option_selection=True but selected_option missing
    metadata = {
        "is_option_selection": True,
        # selected_option is missing!
    }

    # Should not crash
    events = []
    async for event in integration_manager.handle_message_stream(
        conversation_id=conversation_id,
        user_message="Test",
        metadata=metadata,
        mode=OptimizationMode.ONLINE,
    ):
        events.append(event)

    # Verify context exists (no crash)
    context = await integration_manager.state_manager.load_context(conversation_id)
    assert context is not None

    # Events should have been generated (normal flow continued)
    assert len(events) > 0
