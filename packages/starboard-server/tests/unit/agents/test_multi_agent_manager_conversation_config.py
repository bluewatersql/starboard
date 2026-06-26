# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Tests for MultiAgentConversationManager with conversation config.

Tests that conversation config is correctly stored in SharedAgentContext
and passed to AgentFactory when creating agents.
"""

from unittest.mock import AsyncMock, Mock

import pytest
from starboard_server.agents.agent_factory import AgentFactory
from starboard_server.agents.conversation.multi_agent_manager import (
    MultiAgentConversationManager,
)
from starboard_server.agents.routing.intent_router import IntentRouter
from starboard_server.agents.state.agent_state import WorkingMemory
from starboard_server.agents.state.shared_context import SharedAgentContext
from starboard_server.api.models import ConversationConfig


@pytest.fixture
def mock_agent_factory():
    """Mock agent factory."""
    from starboard_server.agents.config.agent_config import AgentConfig

    factory = Mock(spec=AgentFactory)
    factory.base_config = AgentConfig(
        model="databricks-claude-sonnet-4-5",
        temperature=0.4,
        max_tokens=75000,
    )

    mock_agent = Mock()

    # Create async generator for run_stream
    async def async_generator():
        return
        yield  # Make this an async generator

    mock_agent.run_stream = Mock(return_value=async_generator())
    factory.get_agent.return_value = mock_agent
    return factory


@pytest.fixture
def mock_intent_router():
    """Mock intent router."""
    from starboard_server.agents.routing.routing_models import RouteDecision

    router = Mock(spec=IntentRouter)

    # Default: route to query domain
    router.classify_intent = AsyncMock(
        return_value=RouteDecision(
            domain="query",
            confidence=0.9,
            extracted_ids={"statement_id": "abc123"},
            context={},
            clarification_needed=False,
            reasoning="User wants to optimize a query",
        )
    )

    return router


@pytest.fixture
def mock_state_manager():
    """Mock conversation state manager."""
    manager = Mock()
    manager.load_context = AsyncMock(return_value=None)
    manager.save_context = AsyncMock()
    return manager


@pytest.fixture
def multi_agent_manager(mock_agent_factory, mock_intent_router, mock_state_manager):
    """Create multi-agent manager for testing."""
    return MultiAgentConversationManager(
        agent_factory=mock_agent_factory,
        intent_router=mock_intent_router,
        state_manager=mock_state_manager,
    )


class TestConversationConfigStorage:
    """Tests for storing conversation config in SharedAgentContext."""

    @pytest.mark.asyncio
    async def test_create_conversation_stores_config_in_metadata(
        self, multi_agent_manager, mock_state_manager
    ):
        """Test that conversation config is stored in SharedAgentContext.metadata."""
        config = ConversationConfig(
            model="gpt-5",
            temperature=0.7,
            max_tokens=50000,
            use_max_model_tokens=True,
        )

        await multi_agent_manager.create_conversation(
            user_id="user_123",
            context={"workspace_id": "ws_abc"},
            config=config,
        )

        # Check that save_context was called
        assert mock_state_manager.save_context.called

        # Get the SharedAgentContext that was saved
        saved_context = mock_state_manager.save_context.call_args[0][0]

        # Verify config is in metadata
        assert "conversation_config" in saved_context.metadata

        # Verify config values
        stored_config = saved_context.metadata["conversation_config"]
        assert stored_config["model"] == "gpt-5"
        assert stored_config["temperature"] == 0.7
        assert stored_config["max_tokens"] == 50000
        assert stored_config["use_max_model_tokens"] is True

    @pytest.mark.asyncio
    async def test_create_conversation_without_config_stores_default(
        self, multi_agent_manager, mock_state_manager
    ):
        """Test that default config is stored when no config provided."""
        await multi_agent_manager.create_conversation(
            user_id="user_123",
            config=None,  # No config provided
        )

        # Get the SharedAgentContext that was saved
        saved_context = mock_state_manager.save_context.call_args[0][0]

        # Verify default config is in metadata
        assert "conversation_config" in saved_context.metadata
        stored_config = saved_context.metadata["conversation_config"]

        # Should have default values
        assert "model" in stored_config
        assert "temperature" in stored_config
        assert stored_config["budget_enforced"] is False  # New default

    @pytest.mark.asyncio
    async def test_create_conversation_preserves_other_metadata(
        self, multi_agent_manager, mock_state_manager
    ):
        """Test that conversation config doesn't overwrite other metadata."""
        config = ConversationConfig(model="gpt-5")
        context = {"workspace_id": "ws_abc", "job_id": "12345"}

        await multi_agent_manager.create_conversation(
            user_id="user_123",
            context=context,
            config=config,
        )

        # Get the SharedAgentContext that was saved
        saved_context = mock_state_manager.save_context.call_args[0][0]

        # Verify both config and context are in metadata
        assert "conversation_config" in saved_context.metadata
        assert "workspace_id" in saved_context.metadata
        assert "job_id" in saved_context.metadata

        # Verify values
        assert saved_context.metadata["workspace_id"] == "ws_abc"
        assert saved_context.metadata["job_id"] == "12345"


