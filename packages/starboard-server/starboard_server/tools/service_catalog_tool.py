# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Service Catalog Tool for agent discovery and handoff recommendations.

Provides catalog registry and lookup functionality for service discovery.
Part of the router-centric orchestration pattern.

Part of Phase 9: Service Catalog & Next-Step Suggestions
Updated in Phase 3 of caching abstraction for async cache support.

Examples:
    >>> tool = ServiceCatalogTool()
    >>> tool.register_entry(entry)
    >>> entries = tool.get_entries(domain="performance")
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starboard_server.domain.models.service_catalog import (
    ServiceCatalogEntry,
    ServiceStatus,
    ServiceType,
)
from starboard_server.infra.constraints.catalog_cache import CatalogCache
from starboard_server.infra.observability.logging import get_logger

if TYPE_CHECKING:
    from starboard_core.ports.cache_store import CacheStore

logger = get_logger(__name__)


class CatalogRegistry:
    """Registry for managing service catalog entries.

    Provides storage and filtering operations for catalog entries.
    Thread-safe for read operations, write operations should be serialized.

    Attributes:
        _entries: Internal dictionary mapping service_id to catalog entry

    Examples:
        >>> registry = CatalogRegistry()
        >>> registry.register(entry)
        >>> result = registry.get("service_id")
    """

    def __init__(self) -> None:
        """Initialize empty catalog registry."""
        self._entries: dict[str, ServiceCatalogEntry] = {}

    def register(self, entry: ServiceCatalogEntry) -> None:
        """Register a catalog entry.

        If an entry with the same service_id exists, it will be replaced.

        Args:
            entry: Catalog entry to register

        Examples:
            >>> registry.register(entry)
            >>> registry.size()
            1
        """
        self._entries[entry.service_id] = entry
        logger.debug(
            "catalog_entry_registered",
            service_id=entry.service_id,
            domain=entry.domain,
            service_type=entry.service_type.value,
        )

    def get(self, service_id: str) -> ServiceCatalogEntry | None:
        """Retrieve a catalog entry by service_id.

        Args:
            service_id: Unique service identifier

        Returns:
            Catalog entry if found, None otherwise

        Examples:
            >>> entry = registry.get("perf_analyzer")
            >>> entry.name
            'Performance Analyzer'
        """
        return self._entries.get(service_id)

    def list_all(self) -> list[ServiceCatalogEntry]:
        """List all registered catalog entries.

        Returns:
            List of all catalog entries (copy, not internal state)

        Examples:
            >>> entries = registry.list_all()
            >>> len(entries)
            5
        """
        return list(self._entries.values())

    def size(self) -> int:
        """Get the number of registered entries.

        Returns:
            Count of registered entries

        Examples:
            >>> registry.size()
            5
        """
        return len(self._entries)

    def filter_by_domain(self, domain: str) -> list[ServiceCatalogEntry]:
        """Filter entries by domain.

        Args:
            domain: Domain to filter by (e.g., "performance", "finops")

        Returns:
            List of entries matching the domain

        Examples:
            >>> perf_entries = registry.filter_by_domain("performance")
            >>> all(e.domain == "performance" for e in perf_entries)
            True
        """
        return [entry for entry in self._entries.values() if entry.domain == domain]

    def filter_by_type(self, service_type: ServiceType) -> list[ServiceCatalogEntry]:
        """Filter entries by service type.

        Args:
            service_type: Type to filter by (AGENT, TOOL, CAPABILITY)

        Returns:
            List of entries matching the service type

        Examples:
            >>> agents = registry.filter_by_type(ServiceType.AGENT)
            >>> all(e.service_type == ServiceType.AGENT for e in agents)
            True
        """
        return [
            entry
            for entry in self._entries.values()
            if entry.service_type == service_type
        ]

    def filter_by_status(self, status: ServiceStatus) -> list[ServiceCatalogEntry]:
        """Filter entries by status.

        Args:
            status: Status to filter by (ACTIVE, BETA, DEPRECATED)

        Returns:
            List of entries matching the status

        Examples:
            >>> active = registry.filter_by_status(ServiceStatus.ACTIVE)
            >>> all(e.status == ServiceStatus.ACTIVE for e in active)
            True
        """
        return [entry for entry in self._entries.values() if entry.status == status]


