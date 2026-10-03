# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Tests for AgentFactory with per-conversation configuration.

Tests that conversation-specific config (model, temperature, max_tokens,
use_max_model_tokens) is correctly applied when creating agents.
"""

from unittest.mock import Mock

import pytest
from starboard.adapters.llm.base import BaseLLMClient
from starboard.agents.agent_factory import AgentFactory
from starboard.agents.config.agent_config import AgentConfig
from starboard.agents.tools import ToolRegistry


@pytest.fixture
def mock_llm_client():
    """Mock LLM client for testing."""
    return Mock(spec=BaseLLMClient)


@pytest.fixture
def mock_tool_registry():
    """Mock tool registry with some tools."""
    registry = Mock(spec=ToolRegistry)
    registry.list_tools.return_value = ["tool1", "tool2", "tool3"]
    registry._tools = {}

    # Mock filter_by_domain to return a filtered registry
    filtered_registry = Mock(spec=ToolRegistry)
    filtered_registry.list_tools.return_value = ["tool1", "tool2"]
    # Add _tools attribute for DomainAgent's complete check
    filtered_registry._tools = {}
    filtered_registry.register = Mock()
    registry.filter_by_domain.return_value = filtered_registry

    return registry


@pytest.fixture
def base_config():
    """Base agent config for testing."""
    return AgentConfig(
        model="gpt-4o",
        temperature=0.5,
        max_tokens=75000,
        domain_model_overrides={"query": "claude-3-opus"},
        domain_temperature_overrides={"query": 0.3},
    )


@pytest.fixture
def agent_factory(mock_llm_client, mock_tool_registry, base_config):
    """Create agent factory for testing."""
    return AgentFactory(
        llm_client=mock_llm_client,
        tool_registry=mock_tool_registry,
        base_config=base_config,
        events=None,
    )


class TestConversationConfigOverrides:
    """Tests for conversation config overriding base/domain config."""

    def test_conversation_config_overrides_model(self, agent_factory):
        """Test that conversation config overrides base model."""
        conversation_config = {"model": "gpt-5"}

        agent = agent_factory.get_agent("job", conversation_config=conversation_config)

        assert agent.config.model == "gpt-5"

    def test_conversation_config_overrides_temperature(self, agent_factory):
        """Test that conversation config overrides base temperature."""
        conversation_config = {"temperature": 0.9}

        agent = agent_factory.get_agent("job", conversation_config=conversation_config)

        assert agent.config.temperature == 0.9

    def test_conversation_config_overrides_max_tokens(self, agent_factory):
        """Test that conversation config overrides base max_tokens."""
        conversation_config = {"max_tokens": 50000}

        agent = agent_factory.get_agent("job", conversation_config=conversation_config)

        assert agent.config.max_tokens == 50000

    def test_conversation_config_overrides_domain_model(self, agent_factory):
        """Test that conversation config overrides domain-specific model."""
        # Domain override: query → claude-3-opus
        # Conversation override: query → gpt-5
        conversation_config = {"model": "gpt-5"}

        agent = agent_factory.get_agent(
            "query", conversation_config=conversation_config
        )

        # Conversation should win
        assert agent.config.model == "gpt-5"

    def test_conversation_config_overrides_domain_temperature(self, agent_factory):
        """Test that conversation config overrides domain-specific temperature."""
        # Domain override: query → 0.3
        # Conversation override: query → 0.8
        conversation_config = {"temperature": 0.8}

        agent = agent_factory.get_agent(
            "query", conversation_config=conversation_config
        )

        # Conversation should win
        assert agent.config.temperature == 0.8

    def test_partial_conversation_config(self, agent_factory):
        """Test that partial conversation config only overrides specified fields."""
        conversation_config = {"model": "gpt-5"}  # Only override model

        agent = agent_factory.get_agent("job", conversation_config=conversation_config)

        assert agent.config.model == "gpt-5"  # Overridden
        assert agent.config.temperature == 0.5  # Base config
        assert agent.config.max_tokens == 75000  # Base config

    def test_empty_conversation_config(self, agent_factory):
        """Test that empty conversation config uses domain/base config."""
        conversation_config = {}

        agent = agent_factory.get_agent(
            "query", conversation_config=conversation_config
        )

        # Should use domain overrides
        assert agent.config.model == "claude-3-opus"  # Domain override
        assert agent.config.temperature == 0.3  # Domain override
        assert agent.config.max_tokens == 75000  # Base config


class TestUseMaxModelTokens:
    """Tests for use_max_model_tokens flag.

    When use_max_model_tokens is enabled, the agent's token budget should be set
    to the model's context_window (total input + output limit), not max_output_tokens
    (which is only the limit for a single response). This allows multi-step agents
    to use the full model capability for their session budget.
    """

    def test_use_max_model_tokens_gpt4o(self, agent_factory):
        """Test that use_max_model_tokens applies GPT-4o's context window."""
        conversation_config = {
            "model": "gpt-4o",
            "use_max_model_tokens": True,
        }

        agent = agent_factory.get_agent("job", conversation_config=conversation_config)

        # Should use context_window (128K), not max_output_tokens (16K)
        assert agent.config.max_tokens == 128_000

    def test_use_max_model_tokens_gpt5(self, agent_factory):
        """Test that use_max_model_tokens applies GPT-5's context window."""
        conversation_config = {
            "model": "gpt-5",
            "use_max_model_tokens": True,
        }

        agent = agent_factory.get_agent("job", conversation_config=conversation_config)

        # Should use context_window (256K), not max_output_tokens (65K)
        assert agent.config.max_tokens == 256_000

    def test_use_max_model_tokens_overrides_explicit_max_tokens(self, agent_factory):
        """Test that use_max_model_tokens overrides explicit max_tokens."""
        conversation_config = {
            "model": "gpt-4o",
            "max_tokens": 50000,  # Explicit value
            "use_max_model_tokens": True,  # Should override explicit value
        }

        agent = agent_factory.get_agent("job", conversation_config=conversation_config)

        # Should use context_window (128K), not explicit value (50K)
        assert agent.config.max_tokens == 128_000

    def test_use_max_model_tokens_false_uses_explicit(self, agent_factory):
        """Test that use_max_model_tokens=False uses explicit max_tokens."""
        conversation_config = {
            "model": "gpt-4o",
            "max_tokens": 50000,
            "use_max_model_tokens": False,
        }

        agent = agent_factory.get_agent("job", conversation_config=conversation_config)

        assert agent.config.max_tokens == 50000  # Explicit value

    def test_use_max_model_tokens_with_domain_model(self, agent_factory):
        """Test that use_max_model_tokens works with domain model override."""
        # Domain override: query → claude-3-opus
        conversation_config = {
            "use_max_model_tokens": True,
            # No model override - should use domain model
        }

        agent = agent_factory.get_agent(
            "query", conversation_config=conversation_config
        )

        # Should use claude-3-opus (from domain override) and its context window
        assert agent.config.model == "claude-3-opus"
        # Claude Opus context_window is 200K
        assert agent.config.max_tokens == 200_000

    def test_use_max_model_tokens_unknown_model(self, agent_factory):
        """Test that use_max_model_tokens with unknown model uses default."""
        conversation_config = {
            "model": "unknown-model-xyz",
            "use_max_model_tokens": True,
        }

        agent = agent_factory.get_agent("job", conversation_config=conversation_config)

        # Should use default context_window fallback (16_384)
        assert agent.config.max_tokens == 16_384


