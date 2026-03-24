"""Service catalog domain models.

Defines the structure of service catalog entries, capabilities, and examples
for the service discovery and handoff recommendation system.

Part of Phase 9: Service Catalog & Next-Step Suggestions

Examples:
    >>> entry = ServiceCatalogEntry(
    ...     service_id="perf_analyzer_v1",
    ...     service_type=ServiceType.AGENT,
    ...     name="Performance Analyzer",
    ...     domain="performance",
    ...     description="Analyzes Spark performance bottlenecks",
    ...     capabilities=(),
    ...     version="1.0.0",
    ...     status=ServiceStatus.ACTIVE,
    ... )
    >>> entry.service_id
    'perf_analyzer_v1'
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ServiceType(str, Enum):
    """Type of service in the catalog.

    Attributes:
        AGENT: A full domain agent (e.g., QueryAgent, PerformanceAgent)
        TOOL: A standalone tool (e.g., OptimizeTable, AnalyzeCosts)
        CAPABILITY: A specific capability (e.g., identify_slow_queries)
    """

    AGENT = "agent"
    TOOL = "tool"
    CAPABILITY = "capability"


class ServiceStatus(str, Enum):
    """Status of a service in the catalog.

    Attributes:
        ACTIVE: Service is production-ready and recommended
        BETA: Service is available but in testing
        DEPRECATED: Service is still available but no longer recommended
    """

    ACTIVE = "active"
    BETA = "beta"
    DEPRECATED = "deprecated"


@dataclass(frozen=True)
class ServiceCapability:
    """Represents a specific capability of a service.

    A capability is a discrete function or feature that a service provides.
    Used to help match user needs to appropriate services.

    Attributes:
        capability_id: Unique identifier (e.g., "identify_slow_queries")
        name: Human-readable name (e.g., "Identify Slow Queries")
        description: What this capability does

    Examples:
        >>> capability = ServiceCapability(
        ...     capability_id="identify_slow_queries",
        ...     name="Identify Slow Queries",
        ...     description="Finds queries exceeding performance thresholds",
        ... )
        >>> capability.capability_id
        'identify_slow_queries'
    """

    capability_id: str
    name: str
    description: str


@dataclass(frozen=True)
class ServiceExample:
    """Represents an example query handled by a service.

    Used for documentation and to help match user queries to services.

    Attributes:
        example_id: Unique identifier for this example
        user_query: Example user query (natural language)
        expected_capability: Which capability should handle this query

    Examples:
        >>> example = ServiceExample(
        ...     example_id="ex1",
        ...     user_query="Why is my query slow?",
        ...     expected_capability="identify_slow_queries",
        ... )
        >>> example.user_query
        'Why is my query slow?'
    """

    example_id: str
    user_query: str
    expected_capability: str


@dataclass(frozen=True)
class ServiceCatalogEntry:
    """Represents a single service in the catalog.

    This is what the get_service_catalog tool returns. Contains complete
    metadata about an agent, tool, or capability.

    Attributes:
        service_id: Unique identifier (e.g., "perf_analyzer_v1")
        service_type: Type of service (agent, tool, capability)
        name: Human-readable name
        domain: Domain category (e.g., "performance", "finops")
        description: Brief description of what it does
        capabilities: Tuple of specific capabilities
        version: Semantic version (e.g., "1.0.0")
        status: Service status (active, beta, deprecated)
        input_schema: Optional JSON schema for inputs
        examples: Tuple of example queries

    Examples:
        >>> entry = ServiceCatalogEntry(
        ...     service_id="query_optimizer_v1",
        ...     service_type=ServiceType.AGENT,
        ...     name="Query Optimizer",
        ...     domain="query",
        ...     description="Optimizes Databricks SQL queries",
        ...     capabilities=(),
        ...     version="1.0.0",
        ...     status=ServiceStatus.ACTIVE,
        ... )
        >>> entry.domain
        'query'
    """

    service_id: str
    service_type: ServiceType
    name: str
    domain: str
    description: str
    capabilities: tuple[ServiceCapability, ...]
    version: str
    status: ServiceStatus
    input_schema: dict[str, Any] | None = None
    examples: tuple[ServiceExample, ...] = ()

    def __post_init__(self) -> None:
        """Validate catalog entry after initialization.

        Raises:
            ValueError: If required fields are empty or invalid
        """
        # Validate required string fields
        if not self.service_id or not self.service_id.strip():
            raise ValueError("service_id cannot be empty")

        if not self.name or not self.name.strip():
            raise ValueError("name cannot be empty")

        if not self.domain or not self.domain.strip():
            raise ValueError("domain cannot be empty")

        # Validate semantic version format (X.Y.Z)
        version_pattern = r"^\d+\.\d+\.\d+$"
        if not re.match(version_pattern, self.version):
            raise ValueError(
                f"version must follow semantic versioning (X.Y.Z): got '{self.version}'"
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert catalog entry to dictionary.

        Returns:
            Dictionary representation suitable for JSON serialization

        Examples:
            >>> entry = ServiceCatalogEntry(...)
            >>> data = entry.to_dict()
            >>> data["service_id"]
            'query_optimizer_v1'
        """
        return {
            "service_id": self.service_id,
            "service_type": self.service_type.value,
            "name": self.name,
            "domain": self.domain,
            "description": self.description,
            "capabilities": [
                {
                    "capability_id": cap.capability_id,
                    "name": cap.name,
                    "description": cap.description,
                }
                for cap in self.capabilities
            ],
            "version": self.version,
            "status": self.status.value,
            "input_schema": self.input_schema,
            "examples": [
                {
                    "example_id": ex.example_id,
                    "user_query": ex.user_query,
                    "expected_capability": ex.expected_capability,
                }
                for ex in self.examples
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ServiceCatalogEntry:
        """Create catalog entry from dictionary.

        Args:
            data: Dictionary containing catalog entry fields

        Returns:
            ServiceCatalogEntry instance

        Examples:
            >>> data = {"service_id": "test", "service_type": "agent", ...}
            >>> entry = ServiceCatalogEntry.from_dict(data)
        """
        # Convert capabilities
        capabilities = tuple(
            ServiceCapability(
                capability_id=cap["capability_id"],
                name=cap["name"],
                description=cap["description"],
            )
            for cap in data.get("capabilities", [])
        )

        # Convert examples
        examples = tuple(
            ServiceExample(
                example_id=ex["example_id"],
                user_query=ex["user_query"],
                expected_capability=ex["expected_capability"],
            )
            for ex in data.get("examples", [])
        )

        return cls(
            service_id=data["service_id"],
            service_type=ServiceType(data["service_type"]),
            name=data["name"],
            domain=data["domain"],
            description=data["description"],
            capabilities=capabilities,
            version=data["version"],
            status=ServiceStatus(data["status"]),
            input_schema=data.get("input_schema"),
            examples=examples,
        )
