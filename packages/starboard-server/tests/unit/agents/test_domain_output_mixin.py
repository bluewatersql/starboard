# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Unit tests for DomainAgentOutputMixin.

Tests the base mixin that all domain agents use to generate structured
DomainAgentOutput with handoff recommendations.

Part of Router Integration for Phase 9.
"""

from starboard_server.agents.output.domain_output_mixin import DomainAgentOutputMixin
from starboard_server.domain.models.agent_output import (
    DomainAgentOutput,
    InDomainNextStep,
)
from starboard_server.domain.models.handoff_recommendation import (
    HandoffConfidence,
    HandoffRecommendation,
)


class TestAgentWithMixin(DomainAgentOutputMixin):
    """Test agent class that uses the mixin."""

    pass


class TestDomainAgentOutputMixin:
    """Test DomainAgentOutputMixin functionality."""

    def test_build_minimal_output(self):
        """Test building minimal output with only primary answer."""
        agent = TestAgentWithMixin()

        output = agent.build_domain_output(primary_answer="Test response")

        assert isinstance(output, DomainAgentOutput)
        assert output.primary_answer == "Test response"
        assert output.in_domain_next_steps is None
        assert output.handoff_recommendations is None
        assert output.metadata == {}

    def test_build_output_with_in_domain_steps(self):
        """Test building output with in-domain next steps."""
        agent = TestAgentWithMixin()

        steps = [
            InDomainNextStep(
                id="step1",
                title="First step",
                description="First description",
                suggested_prompt="Do first step",
            ),
            InDomainNextStep(
                id="step2",
                title="Second step",
                description="Second description",
                suggested_prompt="Do second step",
            ),
        ]

        output = agent.build_domain_output(
            primary_answer="Test response", in_domain_steps=steps
        )

        assert output.in_domain_next_steps is not None
        assert len(output.in_domain_next_steps) == 2
        assert output.in_domain_next_steps[0].id == "step1"
        assert output.in_domain_next_steps[1].id == "step2"

    def test_build_output_with_handoff_recommendations(self):
        """Test building output with handoff recommendations."""
        agent = TestAgentWithMixin()

        handoffs = [
            HandoffRecommendation(
                target_domain="cluster",
                confidence=HandoffConfidence.HIGH,
                reason="Performance optimization needed",
            ),
        ]

        output = agent.build_domain_output(
            primary_answer="Test response", handoff_recommendations=handoffs
        )

        assert output.handoff_recommendations is not None
        assert len(output.handoff_recommendations) == 1
        assert output.handoff_recommendations[0].target_domain == "cluster"
        assert output.handoff_recommendations[0].confidence == HandoffConfidence.HIGH

    def test_build_output_with_metadata(self):
        """Test building output with metadata."""
        agent = TestAgentWithMixin()

        metadata = {"key": "value", "count": 42}

        output = agent.build_domain_output(
            primary_answer="Test response", metadata=metadata
        )

        assert output.metadata == metadata
        assert output.metadata["key"] == "value"
        assert output.metadata["count"] == 42

    def test_build_output_converts_lists_to_tuples(self):
        """Test that lists are converted to tuples for immutability."""
        agent = TestAgentWithMixin()

        steps = [
            InDomainNextStep(
                id="step1",
                title="Step 1",
                description="Desc",
                suggested_prompt="Do step",
            )
        ]
        handoffs = [
            HandoffRecommendation(
                target_domain="cluster",
                confidence=HandoffConfidence.MEDIUM,
                reason="Test reason",
            )
        ]

        output = agent.build_domain_output(
            primary_answer="Test",
            in_domain_steps=steps,
            handoff_recommendations=handoffs,
        )

        # Should be tuples, not lists
        assert isinstance(output.in_domain_next_steps, tuple)
        assert isinstance(output.handoff_recommendations, tuple)

    def test_suggest_compute_handoff(self):
        """Test creating compute domain handoff."""
        agent = TestAgentWithMixin()

        handoff = agent.suggest_compute_handoff(
            "Cluster optimization needed",
            HandoffConfidence.HIGH,
            {"cluster_id": "cluster-123"},
        )

        assert handoff.target_domain == "cluster"
        assert handoff.confidence == HandoffConfidence.HIGH
        assert handoff.reason == "Cluster optimization needed"
        assert handoff.context_to_pass["cluster_id"] == "cluster-123"

    def test_suggest_diagnostic_handoff(self):
        """Test creating diagnostic domain handoff."""
        agent = TestAgentWithMixin()

        handoff = agent.suggest_diagnostic_handoff(
            "Query failure needs investigation",
            HandoffConfidence.HIGH,
            {"error_code": "TIMEOUT"},
        )

        assert handoff.target_domain == "diagnostic"
        assert handoff.confidence == HandoffConfidence.HIGH
        assert handoff.reason == "Query failure needs investigation"
        assert handoff.context_to_pass["error_code"] == "TIMEOUT"

    def test_suggest_table_handoff(self):
        """Test creating table domain handoff."""
        agent = TestAgentWithMixin()

        handoff = agent.suggest_table_handoff(
            "Table statistics outdated",
            HandoffConfidence.MEDIUM,
            {"table_name": "main.users"},
        )

        assert handoff.target_domain == "tables"
        assert handoff.confidence == HandoffConfidence.MEDIUM
        assert handoff.reason == "Table statistics outdated"
        assert handoff.context_to_pass["table_name"] == "main.users"

    def test_suggest_query_handoff(self):
        """Test creating query domain handoff."""
        agent = TestAgentWithMixin()

        handoff = agent.suggest_query_handoff(
            "SQL query needs optimization", HandoffConfidence.HIGH
        )

        assert handoff.target_domain == "query"
        assert handoff.confidence == HandoffConfidence.HIGH
        assert handoff.reason == "SQL query needs optimization"

    def test_suggest_job_handoff(self):
        """Test creating job domain handoff."""
        agent = TestAgentWithMixin()

        handoff = agent.suggest_job_handoff(
            "Job configuration inefficient",
            HandoffConfidence.MEDIUM,
            {"job_id": "job-789"},
        )

        assert handoff.target_domain == "jobs"
        assert handoff.confidence == HandoffConfidence.MEDIUM
        assert handoff.reason == "Job configuration inefficient"
        assert handoff.context_to_pass["job_id"] == "job-789"

    def test_handoff_helpers_default_to_medium_confidence(self):
        """Test that handoff helpers default to MEDIUM confidence."""
        agent = TestAgentWithMixin()

        handoff1 = agent.suggest_compute_handoff("Test reason")
        handoff2 = agent.suggest_diagnostic_handoff("Test reason")
        handoff3 = agent.suggest_table_handoff("Test reason")

        assert handoff1.confidence == HandoffConfidence.MEDIUM
        assert handoff2.confidence == HandoffConfidence.MEDIUM
        assert handoff3.confidence == HandoffConfidence.MEDIUM

    def test_handoff_helpers_accept_empty_context(self):
        """Test that handoff helpers work with no context."""
        agent = TestAgentWithMixin()

        handoff = agent.suggest_compute_handoff("Test reason")

        assert handoff.context_to_pass is None or handoff.context_to_pass == {}

    def test_complete_workflow_example(self):
        """Test complete workflow: building output with multiple components."""
        agent = TestAgentWithMixin()

        # Build in-domain steps
        steps = [
            InDomainNextStep(
                id="analyze",
                title="Analyze query",
                description="Deep dive into query performance",
                suggested_prompt="Analyze this query",
            )
        ]

        # Suggest handoffs
        handoffs = [
            agent.suggest_compute_handoff(
                "Cluster may be under-provisioned",
                HandoffConfidence.HIGH,
                {"current_size": "small"},
            ),
            agent.suggest_diagnostic_handoff(
                "Investigate recurring errors", HandoffConfidence.MEDIUM
            ),
        ]

        # Build output
        output = agent.build_domain_output(
            primary_answer="Query analysis complete. Found performance issues.",
            in_domain_steps=steps,
            handoff_recommendations=handoffs,
            metadata={"confidence": 0.95, "query_id": "q123"},
        )

        # Verify complete structure
        assert output.primary_answer is not None
        assert len(output.in_domain_next_steps) == 1
        assert len(output.handoff_recommendations) == 2
        assert output.metadata["query_id"] == "q123"

        # Verify handoffs are sorted by confidence
        assert output.handoff_recommendations[0].confidence == HandoffConfidence.HIGH
        assert output.handoff_recommendations[1].confidence == HandoffConfidence.MEDIUM