class TestAgentCaching:
    """Tests for agent caching behavior with conversation config."""

    def test_agent_without_config_is_cached(self, agent_factory):
        """Test that agents without conversation config are cached."""
        agent1 = agent_factory.get_agent("query")
        agent2 = agent_factory.get_agent("query")

        # Should be same instance (cached)
        assert agent1 is agent2

    def test_agent_with_config_is_not_cached(self, agent_factory):
        """Test that agents with conversation config are not cached."""
        conversation_config = {"model": "gpt-5"}

        agent1 = agent_factory.get_agent(
            "query", conversation_config=conversation_config
        )
        agent2 = agent_factory.get_agent(
            "query", conversation_config=conversation_config
        )

        # Should be different instances (not cached)
        assert agent1 is not agent2

    def test_different_domains_cached_separately(self, agent_factory):
        """Test that different domains are cached separately."""
        agent_query = agent_factory.get_agent("query")
        agent_job = agent_factory.get_agent("job")

        # Should be different instances (different domains)
        assert agent_query is not agent_job

        # But reusing same domain returns cached instance
        agent_query2 = agent_factory.get_agent("query")
        assert agent_query is agent_query2

    def test_cached_agent_not_affected_by_later_config(self, agent_factory):
        """Test that cached agent is not affected by later conversation config."""
        # Get cached agent
        cached_agent = agent_factory.get_agent("job")
        assert cached_agent.config.model == "gpt-4o"  # Base model

        # Create agent with conversation config
        conversation_config = {"model": "gpt-5"}
        custom_agent = agent_factory.get_agent(
            "job", conversation_config=conversation_config
        )
        assert custom_agent.config.model == "gpt-5"

        # Cached agent should still have original config
        assert cached_agent.config.model == "gpt-4o"

    def test_cache_cleared(self, agent_factory):
        """Test that clearing cache works."""
        agent1 = agent_factory.get_agent("query")

        # Clear cache
        agent_factory.clear_cache()

        # Next get_agent should create new instance
        agent2 = agent_factory.get_agent("query")
        assert agent1 is not agent2


