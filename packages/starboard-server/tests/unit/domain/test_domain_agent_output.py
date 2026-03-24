"""Unit tests for DomainAgentOutput structure.

Tests domain agent output format with handoff recommendations.
Part of Phase 9: Service Catalog & Next-Step Suggestions
"""

import pytest

# These imports will fail initially - that's expected in TDD
from starboard_server.domain.models.agent_output import (
    DomainAgentOutput,
    InDomainNextStep,
)
from starboard_server.domain.models.handoff_recommendation import (
    HandoffConfidence,
    HandoffRecommendation,
)


class TestInDomainNextStep:
    """Test InDomainNextStep model."""

    def test_create_in_domain_next_step(self):
        """Test creating an in-domain next step suggestion."""
        step = InDomainNextStep(
            id="continue_optimization",
            title="Continue optimization",
            description="Apply the recommended query optimizations",
            suggested_prompt="Apply these optimizations",
        )

        assert step.id == "continue_optimization"
        assert step.title == "Continue optimization"
        assert step.description == "Apply the recommended query optimizations"
        assert step.suggested_prompt == "Apply these optimizations"

    def test_in_domain_next_step_immutable(self):
        """Test that InDomainNextStep is immutable."""
        step = InDomainNextStep(
            id="test_step",
            title="Test",
            description="Test step",
            suggested_prompt="Test",
        )

        with pytest.raises(AttributeError):
            step.title = "Modified"  # type: ignore

    def test_in_domain_next_step_to_dict(self):
        """Test serialization to dict."""
        step = InDomainNextStep(
            id="test_step",
            title="Test Step",
            description="Description",
            suggested_prompt="Do this",
        )

        result = step.to_dict()

        assert result["id"] == "test_step"
        assert result["title"] == "Test Step"
        assert result["description"] == "Description"
        assert result["suggested_prompt"] == "Do this"

    def test_in_domain_next_step_from_dict(self):
        """Test deserialization from dict."""
        data = {
            "id": "test_step",
            "title": "Test Step",
            "description": "Description",
            "suggested_prompt": "Do this",
        }

        step = InDomainNextStep.from_dict(data)

        assert step.id == "test_step"
        assert step.title == "Test Step"


