"""
Unit tests for DomainAgent handoff context extraction.

Tests the _initialize_state method's ability to extract nested handoff_context
parameters from user_constraints, ensuring cross-agent context passing works.
"""

from unittest.mock import AsyncMock, Mock

import pytest
from starboard_core.domain.models.llm import OptimizationMode
from starboard_server.adapters.llm.base import BaseLLMClient
from starboard_server.agents.config.agent_config import AgentConfig
from starboard_server.agents.domain.domain_agent import DomainAgent
from starboard_server.agents.tools import NativeToolAdapter, ToolMetadata, ToolRegistry


@pytest.fixture
def mock_llm_client():
    """Create a mock LLM client."""
    mock = Mock(spec=BaseLLMClient)
    mock.json_response = AsyncMock(return_value={"result": "test"})
    mock.text_response = AsyncMock(return_value="Test response")
    return mock


@pytest.fixture
def mock_tool_registry():
    """Create a minimal tool registry with required tools."""
    registry = ToolRegistry()

    # Create mock tool instance
    mock_tool_instance = Mock()

    # Register minimal tools needed for UC agent
    for tool_name in [
        "get_table_metadata",
        "discover_tables",
        "get_table_lineage",
    ]:
        setattr(mock_tool_instance, tool_name, AsyncMock(return_value={}))
        metadata = ToolMetadata(
            name=tool_name,
            description=f"{tool_name} description",
            parameters={"type": "object", "properties": {}},
        )
        adapter = NativeToolAdapter(mock_tool_instance, tool_name, metadata)
        registry.register(tool_name, adapter)

    return registry


@pytest.fixture
def mock_agent_config():
    """Create a minimal agent config for testing."""
    return AgentConfig(
        model="gpt-4o",
        temperature=0.4,
        max_steps=10,
        max_tokens=10000,
        domain="uc",  # Use UC agent for testing table optimization
    )


@pytest.fixture
def domain_agent(mock_llm_client, mock_tool_registry, mock_agent_config):
    """Create a DomainAgent with mocked dependencies."""
    agent = DomainAgent(
        llm_client=mock_llm_client,
        tool_registry=mock_tool_registry,
        config=mock_agent_config,
        enable_metrics=False,
    )
    return agent


class TestHandoffContextExtraction:
    """Tests for extracting handoff context from user_constraints."""

    def test_extracts_nested_handoff_context_tables(self, domain_agent):
        """Test that nested tables in handoff_context are extracted."""
        # Simulate what happens when NextStepGenerator passes handoff context
        # parameters={"handoff_context": handoff.context_to_pass}
        context = {
            "conversation_history": [],
            "working_memory": {
                "metrics": {
                    "user_constraints": {
                        "handoff_context": {
                            "tables": [
                                "cprice_main.core.orders",
                                "cprice_main.core.order_financial_items",
                                "cprice_main.core.products",
                            ],
                            "query_id": "b6722cfa-b486-4cc3-82b8-5f08465974a9",
                        }
                    }
                }
            },
        }

        state = domain_agent._initialize_state(
            user_input="Deep dive into table optimization",
            mode=OptimizationMode.ONLINE,
            user_id="test_user",
            context=context,
        )

        # The enriched user message should contain the tables
        user_message = state.conversation_history[1].content
        assert "tables:" in user_message.lower() or "tables" in user_message
        assert "cprice_main.core.orders" in user_message
        assert "cprice_main.core.order_financial_items" in user_message
        assert "cprice_main.core.products" in user_message
        assert "b6722cfa-b486-4cc3-82b8-5f08465974a9" in user_message

    def test_extracts_nested_handoff_context_single_table(self, domain_agent):
        """Test that a single table_name in handoff_context is extracted."""
        context = {
            "conversation_history": [],
            "working_memory": {
                "metrics": {
                    "user_constraints": {
                        "handoff_context": {
                            "table_name": "catalog.schema.my_table",
                        }
                    }
                }
            },
        }

        state = domain_agent._initialize_state(
            user_input="Analyze this table",
            mode=OptimizationMode.ONLINE,
            user_id="test_user",
            context=context,
        )

        user_message = state.conversation_history[1].content
        assert "catalog.schema.my_table" in user_message

    def test_extracts_nested_handoff_context_job_id(self, domain_agent):
        """Test that job_id in handoff_context is extracted."""
        context = {
            "conversation_history": [],
            "working_memory": {
                "metrics": {
                    "user_constraints": {
                        "handoff_context": {
                            "job_id": "31942593021809",
                            "context": "High-frequency execution pattern detected",
                        }
                    }
                }
            },
        }

        state = domain_agent._initialize_state(
            user_input="Analyze job performance",
            mode=OptimizationMode.ONLINE,
            user_id="test_user",
            context=context,
        )

        user_message = state.conversation_history[1].content
        assert "31942593021809" in user_message
        assert "High-frequency execution pattern detected" in user_message

    def test_extracts_nested_handoff_context_summary(self, domain_agent):
        """Test that summary in handoff_context is extracted."""
        context = {
            "conversation_history": [],
            "working_memory": {
                "metrics": {
                    "user_constraints": {
                        "handoff_context": {
                            "summary": "Query uses 3 tables with expensive joins",
                        }
                    }
                }
            },
        }

        state = domain_agent._initialize_state(
            user_input="Optimize the tables",
            mode=OptimizationMode.ONLINE,
            user_id="test_user",
            context=context,
        )

        user_message = state.conversation_history[1].content
        assert "Query uses 3 tables with expensive joins" in user_message

    def test_extracts_flat_and_nested_context(self, domain_agent):
        """Test that both flat and nested user_constraints are extracted."""
        context = {
            "conversation_history": [],
            "working_memory": {
                "metrics": {
                    "user_constraints": {
                        # Flat constraints (from intent classification)
                        "warehouse_id": "main_warehouse",
                        # Nested handoff context (from NextStepGenerator)
                        "handoff_context": {
                            "tables": ["db.schema.table1", "db.schema.table2"],
                            "query_id": "q_123",
                        },
                    }
                }
            },
        }

        state = domain_agent._initialize_state(
            user_input="Deep analysis",
            mode=OptimizationMode.ONLINE,
            user_id="test_user",
            context=context,
        )

        user_message = state.conversation_history[1].content
        # Both flat and nested should be present
        assert "main_warehouse" in user_message
        assert "db.schema.table1" in user_message
        assert "db.schema.table2" in user_message
        assert "q_123" in user_message

    def test_handles_empty_handoff_context(self, domain_agent):
        """Test that empty handoff_context doesn't crash."""
        context = {
            "conversation_history": [],
            "working_memory": {
                "metrics": {
                    "user_constraints": {
                        "handoff_context": {},
                    }
                }
            },
        }

        # Should not raise
        state = domain_agent._initialize_state(
            user_input="Test input",
            mode=OptimizationMode.ONLINE,
            user_id="test_user",
            context=context,
        )

        assert state is not None
        assert state.goal == "Test input"

    def test_handles_non_dict_handoff_context(self, domain_agent):
        """Test that non-dict handoff_context (legacy string) is ignored."""
        context = {
            "conversation_history": [],
            "working_memory": {
                "metrics": {
                    "user_constraints": {
                        # Legacy format: handoff_context as string
                        "handoff_context": "Some legacy context string",
                    }
                }
            },
        }

        # Should not raise, but won't extract nested values
        state = domain_agent._initialize_state(
            user_input="Test input",
            mode=OptimizationMode.ONLINE,
            user_id="test_user",
            context=context,
        )

        assert state is not None