class TestOverridePrecedence:
    """Tests for config override precedence: Base → Domain → Conversation."""

    def test_base_only(self, agent_factory):
        """Test that base config is used when no overrides."""
        agent = agent_factory.get_agent("job")  # No domain overrides for job

        assert agent.config.model == "gpt-4o"  # Base
        assert agent.config.temperature == 0.5  # Base
        assert agent.config.max_tokens == 75000  # Base

    def test_domain_overrides_base(self, agent_factory):
        """Test that domain config overrides base."""
        agent = agent_factory.get_agent("query")  # Has domain overrides

        assert agent.config.model == "claude-3-opus"  # Domain override
        assert agent.config.temperature == 0.3  # Domain override
        assert agent.config.max_tokens == 75000  # Base (no domain override)

    def test_conversation_overrides_domain(self, agent_factory):
        """Test that conversation config overrides domain."""
        conversation_config = {
            "model": "gpt-5",
            "temperature": 0.9,
        }

        agent = agent_factory.get_agent(
            "query", conversation_config=conversation_config
        )

        assert agent.config.model == "gpt-5"  # Conversation override
        assert agent.config.temperature == 0.9  # Conversation override
        assert agent.config.max_tokens == 75000  # Base (no overrides)

    def test_conversation_overrides_base_when_no_domain(self, agent_factory):
        """Test that conversation config overrides base when no domain override."""
        conversation_config = {
            "model": "gpt-5",
            "temperature": 0.9,
        }

        agent = agent_factory.get_agent(
            "job", conversation_config=conversation_config
        )  # No domain overrides

        assert agent.config.model == "gpt-5"  # Conversation override
        assert agent.config.temperature == 0.9  # Conversation override

    def test_all_three_levels(self, agent_factory):
        """Test all three levels of config: base, domain, conversation."""
        conversation_config = {
            "model": "gpt-5",  # Override domain model
            # Don't override temperature - should use domain temp
        }

        agent = agent_factory.get_agent(
            "query", conversation_config=conversation_config
        )

        assert agent.config.model == "gpt-5"  # Conversation (most specific)
        assert agent.config.temperature == 0.3  # Domain (middle)
        assert agent.config.max_tokens == 75000  # Base (least specific)


