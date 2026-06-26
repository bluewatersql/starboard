# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for NextStepGenerator service.

Tests generation of NextStepOptions from domain agent output and catalog.
Part of Phase 9: Service Catalog & Next-Step Suggestions
"""

# These imports will fail initially - that's expected in TDD
from starboard_server.domain.models.agent_output import (
    DomainAgentOutput,
    InDomainNextStep,
)
from starboard_server.domain.models.conversation_patterns import (
    ActionType,
)
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


class TestNextStepGenerator:
    """Test NextStepGenerator service."""

    async def test_generate_from_in_domain_steps_only(self):
        """Test generating options when only in-domain steps present."""
        # Setup
        domain_output = DomainAgentOutput(
            primary_answer="Query analyzed.",
            in_domain_next_steps=(
                InDomainNextStep(
                    id="add_index",
                    title="Add Missing Index",
                    description="Create index on customer_id",
                    suggested_prompt="Add index to customer_id",
                ),
                InDomainNextStep(
                    id="optimize_query",
                    title="Optimize Query",
                    description="Rewrite query for better performance",
                    suggested_prompt="Optimize my query",
                ),
            ),
            handoff_recommendations=None,
            metadata={},
        )

        catalog = ServiceCatalogTool()
        generator = NextStepGenerator(catalog)

        # Execute
        options = await generator.generate_next_steps(
            domain_output, current_agent="query_optimizer"
        )

        # Assert
        assert len(options) == 2
        assert options[0].number == 1
        assert options[0].title == "Add Missing Index"
        assert options[0].action_type == ActionType.CONTINUE
        assert options[0].target_agent is None
        assert options[1].number == 2
        assert options[1].action_type == ActionType.CONTINUE

    async def test_generate_from_handoffs_only(self):
        """Test generating options when only handoff recommendations present."""
        # Setup
        perf_agent = ServiceCatalogEntry(
            service_id="perf_analyzer",
            service_type=ServiceType.AGENT,
            name="Performance Analyzer",
            domain="performance",
            description="Analyzes Spark performance",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        catalog = ServiceCatalogTool(initial_entries=[perf_agent])

        domain_output = DomainAgentOutput(
            primary_answer="Query analyzed.",
            in_domain_next_steps=(),
            handoff_recommendations=(
                HandoffRecommendation(
                    target_domain="performance",
                    confidence=HandoffConfidence.HIGH,
                    reason="Deep performance analysis recommended",
                ),
            ),
            metadata={},
        )

        generator = NextStepGenerator(catalog)

        # Execute
        options = await generator.generate_next_steps(
            domain_output, current_agent="query_optimizer"
        )

        # Assert
        assert len(options) == 1
        assert options[0].number == 1
        assert options[0].action_type == ActionType.ROUTE
        assert options[0].target_agent == "perf_analyzer"
        assert "Performance Analyzer" in options[0].title

    async def test_generate_combines_both_sources(self):
        """Test generating options from both in-domain and handoffs."""
        # Setup
        perf_agent = ServiceCatalogEntry(
            service_id="perf_analyzer",
            service_type=ServiceType.AGENT,
            name="Performance Analyzer",
            domain="performance",
            description="Performance analysis",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        catalog = ServiceCatalogTool(initial_entries=[perf_agent])

        domain_output = DomainAgentOutput(
            primary_answer="Analysis complete.",
            in_domain_next_steps=(
                InDomainNextStep(
                    id="continue",
                    title="Continue in Current Domain",
                    description="Keep working here",
                    suggested_prompt="Continue",
                ),
            ),
            handoff_recommendations=(
                HandoffRecommendation(
                    target_domain="performance",
                    confidence=HandoffConfidence.HIGH,
                    reason="Performance analysis needed",
                ),
            ),
            metadata={},
        )

        generator = NextStepGenerator(catalog)

        # Execute
        options = await generator.generate_next_steps(
            domain_output, current_agent="query_optimizer"
        )

        # Assert
        assert len(options) == 2
        # In-domain first
        assert options[0].action_type == ActionType.CONTINUE
        # Cross-domain second
        assert options[1].action_type == ActionType.ROUTE
        assert options[1].target_agent == "perf_analyzer"

    async def test_prioritizes_in_domain_before_cross_domain(self):
        """Test that in-domain steps come before cross-domain."""
        # Setup with multiple of each
        perf_agent = ServiceCatalogEntry(
            service_id="perf_analyzer",
            service_type=ServiceType.AGENT,
            name="Performance Analyzer",
            domain="performance",
            description="Performance",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        catalog = ServiceCatalogTool(initial_entries=[perf_agent])

        domain_output = DomainAgentOutput(
            primary_answer="Analysis.",
            in_domain_next_steps=(
                InDomainNextStep(
                    id="step1", title="Step 1", description="", suggested_prompt=""
                ),
                InDomainNextStep(
                    id="step2", title="Step 2", description="", suggested_prompt=""
                ),
            ),
            handoff_recommendations=(
                HandoffRecommendation(
                    target_domain="performance",
                    confidence=HandoffConfidence.HIGH,
                    reason="Performance analysis",
                ),
            ),
            metadata={},
        )

        generator = NextStepGenerator(catalog)

        # Execute
        options = await generator.generate_next_steps(
            domain_output, current_agent="query_optimizer"
        )

        # Assert
        assert options[0].action_type == ActionType.CONTINUE
        assert options[1].action_type == ActionType.CONTINUE
        assert options[2].action_type == ActionType.ROUTE

    async def test_sorts_handoffs_by_confidence(self):
        """Test that handoffs are sorted HIGH → MEDIUM → LOW."""
        # Setup
        perf_agent = ServiceCatalogEntry(
            service_id="perf_analyzer",
            service_type=ServiceType.AGENT,
            name="Performance Analyzer",
            domain="performance",
            description="Performance",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        finops_agent = ServiceCatalogEntry(
            service_id="finops_analyzer",
            service_type=ServiceType.AGENT,
            name="FinOps Analyzer",
            domain="finops",
            description="Cost analysis",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        gov_agent = ServiceCatalogEntry(
            service_id="governance_manager",
            service_type=ServiceType.AGENT,
            name="Governance Manager",
            domain="governance",
            description="Governance",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        catalog = ServiceCatalogTool(
            initial_entries=[perf_agent, finops_agent, gov_agent]
        )

        domain_output = DomainAgentOutput(
            primary_answer="Analysis.",
            in_domain_next_steps=(),
            handoff_recommendations=(
                HandoffRecommendation(
                    target_domain="governance",
                    confidence=HandoffConfidence.LOW,
                    reason="Optional governance check",
                ),
                HandoffRecommendation(
                    target_domain="performance",
                    confidence=HandoffConfidence.HIGH,
                    reason="Critical performance issue",
                ),
                HandoffRecommendation(
                    target_domain="finops",
                    confidence=HandoffConfidence.MEDIUM,
                    reason="Cost optimization opportunity",
                ),
            ),
            metadata={},
        )

        generator = NextStepGenerator(catalog)

        # Execute
        options = await generator.generate_next_steps(
            domain_output, current_agent="query_optimizer"
        )

        # Assert - should be sorted by confidence
        assert options[0].target_agent == "perf_analyzer"  # HIGH
        assert options[1].target_agent == "finops_analyzer"  # MEDIUM
        assert options[2].target_agent == "governance_manager"  # LOW

    async def test_limits_to_9_total_options(self):
        """Test that total options are limited to 9."""
        # Setup with more than 9 steps
        in_domain_steps = tuple(
            InDomainNextStep(
                id=f"step{i}",
                title=f"Step {i}",
                description="",
                suggested_prompt="",
            )
            for i in range(6)
        )

        perf_agent = ServiceCatalogEntry(
            service_id="perf_analyzer",
            service_type=ServiceType.AGENT,
            name="Performance Analyzer",
            domain="performance",
            description="Performance",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        finops_agent = ServiceCatalogEntry(
            service_id="finops_analyzer",
            service_type=ServiceType.AGENT,
            name="FinOps Analyzer",
            domain="finops",
            description="Cost",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        gov_agent = ServiceCatalogEntry(
            service_id="governance_manager",
            service_type=ServiceType.AGENT,
            name="Governance Manager",
            domain="governance",
            description="Governance",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        catalog = ServiceCatalogTool(
            initial_entries=[perf_agent, finops_agent, gov_agent]
        )

        handoff_recommendations = tuple(
            HandoffRecommendation(
                target_domain=domain,
                confidence=HandoffConfidence.HIGH,
                reason=f"Handoff to {domain}",
            )
            for domain in ["performance", "finops", "governance", "security"]
        )

        domain_output = DomainAgentOutput(
            primary_answer="Analysis.",
            in_domain_next_steps=in_domain_steps,
            handoff_recommendations=handoff_recommendations,
            metadata={},
        )

        generator = NextStepGenerator(catalog)

        # Execute
        options = await generator.generate_next_steps(
            domain_output, current_agent="query_optimizer"
        )

        # Assert - should be limited to 9
        assert len(options) <= 9
        # Numbers should be 1-9
        assert options[0].number == 1
        assert options[-1].number == len(options)

    async def test_handles_missing_catalog_entry_gracefully(self):
        """Test that missing catalog entries are skipped."""
        # Setup with handoff to non-existent domain
        catalog = ServiceCatalogTool()  # Empty catalog

        domain_output = DomainAgentOutput(
            primary_answer="Analysis.",
            in_domain_next_steps=(
                InDomainNextStep(
                    id="step1",
                    title="In-Domain Step",
                    description="",
                    suggested_prompt="",
                ),
            ),
            handoff_recommendations=(
                HandoffRecommendation(
                    target_domain="nonexistent_domain",
                    confidence=HandoffConfidence.HIGH,
                    reason="Handoff to missing domain",
                ),
            ),
            metadata={},
        )

        generator = NextStepGenerator(catalog)

        # Execute
        options = await generator.generate_next_steps(
            domain_output, current_agent="query_optimizer"
        )

        # Assert - should only have in-domain step (handoff skipped)
        assert len(options) == 1
        assert options[0].action_type == ActionType.CONTINUE

    async def test_option_numbering_sequential(self):
        """Test that option numbers are sequential 1, 2, 3, ..."""
        # Setup
        domain_output = DomainAgentOutput(
            primary_answer="Analysis.",
            in_domain_next_steps=(
                InDomainNextStep(
                    id="s1", title="Step 1", description="", suggested_prompt=""
                ),
                InDomainNextStep(
                    id="s2", title="Step 2", description="", suggested_prompt=""
                ),
                InDomainNextStep(
                    id="s3", title="Step 3", description="", suggested_prompt=""
                ),
            ),
            handoff_recommendations=None,
            metadata={},
        )

        catalog = ServiceCatalogTool()
        generator = NextStepGenerator(catalog)

        # Execute
        options = await generator.generate_next_steps(
            domain_output, current_agent="query_optimizer"
        )

        # Assert
        assert options[0].number == 1
        assert options[1].number == 2
        assert options[2].number == 3

    async def test_includes_reason_in_handoff_description(self):
        """Test that handoff reason is included in option description."""
        # Setup
        perf_agent = ServiceCatalogEntry(
            service_id="perf_analyzer",
            service_type=ServiceType.AGENT,
            name="Performance Analyzer",
            domain="performance",
            description="Performance analysis",
            capabilities=(),
            version="1.0.0",
            status=ServiceStatus.ACTIVE,
        )

        catalog = ServiceCatalogTool(initial_entries=[perf_agent])

        domain_output = DomainAgentOutput(
            primary_answer="Analysis.",
            in_domain_next_steps=(),
            handoff_recommendations=(
                HandoffRecommendation(
                    target_domain="performance",
                    confidence=HandoffConfidence.HIGH,
                    reason="Query execution time exceeds 30 seconds",
                ),
            ),
            metadata={},
        )

        generator = NextStepGenerator(catalog)

        # Execute
        options = await generator.generate_next_steps(
            domain_output, current_agent="query_optimizer"
        )

        # Assert
        assert len(options) == 1
        assert "Query execution time exceeds 30 seconds" in options[0].description