class ServiceCatalogTool:
    """Service catalog tool for agent discovery and handoff recommendations.

    Provides the public interface for accessing the service catalog.
    Used by the router agent to discover available services and capabilities.

    Disabled Domains:
        Services with domains in the disabled_domains list are filtered out
        from all query results. This respects DISABLED_AGENT_DOMAINS config
        and ensures consistency between routing and service discovery.

    Attributes:
        registry: Catalog registry instance
        disabled_domains: Set of domain names to exclude from results

    Examples:
        >>> tool = ServiceCatalogTool(disabled_domains=["diagnostic"])
        >>> tool.register_entry(entry)
        >>> entries = tool.get_entries(domain="performance", status=ServiceStatus.ACTIVE)
    """

    def __init__(
        self,
        initial_entries: list[ServiceCatalogEntry] | None = None,
        enable_cache: bool = True,
        cache_ttl: int = 300,
        disabled_domains: list[str] | None = None,
        cache_store: CacheStore | None = None,
    ) -> None:
        """Initialize service catalog tool.

        Args:
            initial_entries: Optional list of entries to register immediately
            enable_cache: Whether to enable caching (default True)
            cache_ttl: Cache TTL in seconds (default 300)
            disabled_domains: List of domains to exclude from results.
                            Should be sourced from DISABLED_AGENT_DOMAINS config.
            cache_store: Optional CacheStore for cache backend (InMemory or Redis).
                        If not provided and enable_cache=True, creates InMemoryCacheStore.

        Examples:
            >>> tool = ServiceCatalogTool(
            ...     initial_entries=[entry1, entry2],
            ...     disabled_domains=["diagnostic", "compute"],
            ... )
            >>> tool.registry.size()  # All entries registered
            2
            >>> len(tool.get_all_entries())  # Disabled domains filtered out
            1
        """
        self.registry = CatalogRegistry()
        self._disabled_domains: frozenset[str] = frozenset(disabled_domains or [])

        # Initialize cache with provided store or create InMemoryCacheStore
        if enable_cache:
            if cache_store is None:
                # Import here to avoid circular dependency
                from starboard_server.adapters.state.inmemory.cache_store import (
                    InMemoryCacheStore,
                )

                cache_store = InMemoryCacheStore()
            self.cache: CatalogCache | None = CatalogCache(
                store=cache_store, ttl_seconds=cache_ttl
            )
        else:
            self.cache = None

        if initial_entries:
            for entry in initial_entries:
                self.registry.register(entry)

        logger.debug(
            "service_catalog_tool_initialized",
            entry_count=self.registry.size(),
            cache_enabled=enable_cache,
            disabled_domains=(
                list(self._disabled_domains) if self._disabled_domains else None
            ),
        )

    @property
    def disabled_domains(self) -> frozenset[str]:
        """Get the set of disabled domains."""
        return self._disabled_domains

    def _filter_disabled(
        self, entries: list[ServiceCatalogEntry]
    ) -> list[ServiceCatalogEntry]:
        """Filter out entries from disabled domains.

        Args:
            entries: List of catalog entries to filter

        Returns:
            List with disabled domain entries removed
        """
        if not self._disabled_domains:
            return entries
        return [e for e in entries if e.domain not in self._disabled_domains]

    def register_entry(self, entry: ServiceCatalogEntry) -> None:
        """Register a new catalog entry.

        Note: For cache invalidation, call invalidate_cache() separately
        after registration in async context.

        Args:
            entry: Catalog entry to register

        Examples:
            >>> tool.register_entry(new_entry)
            >>> await tool.invalidate_cache()  # Clear cache in async context
        """
        self.registry.register(entry)

    async def invalidate_cache(self) -> None:
        """Invalidate the cache (clear all entries).

        Call this after registering new entries to ensure
        the cache reflects the updated registry.

        Examples:
            >>> tool.register_entry(new_entry)
            >>> await tool.invalidate_cache()
        """
        if self.cache:
            await self.cache.clear()
            logger.debug("catalog_cache_invalidated")

    def get_entry(self, service_id: str) -> ServiceCatalogEntry | None:
        """Retrieve a catalog entry by service_id.

        Args:
            service_id: Unique service identifier

        Returns:
            Catalog entry if found, None otherwise

        Examples:
            >>> entry = tool.get_entry("perf_analyzer")
            >>> entry.name
            'Performance Analyzer'
        """
        return self.registry.get(service_id)

    def get_all_entries(self) -> list[ServiceCatalogEntry]:
        """Retrieve all catalog entries (excluding disabled domains).

        Returns:
            List of all registered catalog entries (disabled domains filtered out)

        Examples:
            >>> entries = tool.get_all_entries()
            >>> len(entries)
            5
        """
        return self._filter_disabled(self.registry.list_all())

    def get_entries(
        self,
        domain: str | None = None,
        service_type: ServiceType | None = None,
        status: ServiceStatus | None = None,
    ) -> list[ServiceCatalogEntry]:
        """Retrieve catalog entries with optional filtering (excluding disabled domains).

        Args:
            domain: Optional domain filter (e.g., "performance")
            service_type: Optional service type filter (AGENT, TOOL, CAPABILITY)
            status: Optional status filter (ACTIVE, BETA, DEPRECATED)

        Returns:
            List of entries matching all provided filters (disabled domains filtered out)

        Examples:
            >>> # Get all active performance agents
            >>> entries = tool.get_entries(
            ...     domain="performance",
            ...     service_type=ServiceType.AGENT,
            ...     status=ServiceStatus.ACTIVE,
            ... )
        """
        # Start with filtered entries (disabled domains removed)
        entries = self._filter_disabled(self.registry.list_all())

        # Apply additional filters sequentially
        if domain is not None:
            entries = [e for e in entries if e.domain == domain]

        if service_type is not None:
            entries = [e for e in entries if e.service_type == service_type]

        if status is not None:
            entries = [e for e in entries if e.status == status]

        logger.debug(
            "catalog_entries_filtered",
            domain=domain,
            service_type=service_type.value if service_type else None,
            status=status.value if status else None,
            result_count=len(entries),
            disabled_domains=(
                list(self._disabled_domains) if self._disabled_domains else None
            ),
        )

        return entries

    def get_entries_as_dict(
        self,
        domain: str | None = None,
        service_type: ServiceType | None = None,
        status: ServiceStatus | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve catalog entries as dictionaries.

        Convenient for JSON serialization or LLM consumption.

        Args:
            domain: Optional domain filter
            service_type: Optional service type filter
            status: Optional status filter

        Returns:
            List of catalog entries as dictionaries

        Examples:
            >>> entries_dict = tool.get_entries_as_dict(domain="performance")
            >>> entries_dict[0]["service_id"]
            'perf_analyzer'
        """
        entries = self.get_entries(
            domain=domain, service_type=service_type, status=status
        )
        return [entry.to_dict() for entry in entries]

    def get_domains(self) -> list[str]:
        """Get unique list of all domains in the catalog (excluding disabled).

        Returns:
            Sorted list of unique domain names (disabled domains excluded)

        Examples:
            >>> domains = tool.get_domains()
            >>> domains
            ['finops', 'governance', 'performance', 'query']
        """
        entries = self._filter_disabled(self.registry.list_all())
        domains = {entry.domain for entry in entries}
        return sorted(domains)

    async def get_entries_cached(
        self,
        domain: str | None = None,
        service_type: ServiceType | None = None,
        status: ServiceStatus | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve catalog entries with caching (async).

        Uses cache if enabled, otherwise falls back to direct lookup.

        Args:
            domain: Optional domain filter
            service_type: Optional service type filter
            status: Optional status filter

        Returns:
            List of catalog entries as dictionaries

        Examples:
            >>> entries = await tool.get_entries_cached(domain="performance")
            >>> # Second call hits cache
            >>> entries_again = await tool.get_entries_cached(domain="performance")
        """
        if not self.cache:
            # No cache, direct lookup
            return self.get_entries_as_dict(
                domain=domain, service_type=service_type, status=status
            )

        # Generate cache key
        cache_key = self.cache.generate_key(
            domain=domain,
            service_type=service_type.value if service_type else None,
            status=status.value if status else None,
        )

        # Try cache first (async)
        cached_result = await self.cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        # Cache miss - fetch and cache
        result = self.get_entries_as_dict(
            domain=domain, service_type=service_type, status=status
        )
        await self.cache.set(cache_key, result)

        return result
