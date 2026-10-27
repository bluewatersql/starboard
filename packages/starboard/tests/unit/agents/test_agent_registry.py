# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for agent registry.

Phase 3 Component 1: Agent Registry & Metadata

Tests cover:
- AgentCapability domain model
- AgentMetadata domain model
- AgentRegistry registration and lookup
- Capability-based search
- Keyword-based search
"""

import pytest
from pydantic import BaseModel
from starboard.agents.config.registry import (
    AgentCapability,
    AgentMetadata,
    AgentRegistry,
    AgentStatus,
)


# Mock Pydantic schemas for testing (named without Test prefix to avoid pytest collection)
class MockInputSchema(BaseModel):
    """Mock input schema for testing."""

    query: str
    limit: int = 10


class MockOutputSchema(BaseModel):
    """Mock output schema for testing."""

    results: list[str]


class TestAgentCapability:
    """Tests for AgentCapability domain model."""

    def test_capability_creation(self):
        """AgentCapability can be created with all required fields."""
        capability = AgentCapability(
            capability_id="identify_slow_queries",
            name="Identify Slow Queries",
            description="Find the slowest queries in a warehouse",
            keywords=("slow", "slowest", "performance", "queries"),
            input_schema=MockInputSchema,
            output_schema=MockOutputSchema,
            example_queries=(
                "Show me the slowest queries",
                "What are the top 10 slowest queries?",
            ),
        )

        assert capability.capability_id == "identify_slow_queries"
        assert capability.name == "Identify Slow Queries"
        assert "slowest queries" in capability.description
        assert "slow" in capability.keywords
        assert capability.input_schema == MockInputSchema
        assert capability.output_schema == MockOutputSchema
        assert len(capability.example_queries) == 2

    def test_capability_immutable(self):
        """AgentCapability is immutable (frozen dataclass)."""
        capability = AgentCapability(
            capability_id="test",
            name="Test",
            description="Test description",
            keywords=("test",),
            input_schema=MockInputSchema,
            output_schema=MockOutputSchema,
            example_queries=("test query",),
        )

        with pytest.raises(AttributeError):
            capability.name = "Modified"  # type: ignore

    def test_capability_with_empty_keywords(self):
        """AgentCapability can have empty keywords tuple."""
        capability = AgentCapability(
            capability_id="test",
            name="Test",
            description="Test",
            keywords=(),  # Empty
            input_schema=MockInputSchema,
            output_schema=MockOutputSchema,
            example_queries=(),
        )

        assert len(capability.keywords) == 0
        assert len(capability.example_queries) == 0


class TestAgentMetadata:
    """Tests for AgentMetadata domain model."""

    def test_metadata_creation(self):
        """AgentMetadata can be created with all fields."""
        capability = AgentCapability(
            capability_id="test_cap",
            name="Test Capability",
            description="Test",
            keywords=("test",),
            input_schema=MockInputSchema,
            output_schema=MockOutputSchema,
            example_queries=(),
        )

        metadata = AgentMetadata(
            agent_id="performance_analyzer",
            agent_name="Performance Analyzer",
            agent_class="PerformanceAnalyzerAgent",
            description="Analyzes query performance",
            capabilities=(capability,),
            status=AgentStatus.ACTIVE,
            version="1.0.0",
        )

        assert metadata.agent_id == "performance_analyzer"
        assert metadata.agent_name == "Performance Analyzer"
        assert metadata.agent_class == "PerformanceAnalyzerAgent"
        assert "performance" in metadata.description
        assert len(metadata.capabilities) == 1
        assert metadata.status == AgentStatus.ACTIVE
        assert metadata.version == "1.0.0"

    def test_metadata_immutable(self):
        """AgentMetadata is immutable (frozen dataclass)."""
        metadata = AgentMetadata(
            agent_id="test",
            agent_name="Test",
            agent_class="TestAgent",
            description="Test",
            capabilities=(),
            status=AgentStatus.ACTIVE,
            version="1.0.0",
        )

        with pytest.raises(AttributeError):
            metadata.agent_name = "Modified"  # type: ignore

    def test_metadata_with_multiple_capabilities(self):
        """AgentMetadata can have multiple capabilities."""
        cap1 = AgentCapability(
            capability_id="cap1",
            name="Capability 1",
            description="First capability",
            keywords=("one",),
            input_schema=MockInputSchema,
            output_schema=MockOutputSchema,
            example_queries=(),
        )
        cap2 = AgentCapability(
            capability_id="cap2",
            name="Capability 2",
            description="Second capability",
            keywords=("two",),
            input_schema=MockInputSchema,
            output_schema=MockOutputSchema,
            example_queries=(),
        )

        metadata = AgentMetadata(
            agent_id="multi_agent",
            agent_name="Multi Agent",
            agent_class="MultiAgent",
            description="Agent with multiple capabilities",
            capabilities=(cap1, cap2),
            status=AgentStatus.ACTIVE,
            version="1.0.0",
        )

        assert len(metadata.capabilities) == 2
        assert metadata.capabilities[0].capability_id == "cap1"
        assert metadata.capabilities[1].capability_id == "cap2"

    def test_metadata_status_values(self):
        """AgentMetadata supports all status values."""
        for status in [AgentStatus.ACTIVE, AgentStatus.BETA, AgentStatus.DEPRECATED]:
            metadata = AgentMetadata(
                agent_id="test",
                agent_name="Test",
                agent_class="TestAgent",
                description="Test",
                capabilities=(),
                status=status,
                version="1.0.0",
            )
            assert metadata.status == status


class TestAgentRegistry:
    """Tests for AgentRegistry."""

    @pytest.fixture
    def registry(self):
        """Create empty registry for testing."""
        return AgentRegistry()

    @pytest.fixture
    def sample_capability(self):
        """Create sample capability."""
        return AgentCapability(
            capability_id="identify_slow_queries",
            name="Identify Slow Queries",
            description="Find the slowest queries",
            keywords=("slow", "slowest", "performance", "queries"),
            input_schema=MockInputSchema,
            output_schema=MockOutputSchema,
            example_queries=("Show me the slowest queries",),
        )

    @pytest.fixture
    def sample_metadata(self, sample_capability):
        """Create sample agent metadata."""
        return AgentMetadata(
            agent_id="performance_analyzer",
            agent_name="Performance Analyzer",
            agent_class="PerformanceAnalyzerAgent",
            description="Analyzes query performance and identifies bottlenecks",
            capabilities=(sample_capability,),
            status=AgentStatus.ACTIVE,
            version="1.0.0",
        )

    def test_register_agent(self, registry, sample_metadata):
        """Can register an agent in the registry."""
        registry.register(sample_metadata)

        # Should be able to retrieve it
        agent = registry.get_agent("performance_analyzer")
        assert agent is not None
        assert agent.agent_id == "performance_analyzer"
        assert agent.agent_name == "Performance Analyzer"

    def test_register_multiple_agents(self, registry, sample_capability):
        """Can register multiple agents."""
        metadata1 = AgentMetadata(
            agent_id="agent1",
            agent_name="Agent 1",
            agent_class="Agent1",
            description="First agent",
            capabilities=(sample_capability,),
            status=AgentStatus.ACTIVE,
            version="1.0.0",
        )
        metadata2 = AgentMetadata(
            agent_id="agent2",
            agent_name="Agent 2",
            agent_class="Agent2",
            description="Second agent",
            capabilities=(sample_capability,),
            status=AgentStatus.ACTIVE,
            version="1.0.0",
        )

        registry.register(metadata1)
        registry.register(metadata2)

        assert registry.get_agent("agent1") is not None
        assert registry.get_agent("agent2") is not None

    def test_get_nonexistent_agent(self, registry):
        """Getting nonexistent agent returns None."""
        agent = registry.get_agent("nonexistent")
        assert agent is None

    def test_list_all_agents(self, registry, sample_metadata):
        """Can list all registered agents."""
        registry.register(sample_metadata)

        all_agents = registry.list_all()
        assert len(all_agents) == 1
        assert all_agents[0].agent_id == "performance_analyzer"

    def test_list_all_empty_registry(self, registry):
        """Listing all agents in empty registry returns empty list."""
        all_agents = registry.list_all()
        assert len(all_agents) == 0

    def test_list_agents_by_status(self, registry, sample_capability):
        """Can filter agents by status."""
        active_agent = AgentMetadata(
            agent_id="active",
            agent_name="Active Agent",
            agent_class="ActiveAgent",
            description="Active",
            capabilities=(sample_capability,),
            status=AgentStatus.ACTIVE,
            version="1.0.0",
        )
        beta_agent = AgentMetadata(
            agent_id="beta",
            agent_name="Beta Agent",
            agent_class="BetaAgent",
            description="Beta",
            capabilities=(sample_capability,),
            status=AgentStatus.BETA,
            version="0.9.0",
        )
        deprecated_agent = AgentMetadata(
            agent_id="deprecated",
            agent_name="Deprecated Agent",
            agent_class="DeprecatedAgent",
            description="Deprecated",
            capabilities=(sample_capability,),
            status=AgentStatus.DEPRECATED,
            version="0.1.0",
        )

        registry.register(active_agent)
        registry.register(beta_agent)
        registry.register(deprecated_agent)

        active_agents = registry.list_all(status=AgentStatus.ACTIVE)
        assert len(active_agents) == 1
        assert active_agents[0].agent_id == "active"

        beta_agents = registry.list_all(status=AgentStatus.BETA)
        assert len(beta_agents) == 1
        assert beta_agents[0].agent_id == "beta"

        deprecated_agents = registry.list_all(status=AgentStatus.DEPRECATED)
        assert len(deprecated_agents) == 1
        assert deprecated_agents[0].agent_id == "deprecated"

    def test_find_by_capability(self, registry, sample_metadata):
        """Can find agents by capability ID."""
        registry.register(sample_metadata)

        agents = registry.find_by_capability("identify_slow_queries")
        assert len(agents) == 1
        assert agents[0].agent_id == "performance_analyzer"

    def test_find_by_nonexistent_capability(self, registry, sample_metadata):
        """Finding by nonexistent capability returns empty list."""
        registry.register(sample_metadata)

        agents = registry.find_by_capability("nonexistent_capability")
        assert len(agents) == 0

    def test_find_by_capability_multiple_matches(self, registry):
        """Multiple agents can provide the same capability."""
        shared_capability = AgentCapability(
            capability_id="shared_cap",
            name="Shared Capability",
            description="Shared",
            keywords=("shared",),
            input_schema=MockInputSchema,
            output_schema=MockOutputSchema,
            example_queries=(),
        )

        agent1 = AgentMetadata(
            agent_id="agent1",
            agent_name="Agent 1",
            agent_class="Agent1",
            description="First",
            capabilities=(shared_capability,),
            status=AgentStatus.ACTIVE,
            version="1.0.0",
        )
        agent2 = AgentMetadata(
            agent_id="agent2",
            agent_name="Agent 2",
            agent_class="Agent2",
            description="Second",
            capabilities=(shared_capability,),
            status=AgentStatus.ACTIVE,
            version="1.0.0",
        )

        registry.register(agent1)
        registry.register(agent2)

        agents = registry.find_by_capability("shared_cap")
        assert len(agents) == 2
        agent_ids = {a.agent_id for a in agents}
        assert agent_ids == {"agent1", "agent2"}

    def test_search_by_agent_description(self, registry, sample_metadata):
        """Can search agents by keywords in description."""
        registry.register(sample_metadata)

        # Search for word in description
        results = registry.search("performance")
        assert len(results) == 1
        assert results[0].agent_id == "performance_analyzer"

    def test_search_by_capability_keyword(self, registry, sample_metadata):
        """Can search agents by capability keywords."""
        registry.register(sample_metadata)

        # Search for capability keyword
        results = registry.search("slowest")
        assert len(results) == 1
        assert results[0].agent_id == "performance_analyzer"

    def test_search_case_insensitive(self, registry, sample_metadata):
        """Search is case-insensitive."""
        registry.register(sample_metadata)

        results_lower = registry.search("performance")
        results_upper = registry.search("PERFORMANCE")
        results_mixed = registry.search("PeRfOrMaNcE")

        assert len(results_lower) == 1
        assert len(results_upper) == 1
        assert len(results_mixed) == 1

    def test_search_no_matches(self, registry, sample_metadata):
        """Search with no matches returns empty list."""
        registry.register(sample_metadata)

        results = registry.search("nonexistent")
        assert len(results) == 0

    def test_search_multiple_matches(self, registry):
        """Search can return multiple matching agents."""
        cap1 = AgentCapability(
            capability_id="cap1",
            name="Capability 1",
            description="Query analysis",
            keywords=("query", "analysis"),
            input_schema=MockInputSchema,
            output_schema=MockOutputSchema,
            example_queries=(),
        )
        cap2 = AgentCapability(
            capability_id="cap2",
            name="Capability 2",
            description="Cost optimization",
            keywords=("query", "cost"),
            input_schema=MockInputSchema,
            output_schema=MockOutputSchema,
            example_queries=(),
        )

        agent1 = AgentMetadata(
            agent_id="agent1",
            agent_name="Agent 1",
            agent_class="Agent1",
            description="Analyzes query performance",
            capabilities=(cap1,),
            status=AgentStatus.ACTIVE,
            version="1.0.0",
        )
        agent2 = AgentMetadata(
            agent_id="agent2",
            agent_name="Agent 2",
            agent_class="Agent2",
            description="Optimizes query costs",
            capabilities=(cap2,),
            status=AgentStatus.ACTIVE,
            version="1.0.0",
        )

        registry.register(agent1)
        registry.register(agent2)

        # Both have "query" keyword
        results = registry.search("query")
        assert len(results) == 2
        agent_ids = {a.agent_id for a in results}
        assert agent_ids == {"agent1", "agent2"}

    def test_register_overwrites_existing_agent(self, registry, sample_metadata):
        """Registering same agent ID overwrites previous registration."""
        registry.register(sample_metadata)

        # Register again with different name
        updated_metadata = AgentMetadata(
            agent_id="performance_analyzer",  # Same ID
            agent_name="Updated Analyzer",  # Different name
            agent_class="PerformanceAnalyzerAgent",
            description="Updated description",
            capabilities=(),
            status=AgentStatus.BETA,
            version="2.0.0",
        )
        registry.register(updated_metadata)

        agent = registry.get_agent("performance_analyzer")
        assert agent is not None
        assert agent.agent_name == "Updated Analyzer"
        assert agent.version == "2.0.0"
        assert agent.status == AgentStatus.BETA