class TestDomainAgentOutput:
    """Test DomainAgentOutput model."""

    def test_create_minimal_domain_agent_output(self):
        """Test creating output with only required fields."""
        output = DomainAgentOutput(
            primary_answer="Your query is missing indexes.",
            in_domain_next_steps=(),
            handoff_recommendations=None,
            metadata={},
        )

        assert output.primary_answer == "Your query is missing indexes."
        assert output.in_domain_next_steps == ()
        assert output.handoff_recommendations is None
        assert output.metadata == {}

    def test_create_full_domain_agent_output(self):
        """Test creating output with all fields populated."""
        in_domain_steps = (
            InDomainNextStep(
                id="step1",
                title="Add Index",
                description="Add missing index",
                suggested_prompt="Add index to table",
            ),
            InDomainNextStep(
                id="step2",
                title="Analyze Plan",
                description="Analyze execution plan",
                suggested_prompt="Show execution plan",
            ),
        )

        handoff_recommendations = (
            HandoffRecommendation(
                target_domain="performance",
                confidence=HandoffConfidence.HIGH,
                reason="Query is slow and needs deep performance analysis",
            ),
            HandoffRecommendation(
                target_domain="finops",
                confidence=HandoffConfidence.MEDIUM,
                reason="Cost analysis would be valuable",
            ),
        )

        output = DomainAgentOutput(
            primary_answer="Found query performance issues.",
            in_domain_next_steps=in_domain_steps,
            handoff_recommendations=handoff_recommendations,
            metadata={"query_id": "abc123", "execution_time_ms": 45000},
        )

        assert "performance issues" in output.primary_answer
        assert len(output.in_domain_next_steps) == 2
        assert output.in_domain_next_steps[0].id == "step1"
        assert len(output.handoff_recommendations) == 2
        assert output.handoff_recommendations[0].target_domain == "performance"
        assert output.metadata["query_id"] == "abc123"

    def test_domain_agent_output_immutable(self):
        """Test that DomainAgentOutput is immutable."""
        output = DomainAgentOutput(
            primary_answer="Test answer",
            in_domain_next_steps=(),
            handoff_recommendations=None,
            metadata={},
        )

        with pytest.raises(AttributeError):
            output.primary_answer = "Modified"  # type: ignore

    def test_domain_agent_output_validation_empty_answer(self):
        """Test that empty primary_answer is rejected."""
        with pytest.raises(ValueError, match="primary_answer cannot be empty"):
            DomainAgentOutput(
                primary_answer="",
                in_domain_next_steps=(),
                handoff_recommendations=None,
                metadata={},
            )

    def test_domain_agent_output_validation_whitespace_answer(self):
        """Test that whitespace-only primary_answer is rejected."""
        with pytest.raises(ValueError, match="primary_answer cannot be empty"):
            DomainAgentOutput(
                primary_answer="   ",
                in_domain_next_steps=(),
                handoff_recommendations=None,
                metadata={},
            )

    def test_domain_agent_output_with_only_in_domain_steps(self):
        """Test output with in-domain steps but no handoffs."""
        steps = (
            InDomainNextStep(
                id="step1",
                title="Continue",
                description="Continue in current domain",
                suggested_prompt="Continue",
            ),
        )

        output = DomainAgentOutput(
            primary_answer="Here's your answer.",
            in_domain_next_steps=steps,
            handoff_recommendations=None,
            metadata={},
        )

        assert len(output.in_domain_next_steps) == 1
        assert output.handoff_recommendations is None

    def test_domain_agent_output_with_only_handoffs(self):
        """Test output with handoffs but no in-domain steps."""
        handoffs = (
            HandoffRecommendation(
                target_domain="performance",
                confidence=HandoffConfidence.HIGH,
                reason="Performance analysis recommended",
            ),
        )

        output = DomainAgentOutput(
            primary_answer="Query analyzed.",
            in_domain_next_steps=(),
            handoff_recommendations=handoffs,
            metadata={},
        )

        assert len(output.in_domain_next_steps) == 0
        assert len(output.handoff_recommendations) == 1

    def test_domain_agent_output_to_dict(self):
        """Test serialization to dict."""
        steps = (
            InDomainNextStep(
                id="step1",
                title="Step 1",
                description="First step",
                suggested_prompt="Do step 1",
            ),
        )

        handoffs = (
            HandoffRecommendation(
                target_domain="performance",
                confidence=HandoffConfidence.HIGH,
                reason="Deep performance analysis needed",
            ),
        )

        output = DomainAgentOutput(
            primary_answer="Analysis complete.",
            in_domain_next_steps=steps,
            handoff_recommendations=handoffs,
            metadata={"agent": "query_optimizer"},
        )

        result = output.to_dict()

        assert result["primary_answer"] == "Analysis complete."
        assert isinstance(result["in_domain_next_steps"], list)
        assert len(result["in_domain_next_steps"]) == 1
        assert result["in_domain_next_steps"][0]["id"] == "step1"
        assert isinstance(result["handoff_recommendations"], list)
        assert len(result["handoff_recommendations"]) == 1
        assert result["handoff_recommendations"][0]["target_domain"] == "performance"
        assert result["metadata"]["agent"] == "query_optimizer"

    def test_domain_agent_output_to_dict_with_none_handoffs(self):
        """Test serialization when handoff_recommendations is None."""
        output = DomainAgentOutput(
            primary_answer="Simple answer.",
            in_domain_next_steps=(),
            handoff_recommendations=None,
            metadata={},
        )

        result = output.to_dict()

        assert result["handoff_recommendations"] is None

    def test_domain_agent_output_from_dict(self):
        """Test deserialization from dict."""
        data = {
            "primary_answer": "Test answer",
            "in_domain_next_steps": [
                {
                    "id": "step1",
                    "title": "Step 1",
                    "description": "First step",
                    "suggested_prompt": "Do step 1",
                }
            ],
            "handoff_recommendations": [
                {
                    "target_domain": "performance",
                    "confidence": "high",
                    "reason": "Performance analysis needed",
                    "context_to_pass": None,
                }
            ],
            "metadata": {"test": "value"},
        }

        output = DomainAgentOutput.from_dict(data)

        assert output.primary_answer == "Test answer"
        assert len(output.in_domain_next_steps) == 1
        assert output.in_domain_next_steps[0].id == "step1"
        assert len(output.handoff_recommendations) == 1
        assert output.handoff_recommendations[0].target_domain == "performance"
        assert output.metadata["test"] == "value"

    def test_domain_agent_output_from_dict_with_none_handoffs(self):
        """Test deserialization when handoff_recommendations is None."""
        data = {
            "primary_answer": "Test answer",
            "in_domain_next_steps": [],
            "handoff_recommendations": None,
            "metadata": {},
        }

        output = DomainAgentOutput.from_dict(data)

        assert output.handoff_recommendations is None

    def test_domain_agent_output_equality(self):
        """Test equality comparison."""
        output1 = DomainAgentOutput(
            primary_answer="Test",
            in_domain_next_steps=(),
            handoff_recommendations=None,
            metadata={},
        )

        output2 = DomainAgentOutput(
            primary_answer="Test",
            in_domain_next_steps=(),
            handoff_recommendations=None,
            metadata={},
        )

        output3 = DomainAgentOutput(
            primary_answer="Different",
            in_domain_next_steps=(),
            handoff_recommendations=None,
            metadata={},
        )

        assert output1 == output2
        assert output1 != output3

    def test_multiple_handoff_recommendations_sorted_by_confidence(self):
        """Test that multiple handoffs can be created and sorted."""
        handoffs = [
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
        ]

        # Sort by confidence (descending)
        sorted_handoffs = sorted(handoffs, key=lambda h: h.confidence, reverse=True)

        output = DomainAgentOutput(
            primary_answer="Analysis complete.",
            in_domain_next_steps=(),
            handoff_recommendations=tuple(sorted_handoffs),
            metadata={},
        )

        assert output.handoff_recommendations[0].confidence == HandoffConfidence.HIGH
        assert output.handoff_recommendations[1].confidence == HandoffConfidence.MEDIUM
        assert output.handoff_recommendations[2].confidence == HandoffConfidence.LOW
