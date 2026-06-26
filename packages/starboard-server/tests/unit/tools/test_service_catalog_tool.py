# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for ServiceCatalogTool.

Tests catalog registration, lookup, and filtering functionality.
Following TDD: write tests first, then implement.

Part of Phase 9: Service Catalog & Next-Step Suggestions
"""

# These imports will fail initially - that's expected in TDD
from starboard_server.domain.models.service_catalog import (
    ServiceCatalogEntry,
    ServiceStatus,
    ServiceType,
)
from starboard_server.tools.service_catalog_tool import (
    CatalogRegistry,
    ServiceCatalogTool,
)


class TestCatalogRegistry:
    """Test CatalogRegistry data structure."""

    def test_create_empty_registry(self):
        """Test creating an empty catalog registry."""
        registry = CatalogRegistry()

        assert registry.size() == 0
        assert registry.list_all() == []

    def test_register_single_entry(self):
        """Test registering a single catalog entry."""
        registry = CatalogRegistry()

        entry = ServiceCatalogEntry(
            service_id="test_service",
            service_type=ServiceType.AGENT,
            name="Test Service",
            domain="test",
            description="Test description",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        registry.register(entry)

        assert registry.size() == 1
        assert registry.get("test_service") == entry

    def test_register_multiple_entries(self):
        """Test registering multiple catalog entries."""
        registry = CatalogRegistry()

        entries = [
            ServiceCatalogEntry(
                service_id=f"service_{i}",
                service_type=ServiceType.AGENT,
                name=f"Service {i}",
                domain="test",
                description="Test",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            )
            for i in range(5)
        ]

        for entry in entries:
            registry.register(entry)

        assert registry.size() == 5
        assert len(registry.list_all()) == 5

    def test_register_duplicate_service_id_replaces(self):
        """Test that registering same service_id replaces the entry."""
        registry = CatalogRegistry()

        entry_v1 = ServiceCatalogEntry(
            service_id="test_service",
            service_type=ServiceType.AGENT,
            name="Test Service V1",
            domain="test",
            description="Version 1",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        entry_v2 = ServiceCatalogEntry(
            service_id="test_service",  # Same service_id
            service_type=ServiceType.AGENT,
            name="Test Service V2",
            domain="test",
            description="Version 2",
            capabilities=(),
            version="2.0.0",
            status=ServiceStatus.ACTIVE,
        )

        registry.register(entry_v1)
        assert registry.get("test_service").name == "Test Service V1"

        registry.register(entry_v2)
        assert registry.size() == 1  # Still 1 entry
        assert registry.get("test_service").name == "Test Service V2"

    def test_get_nonexistent_service_returns_none(self):
        """Test that getting non-existent service returns None."""
        registry = CatalogRegistry()

        result = registry.get("nonexistent_service")

        assert result is None

    def test_list_all_returns_copy(self):
        """Test that list_all returns a copy, not internal state."""
        registry = CatalogRegistry()

        entry = ServiceCatalogEntry(
            service_id="test_service",
            service_type=ServiceType.AGENT,
            name="Test",
            domain="test",
            description="Test",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        registry.register(entry)
        entries_list = registry.list_all()

        # Modifying the list shouldn't affect the registry
        entries_list.clear()

        assert registry.size() == 1

    def test_filter_by_domain(self):
        """Test filtering entries by domain."""
        registry = CatalogRegistry()

        performance_entry = ServiceCatalogEntry(
            service_id="perf_agent",
            service_type=ServiceType.AGENT,
            name="Performance Agent",
            domain="performance",
            description="Perf analysis",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        finops_entry = ServiceCatalogEntry(
            service_id="finops_agent",
            service_type=ServiceType.AGENT,
            name="FinOps Agent",
            domain="finops",
            description="Cost analysis",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        registry.register(performance_entry)
        registry.register(finops_entry)

        perf_results = registry.filter_by_domain("performance")
        finops_results = registry.filter_by_domain("finops")

        assert len(perf_results) == 1
        assert perf_results[0].service_id == "perf_agent"
        assert len(finops_results) == 1
        assert finops_results[0].service_id == "finops_agent"

    def test_filter_by_service_type(self):
        """Test filtering entries by service type."""
        registry = CatalogRegistry()

        agent_entry = ServiceCatalogEntry(
            service_id="test_agent",
            service_type=ServiceType.AGENT,
            name="Test Agent",
            domain="test",
            description="Test",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        tool_entry = ServiceCatalogEntry(
            service_id="test_tool",
            service_type=ServiceType.TOOL,
            name="Test Tool",
            domain="test",
            description="Test",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        registry.register(agent_entry)
        registry.register(tool_entry)

        agent_results = registry.filter_by_type(ServiceType.AGENT)
        tool_results = registry.filter_by_type(ServiceType.TOOL)

        assert len(agent_results) == 1
        assert agent_results[0].service_type == ServiceType.AGENT
        assert len(tool_results) == 1
        assert tool_results[0].service_type == ServiceType.TOOL

    def test_filter_by_status(self):
        """Test filtering entries by status."""
        registry = CatalogRegistry()

        active_entry = ServiceCatalogEntry(
            service_id="active_service",
            service_type=ServiceType.AGENT,
            name="Active Service",
            domain="test",
            description="Test",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        beta_entry = ServiceCatalogEntry(
            service_id="beta_service",
            service_type=ServiceType.AGENT,
            name="Beta Service",
            domain="test",
            description="Test",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.BETA,
        )

        registry.register(active_entry)
        registry.register(beta_entry)

        active_results = registry.filter_by_status(ServiceStatus.ACTIVE)
        beta_results = registry.filter_by_status(ServiceStatus.BETA)

        assert len(active_results) == 1
        assert active_results[0].status == ServiceStatus.ACTIVE
        assert len(beta_results) == 1
        assert beta_results[0].status == ServiceStatus.BETA

    def test_combined_filters(self):
        """Test applying multiple filters together."""
        registry = CatalogRegistry()

        # Register multiple entries with different attributes
        entries = [
            ServiceCatalogEntry(
                service_id="perf_agent_active",
                service_type=ServiceType.AGENT,
                name="Performance Agent",
                domain="performance",
                description="Active perf agent",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            ),
            ServiceCatalogEntry(
                service_id="perf_agent_beta",
                service_type=ServiceType.AGENT,
                name="Performance Agent Beta",
                domain="performance",
                description="Beta perf agent",
                capabilities=(),
                version="2.0.0",
                status=ServiceStatus.BETA,
            ),
            ServiceCatalogEntry(
                service_id="finops_tool",
                service_type=ServiceType.TOOL,
                name="FinOps Tool",
                domain="finops",
                description="Cost tool",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            ),
        ]

        for entry in entries:
            registry.register(entry)

        # Filter by domain AND status
        perf_active = [
            e
            for e in registry.filter_by_domain("performance")
            if e.status == ServiceStatus.ACTIVE
        ]

        assert len(perf_active) == 1
        assert perf_active[0].service_id == "perf_agent_active"


class TestServiceCatalogTool:
    """Test ServiceCatalogTool class."""

    def test_create_tool_with_empty_registry(self):
        """Test creating tool with no registered services."""
        tool = ServiceCatalogTool()

        assert tool.registry.size() == 0

    def test_create_tool_with_initial_entries(self):
        """Test creating tool with initial catalog entries."""
        entry = ServiceCatalogEntry(
            service_id="test_service",
            service_type=ServiceType.AGENT,
            name="Test",
            domain="test",
            description="Test",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        tool = ServiceCatalogTool(initial_entries=[entry])

        assert tool.registry.size() == 1

    def test_get_catalog_entry_by_id(self):
        """Test retrieving a catalog entry by service_id."""
        entry = ServiceCatalogEntry(
            service_id="test_service",
            service_type=ServiceType.AGENT,
            name="Test Service",
            domain="test",
            description="Test",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        tool = ServiceCatalogTool(initial_entries=[entry])
        result = tool.get_entry("test_service")

        assert result is not None
        assert result.service_id == "test_service"
        assert result.name == "Test Service"

    def test_get_catalog_entry_nonexistent_returns_none(self):
        """Test that getting non-existent entry returns None."""
        tool = ServiceCatalogTool()

        result = tool.get_entry("nonexistent")

        assert result is None

    def test_get_all_entries(self):
        """Test retrieving all catalog entries."""
        entries = [
            ServiceCatalogEntry(
                service_id=f"service_{i}",
                service_type=ServiceType.AGENT,
                name=f"Service {i}",
                domain="test",
                description="Test",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            )
            for i in range(3)
        ]

        tool = ServiceCatalogTool(initial_entries=entries)
        all_entries = tool.get_all_entries()

        assert len(all_entries) == 3

    def test_get_entries_with_domain_scope(self):
        """Test retrieving entries filtered by domain scope."""
        entries = [
            ServiceCatalogEntry(
                service_id="perf_agent",
                service_type=ServiceType.AGENT,
                name="Performance Agent",
                domain="performance",
                description="Perf",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            ),
            ServiceCatalogEntry(
                service_id="finops_agent",
                service_type=ServiceType.AGENT,
                name="FinOps Agent",
                domain="finops",
                description="Cost",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            ),
        ]

        tool = ServiceCatalogTool(initial_entries=entries)
        perf_entries = tool.get_entries(domain="performance")

        assert len(perf_entries) == 1
        assert perf_entries[0].domain == "performance"

    def test_get_entries_with_type_filter(self):
        """Test retrieving entries filtered by service type."""
        entries = [
            ServiceCatalogEntry(
                service_id="test_agent",
                service_type=ServiceType.AGENT,
                name="Agent",
                domain="test",
                description="Test",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            ),
            ServiceCatalogEntry(
                service_id="test_tool",
                service_type=ServiceType.TOOL,
                name="Tool",
                domain="test",
                description="Test",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            ),
        ]

        tool = ServiceCatalogTool(initial_entries=entries)
        agent_entries = tool.get_entries(service_type=ServiceType.AGENT)

        assert len(agent_entries) == 1
        assert agent_entries[0].service_type == ServiceType.AGENT

    def test_get_entries_with_status_filter(self):
        """Test retrieving entries filtered by status."""
        entries = [
            ServiceCatalogEntry(
                service_id="active_service",
                service_type=ServiceType.AGENT,
                name="Active",
                domain="test",
                description="Test",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            ),
            ServiceCatalogEntry(
                service_id="beta_service",
                service_type=ServiceType.AGENT,
                name="Beta",
                domain="test",
                description="Test",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.BETA,
            ),
        ]

        tool = ServiceCatalogTool(initial_entries=entries)
        active_entries = tool.get_entries(status=ServiceStatus.ACTIVE)

        assert len(active_entries) == 1
        assert active_entries[0].status == ServiceStatus.ACTIVE

    def test_get_entries_with_multiple_filters(self):
        """Test retrieving entries with combined filters."""
        entries = [
            ServiceCatalogEntry(
                service_id="perf_agent",
                service_type=ServiceType.AGENT,
                name="Performance Agent",
                domain="performance",
                description="Active perf agent",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            ),
            ServiceCatalogEntry(
                service_id="perf_beta",
                service_type=ServiceType.AGENT,
                name="Performance Beta",
                domain="performance",
                description="Beta perf agent",
                capabilities=(),
                version="2.0.0",
                status=ServiceStatus.BETA,
            ),
            ServiceCatalogEntry(
                service_id="finops_agent",
                service_type=ServiceType.AGENT,
                name="FinOps Agent",
                domain="finops",
                description="Cost agent",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            ),
        ]

        tool = ServiceCatalogTool(initial_entries=entries)

        # Filter: domain=performance AND status=ACTIVE
        results = tool.get_entries(domain="performance", status=ServiceStatus.ACTIVE)

        assert len(results) == 1
        assert results[0].service_id == "perf_agent"

    def test_register_new_entry(self):
        """Test registering a new entry after tool creation."""
        tool = ServiceCatalogTool()

        assert tool.registry.size() == 0

        entry = ServiceCatalogEntry(
            service_id="new_service",
            service_type=ServiceType.AGENT,
            name="New Service",
            domain="test",
            description="Test",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        tool.register_entry(entry)

        assert tool.registry.size() == 1
        assert tool.get_entry("new_service") is not None

    def test_to_dict_format(self):
        """Test converting catalog entries to dict format."""
        entry = ServiceCatalogEntry(
            service_id="test_service",
            service_type=ServiceType.AGENT,
            name="Test Service",
            domain="test",
            description="Test description",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        tool = ServiceCatalogTool(initial_entries=[entry])
        entries_dict = tool.get_entries_as_dict()

        assert isinstance(entries_dict, list)
        assert len(entries_dict) == 1
        assert entries_dict[0]["service_id"] == "test_service"
        assert entries_dict[0]["service_type"] == "agent"

    def test_get_domains_list(self):
        """Test getting unique list of domains."""
        entries = [
            ServiceCatalogEntry(
                service_id=f"perf_{i}",
                service_type=ServiceType.AGENT,
                name=f"Perf {i}",
                domain="performance",
                description="Test",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            )
            for i in range(2)
        ] + [
            ServiceCatalogEntry(
                service_id="finops_agent",
                service_type=ServiceType.AGENT,
                name="FinOps",
                domain="finops",
                description="Test",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            )
        ]

        tool = ServiceCatalogTool(initial_entries=entries)
        domains = tool.get_domains()

        assert len(domains) == 2
        assert "performance" in domains
        assert "finops" in domains


class TestServiceCatalogToolDisabledDomains:
    """Tests for disabled_domains filtering (DISABLED_AGENT_DOMAINS support)."""

    def test_disabled_domains_filters_get_all_entries(self):
        """Disabled domains should be filtered from get_all_entries."""
        entries = [
            ServiceCatalogEntry(
                service_id="query_agent",
                service_type=ServiceType.AGENT,
                name="Query Agent",
                domain="query",
                description="Query analysis",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            ),
            ServiceCatalogEntry(
                service_id="diagnostic_agent",
                service_type=ServiceType.AGENT,
                name="Diagnostic Agent",
                domain="diagnostic",
                description="Diagnostics",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            ),
        ]

        tool = ServiceCatalogTool(
            initial_entries=entries,
            disabled_domains=["diagnostic"],
        )

        # Registry has both entries
        assert tool.registry.size() == 2

        # But get_all_entries only returns non-disabled
        result = tool.get_all_entries()
        assert len(result) == 1
        assert result[0].service_id == "query_agent"

    def test_disabled_domains_filters_get_entries(self):
        """Disabled domains should be filtered from get_entries."""
        entries = [
            ServiceCatalogEntry(
                service_id="uc_agent",
                service_type=ServiceType.AGENT,
                name="UC Agent",
                domain="uc",
                description="Unity Catalog",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            ),
            ServiceCatalogEntry(
                service_id="compute_agent",
                service_type=ServiceType.AGENT,
                name="Compute Agent",
                domain="cluster",
                description="Compute management",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            ),
        ]

        tool = ServiceCatalogTool(
            initial_entries=entries,
            disabled_domains=["uc", "cluster"],
        )

        # Even when filtering by disabled domain, returns empty
        result = tool.get_entries(domain="uc")
        assert len(result) == 0

        # All entries filtered
        result = tool.get_entries()
        assert len(result) == 0

    def test_disabled_domains_filters_get_domains(self):
        """Disabled domains should be excluded from get_domains."""
        entries = [
            ServiceCatalogEntry(
                service_id="job_agent",
                service_type=ServiceType.AGENT,
                name="Job Agent",
                domain="job",
                description="Job analysis",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            ),
            ServiceCatalogEntry(
                service_id="analytics_agent",
                service_type=ServiceType.AGENT,
                name="Analytics Agent",
                domain="analytics",
                description="Analytics",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            ),
        ]

        tool = ServiceCatalogTool(
            initial_entries=entries,
            disabled_domains=["analytics"],
        )

        domains = tool.get_domains()
        assert domains == ["job"]
        assert "analytics" not in domains

    def test_disabled_domains_property(self):
        """Should expose disabled_domains as a frozenset property."""
        tool = ServiceCatalogTool(disabled_domains=["diagnostic", "cluster"])

        assert tool.disabled_domains == frozenset({"diagnostic", "cluster"})

    def test_empty_disabled_domains(self):
        """Empty disabled_domains should not filter anything."""
        entry = ServiceCatalogEntry(
            service_id="test_agent",
            service_type=ServiceType.AGENT,
            name="Test Agent",
            domain="test",
            description="Test",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        tool = ServiceCatalogTool(
            initial_entries=[entry],
            disabled_domains=[],  # Empty list
        )

        assert len(tool.get_all_entries()) == 1

    def test_none_disabled_domains(self):
        """None disabled_domains should not filter anything."""
        entry = ServiceCatalogEntry(
            service_id="test_agent",
            service_type=ServiceType.AGENT,
            name="Test Agent",
            domain="test",
            description="Test",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        tool = ServiceCatalogTool(
            initial_entries=[entry],
            disabled_domains=None,  # None
        )

        assert len(tool.get_all_entries()) == 1

    def test_get_entry_not_filtered(self):
        """get_entry should still return entry even if domain is disabled.

        Direct lookup by ID should work - filtering applies to list operations.
        """
        entry = ServiceCatalogEntry(
            service_id="disabled_agent",
            service_type=ServiceType.AGENT,
            name="Disabled Agent",
            domain="disabled_domain",
            description="Test",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        tool = ServiceCatalogTool(
            initial_entries=[entry],
            disabled_domains=["disabled_domain"],
        )

        # Direct lookup still works
        result = tool.get_entry("disabled_agent")
        assert result is not None
        assert result.service_id == "disabled_agent"