class TestConversationConfigPassing:
    """Tests for passing conversation config to AgentFactory."""

    @pytest.mark.asyncio
    async def test_handle_message_passes_config_to_agent_factory(
        self, multi_agent_manager, mock_agent_factory, mock_state_manager
    ):
        """Test that conversation config is passed to agent_factory.get_agent()."""
        # Create conversation with config
        config = ConversationConfig(
            model="gpt-5",
            temperature=0.7,
            use_max_model_tokens=True,
        )

        conv_response = await multi_agent_manager.create_conversation(
            user_id="user_123",
            config=config,
        )
        conversation_id = conv_response.conversation_id

        # Mock load_context to return the saved context
        saved_context = mock_state_manager.save_context.call_args[0][0]
        mock_state_manager.load_context.return_value = saved_context

        # Process message
        events = []
        async for event in multi_agent_manager.handle_message_stream(
            conversation_id=conversation_id,
            user_message="Optimize query abc123",
        ):
            events.append(event)

        # Verify get_agent was called with conversation_config
        assert mock_agent_factory.get_agent.called
        call_args = mock_agent_factory.get_agent.call_args

        # Check that conversation_config was passed
        assert "conversation_config" in call_args.kwargs
        conversation_config = call_args.kwargs["conversation_config"]

        # Verify config values
        assert conversation_config["model"] == "gpt-5"
        assert conversation_config["temperature"] == 0.7
        assert conversation_config["use_max_model_tokens"] is True

    @pytest.mark.asyncio
    async def test_handle_message_without_stored_config(
        self, multi_agent_manager, mock_agent_factory, mock_state_manager
    ):
        """Test that get_agent handles missing config gracefully."""
        # Create context without conversation_config
        context_without_config = SharedAgentContext(
            conversation_id="conv_123",
            user_id="user_123",
            conversation_history=[],
            working_memory=WorkingMemory(),
            agent_transitions=[],
            metadata={},  # No conversation_config
        )

        mock_state_manager.load_context.return_value = context_without_config

        # Process message
        events = []
        async for event in multi_agent_manager.handle_message_stream(
            conversation_id="conv_123",
            user_message="Optimize query abc123",
        ):
            events.append(event)

        # Verify get_agent was called
        assert mock_agent_factory.get_agent.called
        call_args = mock_agent_factory.get_agent.call_args

        # conversation_config should be None or not present
        conversation_config = call_args.kwargs.get("conversation_config")
        assert conversation_config is None

    @pytest.mark.asyncio
    async def test_different_conversations_different_configs(
        self, multi_agent_manager, mock_agent_factory, mock_state_manager
    ):
        """Test that different conversations can have different configs."""
        # Create two conversations with different configs
        config1 = ConversationConfig(model="gpt-4o", temperature=0.3)
        config2 = ConversationConfig(model="gpt-5", temperature=0.9)

        await multi_agent_manager.create_conversation(
            user_id="user_123",
            config=config1,
        )

        await multi_agent_manager.create_conversation(
            user_id="user_123",
            config=config2,
        )

        # Get saved contexts
        call1 = mock_state_manager.save_context.call_args_list[0][0][0]
        call2 = mock_state_manager.save_context.call_args_list[1][0][0]

        # Verify different configs
        config1_stored = call1.metadata["conversation_config"]
        config2_stored = call2.metadata["conversation_config"]

        assert config1_stored["model"] == "gpt-4o"
        assert config1_stored["temperature"] == 0.3

        assert config2_stored["model"] == "gpt-5"
        assert config2_stored["temperature"] == 0.9


class TestConfigPersistence:
    """Tests for config persistence across message handling."""

    @pytest.mark.asyncio
    async def test_config_persists_across_messages(
        self, multi_agent_manager, mock_agent_factory, mock_state_manager
    ):
        """Test that conversation config persists across multiple messages."""
        # Create conversation with config
        config = ConversationConfig(model="gpt-5", use_max_model_tokens=True)

        conv_response = await multi_agent_manager.create_conversation(
            user_id="user_123",
            config=config,
        )
        conversation_id = conv_response.conversation_id

        # Get saved context
        saved_context = mock_state_manager.save_context.call_args[0][0]

        # Mock load_context to return the saved context
        mock_state_manager.load_context.return_value = saved_context

        # Process first message
        async for _event in multi_agent_manager.handle_message_stream(
            conversation_id=conversation_id,
            user_message="First message",
        ):
            pass

        # Get conversation_config from first call
        first_call_config = mock_agent_factory.get_agent.call_args_list[0].kwargs.get(
            "conversation_config"
        )

        # Process second message
        async for _event in multi_agent_manager.handle_message_stream(
            conversation_id=conversation_id,
            user_message="Second message",
        ):
            pass

        # Get conversation_config from second call
        second_call_config = mock_agent_factory.get_agent.call_args_list[1].kwargs.get(
            "conversation_config"
        )

        # Both should have same config
        assert first_call_config["model"] == "gpt-5"
        assert second_call_config["model"] == "gpt-5"
        assert first_call_config["use_max_model_tokens"] is True
        assert second_call_config["use_max_model_tokens"] is True


