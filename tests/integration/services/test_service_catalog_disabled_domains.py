# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Integration tests for service catalog disabled domains filtering.

Verifies that DISABLED_AGENT_DOMAINS configuration is respected throughout
the service catalog and next-step generation pipeline.

Part of Phase 9: Service Catalog & Next-Step Suggestions
"""

import pytest
from starboard_server.domain.models.agent_output import (
    DomainAgentOutput,
    InDomainNextStep,
)
from starboard_server.domain.models.conversation_patterns import ActionType
from starboard_server.domain.models.handoff_recommendation import (
    HandoffConfidence,
    HandoffRecommendation,
)
from starboard_server.domain.models.service_catalog import (
    ServiceCatalogEntry,
    ServiceStatus,
    ServiceType,
)
from starboard_server.services.coordination.next_step_generator import NextStepGenerator
from starboard_server.tools.service_catalog_tool import ServiceCatalogTool


class TestDisabledDomainsIntegration:
    """Integration tests for disabled domains filtering through the pipeline."""

    @pytest.fixture
    def sample_entries(self) -> list[ServiceCatalogEntry]:
        """Create sample catalog entries for testing."""
        return [
            ServiceCatalogEntry(
                service_id="query_optimizer",
                service_type=ServiceType.AGENT,
                name="Query Optimizer",
                domain="query",
                description="Query analysis",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            ),
            ServiceCatalogEntry(
                service_id="compute_manager",
                service_type=ServiceType.AGENT,
                name="Compute Manager",
                domain="compute",
                description="Compute management",
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
            ServiceCatalogEntry(
                service_id="warehouse_agent",
                service_type=ServiceType.AGENT,
                name="Warehouse Agent",
                domain="warehouse",
                description="Warehouse optimization",
                capabilities=(),
                version="1.0.0",
                status=ServiceStatus.ACTIVE,
            ),
        ]

    @pytest.mark.asyncio
    async def test_disabled_domains_not_in_next_steps(
        self, sample_entries: list[ServiceCatalogEntry]
    ) -> None:
        """Test that disabled domains don't appear in next step suggestions."""
        # Setup catalog with compute disabled
        catalog = ServiceCatalogTool(
            initial_entries=sample_entries,
            disabled_domains=["compute"],
        )
        generator = NextStepGenerator(catalog)

        # Create output with handoff to disabled compute domain
        output = DomainAgentOutput(
            primary_answer="Query analysis complete.",
            in_domain_next_steps=(),
            handoff_recommendations=(
                HandoffRecommendation(
                    target_domain="compute",
                    confidence=HandoffConfidence.HIGH,
                    reason="Could optimize cluster config",
                ),
                HandoffRecommendation(
                    target_domain="diagnostic",
                    confidence=HandoffConfidence.MEDIUM,
                    reason="Run additional diagnostics",
                ),
            ),
            metadata={},
        )

        # Generate next steps
        options = await generator.generate_next_steps(
            output, current_agent="query_optimizer"
        )

        # Extract target agents from options
        target_agents = [
            opt.target_agent for opt in options if opt.target_agent is not None
        ]

        # Compute should NOT appear (disabled)
        assert "compute_manager" not in target_agents

        # Diagnostic should appear (not disabled)
        assert "diagnostic_agent" in target_agents

    @pytest.mark.asyncio
    async def test_multiple_disabled_domains(
        self, sample_entries: list[ServiceCatalogEntry]
    ) -> None:
        """Test that multiple disabled domains are all filtered."""
        # Setup catalog with compute and diagnostic disabled
        catalog = ServiceCatalogTool(
            initial_entries=sample_entries,
            disabled_domains=["compute", "diagnostic"],
        )
        generator = NextStepGenerator(catalog)

        # Create output with handoffs to both disabled domains
        output = DomainAgentOutput(
            primary_answer="Analysis complete.",
            in_domain_next_steps=(),
            handoff_recommendations=(
                HandoffRecommendation(
                    target_domain="compute",
                    confidence=HandoffConfidence.HIGH,
                    reason="Optimize cluster",
                ),
                HandoffRecommendation(
                    target_domain="diagnostic",
                    confidence=HandoffConfidence.HIGH,
                    reason="Run diagnostics",
                ),
            ),
            metadata={},
        )

        # Generate next steps
        options = await generator.generate_next_steps(
            output, current_agent="query_optimizer"
        )

        # Extract handoff-related options (exclude in-domain next steps)
        handoff_options = [opt for opt in options if opt.target_agent is not None]

        # Both disabled domains should be filtered out
        assert len(handoff_options) == 0

    @pytest.mark.asyncio
    async def test_in_domain_steps_unaffected_by_disabled_domains(
        self, sample_entries: list[ServiceCatalogEntry]
    ) -> None:
        """Test that in-domain next steps are not affected by disabled domains."""
        catalog = ServiceCatalogTool(
            initial_entries=sample_entries,
            disabled_domains=["compute", "diagnostic"],
        )
        generator = NextStepGenerator(catalog)

        # Create output with in-domain steps (should not be filtered)
        output = DomainAgentOutput(
            primary_answer="Query analyzed.",
            in_domain_next_steps=(
                InDomainNextStep(
                    id="optimize_query",
                    title="Optimize Query",
                    description="Rewrite query for better performance",
                    suggested_prompt="Optimize my query",
                ),
            ),
            handoff_recommendations=(),
            metadata={},
        )

        # Generate next steps
        options = await generator.generate_next_steps(
            output, current_agent="query_optimizer"
        )

        # In-domain step should still appear
        assert len(options) == 1
        assert options[0].title == "Optimize Query"
        assert options[0].action_type == ActionType.CONTINUE

    @pytest.mark.asyncio
    async def test_catalog_get_domains_respects_disabled(
        self, sample_entries: list[ServiceCatalogEntry]
    ) -> None:
        """Test that get_domains() excludes disabled domains."""
        catalog = ServiceCatalogTool(
            initial_entries=sample_entries,
            disabled_domains=["compute"],
        )

        domains = catalog.get_domains()

        assert "compute" not in domains
        assert "query" in domains
        assert "diagnostic" in domains
        assert "warehouse" in domains

    @pytest.mark.asyncio
    async def test_catalog_get_entries_respects_disabled(
        self, sample_entries: list[ServiceCatalogEntry]
    ) -> None:
        """Test that get_entries() excludes disabled domains."""
        catalog = ServiceCatalogTool(
            initial_entries=sample_entries,
            disabled_domains=["compute", "warehouse"],
        )

        # Get all entries
        all_entries = catalog.get_all_entries()
        domains = {e.domain for e in all_entries}

        assert "compute" not in domains
        assert "warehouse" not in domains
        assert "query" in domains
        assert "diagnostic" in domains

    @pytest.mark.asyncio
    async def test_mixed_enabled_disabled_handoffs(
        self, sample_entries: list[ServiceCatalogEntry]
    ) -> None:
        """Test handoffs with mix of enabled and disabled target domains."""
        catalog = ServiceCatalogTool(
            initial_entries=sample_entries,
            disabled_domains=["compute"],
        )
        generator = NextStepGenerator(catalog)

        # Create output with handoffs to both enabled and disabled domains
        output = DomainAgentOutput(
            primary_answer="Analysis complete.",
            in_domain_next_steps=(),
            handoff_recommendations=(
                HandoffRecommendation(
                    target_domain="compute",  # Disabled
                    confidence=HandoffConfidence.HIGH,
                    reason="Optimize cluster",
                ),
                HandoffRecommendation(
                    target_domain="diagnostic",  # Enabled
                    confidence=HandoffConfidence.HIGH,
                    reason="Run diagnostics",
                ),
                HandoffRecommendation(
                    target_domain="warehouse",  # Enabled
                    confidence=HandoffConfidence.MEDIUM,
                    reason="Optimize warehouses",
                ),
            ),
            metadata={},
        )

        # Generate next steps
        options = await generator.generate_next_steps(
            output, current_agent="query_optimizer"
        )

        # Extract target agents
        target_agents = [
            opt.target_agent for opt in options if opt.target_agent is not None
        ]

        # Only enabled domains should appear
        assert len(target_agents) == 2
        assert "compute_manager" not in target_agents
        assert "diagnostic_agent" in target_agents
        assert "warehouse_agent" in target_agents

    @pytest.mark.asyncio
    async def test_disabled_domains_property_is_frozen(
        self, sample_entries: list[ServiceCatalogEntry]
    ) -> None:
        """Test that disabled_domains property returns an immutable frozenset."""
        catalog = ServiceCatalogTool(
            initial_entries=sample_entries,
            disabled_domains=["compute", "diagnostic"],
        )

        disabled = catalog.disabled_domains

        assert isinstance(disabled, frozenset)
        assert disabled == frozenset({"compute", "diagnostic"})