class TestMultipleConversations:
    """Tests for multiple conversations with different configs."""

    def test_different_conversations_different_agents(self, agent_factory):
        """Test that different conversations get different agent instances."""
        config1 = {"model": "gpt-4o", "temperature": 0.3}
        config2 = {"model": "gpt-5", "temperature": 0.7}

        agent1 = agent_factory.get_agent("query", conversation_config=config1)
        agent2 = agent_factory.get_agent("query", conversation_config=config2)

        assert agent1 is not agent2
        assert agent1.config.model == "gpt-4o"
        assert agent2.config.model == "gpt-5"

    def test_same_config_different_agents(self, agent_factory):
        """Test that same config creates different agents (not cached)."""
        config = {"model": "gpt-5", "temperature": 0.7}

        agent1 = agent_factory.get_agent("query", conversation_config=config)
        agent2 = agent_factory.get_agent("query", conversation_config=config)

        # Should be different instances (not cached)
        assert agent1 is not agent2

        # But have same config
        assert agent1.config.model == agent2.config.model
        assert agent1.config.temperature == agent2.config.temperature


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_none_conversation_config(self, agent_factory):
        """Test that None conversation config uses default behavior."""
        agent = agent_factory.get_agent("query", conversation_config=None)

        # Should use domain overrides
        assert agent.config.model == "claude-3-opus"
        assert agent.config.temperature == 0.3

    def test_conversation_config_with_none_values(self, agent_factory):
        """Test that None values in conversation config are ignored."""
        conversation_config = {
            "model": None,
            "temperature": 0.7,
        }

        agent = agent_factory.get_agent(
            "query", conversation_config=conversation_config
        )

        # None model should be ignored, use domain model
        assert agent.config.model == "claude-3-opus"  # Domain override
        # Temperature should be overridden
        assert agent.config.temperature == 0.7

    def test_conversation_config_with_invalid_keys(self, agent_factory):
        """Test that invalid keys in conversation config are ignored."""
        conversation_config = {
            "model": "gpt-5",
            "invalid_key": "should_be_ignored",
            "another_invalid": 12345,
        }

        agent = agent_factory.get_agent(
            "query", conversation_config=conversation_config
        )

        # Valid key should work
        assert agent.config.model == "gpt-5"
        # Invalid keys should be ignored (no error)

    def test_conversation_config_with_empty_string_model(self, agent_factory):
        """Test that empty string model uses default."""
        conversation_config = {"model": ""}

        agent = agent_factory.get_agent(
            "query", conversation_config=conversation_config
        )

        # Empty string model - behavior depends on implementation
        # Should either use domain override or base
        # (Current implementation: empty string is falsy, so uses domain)
        assert agent.config.model in ["claude-3-opus", "gpt-4o"]

    def test_use_max_model_tokens_with_no_model_specified(self, agent_factory):
        """Test use_max_model_tokens with no model in conversation config."""
        conversation_config = {
            "use_max_model_tokens": True,
            # No model specified - should use domain/base model
        }

        agent = agent_factory.get_agent(
            "query", conversation_config=conversation_config
        )

        # Should use domain model (claude-3-opus) and its context window
        assert agent.config.model == "claude-3-opus"
        assert agent.config.max_tokens == 200_000  # Claude's context window

    def test_negative_max_tokens(self, agent_factory):
        """Test that negative max_tokens is rejected by AgentConfig validation."""
        conversation_config = {"max_tokens": -1000}

        # Should raise ValueError during config validation
        with pytest.raises(ValueError, match="max_tokens must be positive"):
            agent_factory.get_agent("query", conversation_config=conversation_config)

    def test_very_large_max_tokens(self, agent_factory):
        """Test that very large max_tokens is passed through."""
        conversation_config = {"max_tokens": 999999999}

        agent = agent_factory.get_agent(
            "query", conversation_config=conversation_config
        )

        assert agent.config.max_tokens == 999999999


class TestLogging:
    """Tests for logging behavior (verify no errors, could check log output)."""

    def test_conversation_config_logs_override(self, agent_factory):
        """Test that conversation config creates fresh agent (not cached)."""
        conversation_config = {"model": "gpt-5"}

        # Get two agents with conversation config - should be different instances
        agent1 = agent_factory.get_agent(
            "query", conversation_config=conversation_config
        )
        agent2 = agent_factory.get_agent(
            "query", conversation_config=conversation_config
        )

        # Fresh agents are created (not cached), so they should be different instances
        assert agent1 is not agent2
        # Both should have the conversation config applied
        assert agent1.config.model == "gpt-5"
        assert agent2.config.model == "gpt-5"

    def test_use_max_model_tokens_logs(self, agent_factory):
        """Test that use_max_model_tokens is applied correctly."""
        conversation_config = {
            "model": "gpt-4o",
            "use_max_model_tokens": True,
        }

        agent = agent_factory.get_agent(
            "query", conversation_config=conversation_config
        )

        # Should use context window for gpt-4o (128000)
        assert agent.config.max_tokens == 128_000
        assert agent.config.model == "gpt-4o"