class TestLegacyMode:
    """Tests for legacy mode (routing disabled)."""

    @pytest.mark.asyncio
    async def test_legacy_mode_uses_config(
        self, mock_agent_factory, mock_intent_router, mock_state_manager
    ):
        """Test that legacy mode still uses conversation config."""
        # Create manager with routing disabled
        manager = MultiAgentConversationManager(
            agent_factory=mock_agent_factory,
            intent_router=mock_intent_router,
            state_manager=mock_state_manager,
        )

        # Create conversation with config
        config = ConversationConfig(model="gpt-5")
        await manager.create_conversation(
            user_id="user_123",
            config=config,
        )

        # Verify config was stored
        saved_context = mock_state_manager.save_context.call_args[0][0]
        assert "conversation_config" in saved_context.metadata
        assert saved_context.metadata["conversation_config"]["model"] == "gpt-5"


class TestEdgeCases:
    """Tests for edge cases."""

    @pytest.mark.asyncio
    async def test_malformed_config_in_metadata(
        self, multi_agent_manager, mock_agent_factory, mock_state_manager
    ):
        """Test handling of malformed config in metadata."""
        # Create context with malformed config
        context_with_bad_config = SharedAgentContext(
            conversation_id="conv_123",
            user_id="user_123",
            conversation_history=[],
            working_memory=WorkingMemory(),
            agent_transitions=[],
            metadata={"conversation_config": "not_a_dict"},  # Malformed
        )

        mock_state_manager.load_context.return_value = context_with_bad_config

        # Process message - should not crash
        async for _event in multi_agent_manager.handle_message_stream(
            conversation_id="conv_123",
            user_message="Test message",
        ):
            pass

        # Should still call get_agent (even if config is malformed)
        assert mock_agent_factory.get_agent.called

    @pytest.mark.asyncio
    async def test_partial_config_in_metadata(
        self, multi_agent_manager, mock_agent_factory, mock_state_manager
    ):
        """Test handling of partial config in metadata."""
        # Create context with partial config
        context_with_partial_config = SharedAgentContext(
            conversation_id="conv_123",
            user_id="user_123",
            conversation_history=[],
            working_memory=WorkingMemory(),
            agent_transitions=[],
            metadata={
                "conversation_config": {
                    "model": "gpt-5",
                    # Missing other fields
                }
            },
        )

        mock_state_manager.load_context.return_value = context_with_partial_config

        # Process message
        async for _event in multi_agent_manager.handle_message_stream(
            conversation_id="conv_123",
            user_message="Test message",
        ):
            pass

        # Should pass partial config to get_agent
        call_args = mock_agent_factory.get_agent.call_args
        conversation_config = call_args.kwargs.get("conversation_config")

        assert conversation_config is not None
        assert conversation_config["model"] == "gpt-5"


class TestIntegrationWithRouting:
    """Tests for integration with intent routing."""

    @pytest.mark.asyncio
    async def test_config_used_for_routed_agent(
        self,
        multi_agent_manager,
        mock_agent_factory,
        mock_intent_router,
        mock_state_manager,
    ):
        """Test that config is used when routing to specialist agent."""
        from starboard_server.agents.routing.routing_models import RouteDecision

        # Configure router to route to job domain
        mock_intent_router.classify_intent.return_value = RouteDecision(
            domain="job",
            confidence=0.95,
            extracted_ids={"job_id": "12345"},
            context={},
            clarification_needed=False,
            reasoning="User wants to optimize a job",
        )

        # Create conversation with config
        config = ConversationConfig(model="gpt-5", temperature=0.8)
        conv_response = await multi_agent_manager.create_conversation(
            user_id="user_123",
            config=config,
        )

        # Get saved context and set it for loading
        saved_context = mock_state_manager.save_context.call_args[0][0]
        mock_state_manager.load_context.return_value = saved_context

        # Process message
        async for _event in multi_agent_manager.handle_message_stream(
            conversation_id=conv_response.conversation_id,
            user_message="Optimize job 12345",
        ):
            pass

        # Verify get_agent was called for job domain with config
        call_args = mock_agent_factory.get_agent.call_args
        assert call_args.args[0] == "job"  # Domain

        conversation_config = call_args.kwargs.get("conversation_config")
        assert conversation_config is not None
        assert conversation_config["model"] == "gpt-5"
        assert conversation_config["temperature"] == 0.8
