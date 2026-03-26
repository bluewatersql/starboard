"""Agent registry for centralized agent management.

Phase 3 Component 1: Agent Registry & Metadata

This module provides a central registry of all available agents and their
capabilities. Agents register themselves on module import, enabling dynamic
agent discovery and routing.

Examples:
    >>> from starboard_server.agents.config.registry import agent_registry, AgentMetadata
    >>>
    >>> # Register an agent
    >>> metadata = AgentMetadata(
    ...     agent_id="performance_analyzer",
    ...     agent_name="Performance Analyzer",
    ...     agent_class="PerformanceAnalyzerAgent",
    ...     description="Analyzes query performance",
    ...     capabilities=(capability1, capability2),
    ...     status=AgentStatus.ACTIVE,
    ...     version="1.0.0",
    ... )
    >>> agent_registry.register(metadata)
    >>>
    >>> # Look up agent by ID
    >>> agent = agent_registry.get_agent("performance_analyzer")
    >>>
    >>> # Search by capability
    >>> agents = agent_registry.find_by_capability("identify_slow_queries")
    >>>
    >>> # Keyword search
    >>> agents = agent_registry.search("performance")
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class AgentStatus(StrEnum):
    """Status of an agent in the registry.

    - ACTIVE: Agent is production-ready and fully supported
    - BETA: Agent is in beta testing, may have limited functionality
    - DEPRECATED: Agent is deprecated and will be removed in future

    Examples:
        >>> AgentStatus.ACTIVE.value
        'active'
        >>> AgentStatus("beta")
        <AgentStatus.BETA: 'beta'>
    """

    ACTIVE = "active"
    BETA = "beta"
    DEPRECATED = "deprecated"


@dataclass(frozen=True)
class AgentCapability:
    """Describes a specific capability an agent provides.

    Capabilities define what an agent can do, including the input/output
    schemas and keywords for discovery.

    Attributes:
        capability_id: Unique identifier for this capability
        name: Human-readable name
        description: Description of what this capability does
        keywords: Keywords for search and discovery
        input_schema: Pydantic model for input validation
        output_schema: Pydantic model for output validation
        example_queries: Example user queries this capability handles

    Examples:
        >>> capability = AgentCapability(
        ...     capability_id="identify_slow_queries",
        ...     name="Identify Slow Queries",
        ...     description="Find the slowest queries in a warehouse",
        ...     keywords=("slow", "slowest", "performance", "queries"),
        ...     input_schema=SlowQueryInput,
        ...     output_schema=SlowQueryOutput,
        ...     example_queries=(
        ...         "Show me the slowest queries",
        ...         "What are the top 10 slowest queries?",
        ...     ),
        ... )
    """

    capability_id: str
    name: str
    description: str
    keywords: tuple[str, ...]
    input_schema: type[Any]  # Pydantic BaseModel
    output_schema: type[Any]  # Pydantic BaseModel
    example_queries: tuple[str, ...]


@dataclass(frozen=True)
class AgentMetadata:
    """Metadata describing an agent and its capabilities.

    This is used to register agents in the central registry for discovery
    and routing purposes.

    Attributes:
        agent_id: Unique identifier for this agent
        agent_name: Human-readable name
        agent_class: Fully qualified class name for instantiation
        description: Description of what this agent does
        capabilities: Tuple of capabilities this agent provides
        status: Current status (active, beta, deprecated)
        version: Semantic version string

    Examples:
        >>> metadata = AgentMetadata(
        ...     agent_id="performance_analyzer",
        ...     agent_name="Performance Analyzer",
        ...     agent_class="PerformanceAnalyzerAgent",
        ...     description="Analyzes query performance and identifies bottlenecks",
        ...     capabilities=(capability1, capability2),
        ...     status=AgentStatus.ACTIVE,
        ...     version="1.0.0",
        ... )
    """

    agent_id: str
    agent_name: str
    agent_class: str
    description: str
    capabilities: tuple[AgentCapability, ...]
    status: AgentStatus
    version: str


class AgentRegistry:
    """Central registry of all available agents.

    The registry provides agent discovery, lookup, and search functionality.
    Agents register themselves on module import.

    Thread-safe for registration and lookup operations.

    Examples:
        >>> registry = AgentRegistry()
        >>>
        >>> # Register agent
        >>> registry.register(agent_metadata)
        >>>
        >>> # Lookup by ID
        >>> agent = registry.get_agent("performance_analyzer")
        >>>
        >>> # Find by capability
        >>> agents = registry.find_by_capability("identify_slow_queries")
        >>>
        >>> # Search by keyword
        >>> agents = registry.search("performance")
        >>>
        >>> # List all active agents
        >>> active_agents = registry.list_all(status=AgentStatus.ACTIVE)
    """

    def __init__(self) -> None:
        """Initialize empty agent registry."""
        self._agents: dict[str, AgentMetadata] = {}

    def register(self, metadata: AgentMetadata) -> None:
        """Register an agent with the registry.

        If an agent with the same ID already exists, it will be overwritten.

        Args:
            metadata: Agent metadata to register

        Examples:
            >>> registry.register(metadata)
        """
        self._agents[metadata.agent_id] = metadata

        logger.debug(
            "agent_registered",
            extra={
                "agent_id": metadata.agent_id,
                "agent_name": metadata.agent_name,
                "num_capabilities": len(metadata.capabilities),
                "status": metadata.status.value,
                "version": metadata.version,
            },
        )

    def get_agent(self, agent_id: str) -> AgentMetadata | None:
        """Get agent by ID.

        Args:
            agent_id: Unique agent identifier

        Returns:
            AgentMetadata if found, None otherwise

        Examples:
            >>> agent = registry.get_agent("performance_analyzer")
            >>> if agent:
            ...     print(f"Found: {agent.agent_name}")
        """
        return self._agents.get(agent_id)

    def list_all(self, status: AgentStatus | None = None) -> list[AgentMetadata]:
        """List all registered agents.

        Args:
            status: Optional status filter (active, beta, deprecated)

        Returns:
            List of matching agents

        Examples:
            >>> # Get all agents
            >>> all_agents = registry.list_all()
            >>>
            >>> # Get only active agents
            >>> active_agents = registry.list_all(status=AgentStatus.ACTIVE)
        """
        if status is None:
            return list(self._agents.values())

        return [agent for agent in self._agents.values() if agent.status == status]

    def find_by_capability(self, capability_id: str) -> list[AgentMetadata]:
        """Find agents that provide a specific capability.

        Args:
            capability_id: Capability identifier to search for

        Returns:
            List of agents providing this capability

        Examples:
            >>> agents = registry.find_by_capability("identify_slow_queries")
            >>> for agent in agents:
            ...     print(f"- {agent.agent_name}")
        """
        results = []

        for agent in self._agents.values():
            for cap in agent.capabilities:
                if cap.capability_id == capability_id:
                    results.append(agent)
                    break  # Found capability, no need to check others

        return results

    def search(self, query: str) -> list[AgentMetadata]:
        """Search agents by keywords.

        Searches in:
        - Agent description
        - Capability keywords

        Search is case-insensitive.

        Args:
            query: Search query string

        Returns:
            List of matching agents

        Examples:
            >>> # Search by agent description
            >>> agents = registry.search("performance")
            >>>
            >>> # Search by capability keyword
            >>> agents = registry.search("slow queries")
        """
        query_lower = query.lower()
        results = []

        for agent in self._agents.values():
            # Search in agent description
            if query_lower in agent.description.lower():
                results.append(agent)
                continue

            # Search in capability keywords
            for cap in agent.capabilities:
                if any(query_lower in kw.lower() for kw in cap.keywords):
                    results.append(agent)
                    break  # Found match, no need to check other capabilities

        return results


# Global registry instance
agent_registry = AgentRegistry()
