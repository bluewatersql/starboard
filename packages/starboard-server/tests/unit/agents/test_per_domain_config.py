# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Tests for per-domain model configuration.

Tests that domain-specific model overrides work correctly through:
1. Conversation config (domain_model_overrides)
2. Environment variables (DOMAIN_MODEL_OVERRIDES)
3. Agent factory applying correct model per domain
"""

from unittest.mock import Mock

import pytest
from starboard_server.agents.agent_factory import AgentFactory
from starboard_server.agents.config.agent_config import AgentConfig
from starboard_server.api.models import ConversationConfig


@pytest.fixture
def mock_llm_client():
    """Mock LLM client for testing."""
    return Mock()


@pytest.fixture
def mock_tool_registry():
    """Mock tool registry for testing."""
    registry = Mock()
    registry._tools = {}  # Add _tools attribute for DomainAgent's complete check
    registry.register = Mock()  # Add register method for DomainAgent
    registry.filter_by_domain = Mock(return_value=registry)
    registry.list_tools = Mock(return_value=[])
    return registry


@pytest.fixture
def base_config_with_domain_overrides():
    """Base config with domain-specific model overrides."""
    return AgentConfig(
        model="databricks-claude-sonnet-4-5",
        temperature=0.4,
        domain_model_overrides={
            "query": "databricks-gpt-5",
            "job": "databricks-gpt-5-1",
        },
    )


@pytest.fixture
def agent_factory(
    mock_llm_client, mock_tool_registry, base_config_with_domain_overrides
):
    """Agent factory with domain-specific configuration."""
    return AgentFactory(
        llm_client=mock_llm_client,
        tool_registry=mock_tool_registry,
        base_config=base_config_with_domain_overrides,
        events=None,
    )


class TestAgentFactoryDomainOverrides:
    """Test AgentFactory with domain-specific model overrides."""

    def test_domain_override_from_base_config(self, agent_factory):
        """Test that domain overrides from base config are applied."""
        # Create agent for query domain (should use databricks-gpt-5)
        conversation_config = None
        agent = agent_factory._create_agent("query", conversation_config)

        # Verify the agent config has the correct model
        assert agent.config.model == "databricks-gpt-5"

    def test_domain_override_from_conversation_config(self, agent_factory):
        """Test that domain overrides from conversation config take priority."""
        # Conversation config with domain-specific override
        conversation_config = {
            "domain_model_overrides": {"query": "databricks-gemini-2.5-pro"}
        }

        agent = agent_factory._create_agent("query", conversation_config)

        # Should use conversation config override, not base config
        assert agent.config.model == "databricks-gemini-2.5-pro"

    def test_global_model_override(self, agent_factory):
        """Test that global model override applies to all domains."""
        # Conversation config with global model
        conversation_config = {"model": "databricks-llama-4-maverick"}

        # Domain without specific override should use global model
        agent = agent_factory._create_agent("diagnostic", conversation_config)
        assert agent.config.model == "databricks-llama-4-maverick"

    def test_domain_override_takes_precedence_over_global(self, agent_factory):
        """Test that domain override takes precedence over global model."""
        conversation_config = {
            "model": "databricks-llama-4-maverick",
            "domain_model_overrides": {"query": "databricks-gpt-5"},
        }

        # Query domain should use domain-specific override
        query_agent = agent_factory._create_agent("query", conversation_config)
        assert query_agent.config.model == "databricks-gpt-5"

        # Other domain should use global model
        job_agent = agent_factory._create_agent("diagnostic", conversation_config)
        assert job_agent.config.model == "databricks-llama-4-maverick"

    def test_no_override_uses_default(self, agent_factory):
        """Test that domains without overrides use the default model."""
        conversation_config = None

        # Diagnostic domain has no override, should use default
        agent = agent_factory._create_agent("diagnostic", conversation_config)
        assert agent.config.model == "databricks-claude-sonnet-4-5"


class TestConversationConfigDomainOverrides:
    """Test ConversationConfig with domain model overrides."""

    def test_conversation_config_accepts_domain_overrides(self):
        """Test that ConversationConfig accepts domain_model_overrides."""
        config = ConversationConfig(
            model="databricks-claude-sonnet-4-5",
            temperature=0.4,
            domain_model_overrides={
                "query": "databricks-gpt-5",
                "job": "databricks-gpt-5-1",
            },
        )

        assert config.domain_model_overrides is not None
        assert config.domain_model_overrides["query"] == "databricks-gpt-5"
        assert config.domain_model_overrides["job"] == "databricks-gpt-5-1"

    def test_conversation_config_domain_overrides_optional(self):
        """Test that domain_model_overrides is optional."""
        config = ConversationConfig(
            model="databricks-claude-sonnet-4-5",
            temperature=0.4,
        )

        assert config.domain_model_overrides is None

    def test_conversation_config_empty_domain_overrides(self):
        """Test that empty domain_model_overrides dict is allowed."""
        config = ConversationConfig(
            model="databricks-claude-sonnet-4-5",
            domain_model_overrides={},
        )

        assert config.domain_model_overrides == {}
