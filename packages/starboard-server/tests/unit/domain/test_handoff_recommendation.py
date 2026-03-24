"""Unit tests for handoff recommendation domain models.

Tests HandoffRecommendation and HandoffConfidence models.
Following TDD: write tests first, then implement.

Part of Phase 9: Service Catalog & Next-Step Suggestions
"""

import pytest

# These imports will fail initially - that's expected in TDD
from starboard_server.domain.models.handoff_recommendation import (
    HandoffConfidence,
    HandoffRecommendation,
)


class TestHandoffConfidence:
    """Test HandoffConfidence enum."""

    def test_handoff_confidence_values(self):
        """Test that HandoffConfidence has expected values."""
        assert HandoffConfidence.HIGH.value == "high"
        assert HandoffConfidence.MEDIUM.value == "medium"
        assert HandoffConfidence.LOW.value == "low"

    def test_handoff_confidence_from_string(self):
        """Test creating HandoffConfidence from string."""
        assert HandoffConfidence("high") == HandoffConfidence.HIGH
        assert HandoffConfidence("medium") == HandoffConfidence.MEDIUM
        assert HandoffConfidence("low") == HandoffConfidence.LOW

    def test_handoff_confidence_invalid_value(self):
        """Test that invalid confidence raises error."""
        with pytest.raises(ValueError):
            HandoffConfidence("invalid")

    def test_handoff_confidence_ordering(self):
        """Test that confidences can be compared for priority."""
        # Define ordering: HIGH > MEDIUM > LOW (using < for total_ordering)
        assert HandoffConfidence.MEDIUM < HandoffConfidence.HIGH
        assert HandoffConfidence.LOW < HandoffConfidence.MEDIUM
        assert HandoffConfidence.LOW < HandoffConfidence.HIGH

    def test_handoff_confidence_sorting(self):
        """Test that confidences can be sorted."""
        confidences = [
            HandoffConfidence.LOW,
            HandoffConfidence.HIGH,
            HandoffConfidence.MEDIUM,
        ]
        sorted_confidences = sorted(confidences, reverse=True)

        assert sorted_confidences[0] == HandoffConfidence.HIGH
        assert sorted_confidences[1] == HandoffConfidence.MEDIUM
        assert sorted_confidences[2] == HandoffConfidence.LOW


class TestHandoffRecommendation:
    """Test HandoffRecommendation data model."""

    def test_create_minimal_handoff_recommendation(self):
        """Test creating a handoff recommendation with minimal fields."""
        recommendation = HandoffRecommendation(
            target_domain="performance",
            confidence=HandoffConfidence.HIGH,
            reason="User mentioned slow query performance",
        )

        assert recommendation.target_domain == "performance"
        assert recommendation.confidence == HandoffConfidence.HIGH
        assert recommendation.reason == "User mentioned slow query performance"
        assert recommendation.context_to_pass is None

    def test_create_full_handoff_recommendation(self):
        """Test creating a handoff recommendation with all fields."""
        context = {
            "query_id": "abc123",
            "execution_time_ms": 45000,
            "user_complaint": "query is slow",
        }

        recommendation = HandoffRecommendation(
            target_domain="performance",
            confidence=HandoffConfidence.HIGH,
            reason="Slow query identified, needs deep performance analysis",
            context_to_pass=context,
        )

        assert recommendation.target_domain == "performance"
        assert recommendation.confidence == HandoffConfidence.HIGH
        assert "performance analysis" in recommendation.reason
        assert recommendation.context_to_pass == context
        assert recommendation.context_to_pass["query_id"] == "abc123"

    def test_handoff_recommendation_immutable(self):
        """Test that HandoffRecommendation is immutable."""
        recommendation = HandoffRecommendation(
            target_domain="performance",
            confidence=HandoffConfidence.HIGH,
            reason="Test reason",
        )

        with pytest.raises(AttributeError):
            recommendation.reason = "Modified"  # type: ignore

    def test_handoff_recommendation_validation_empty_target_domain(self):
        """Test that empty target_domain is rejected."""
        with pytest.raises(ValueError, match="target_domain cannot be empty"):
            HandoffRecommendation(
                target_domain="",
                confidence=HandoffConfidence.HIGH,
                reason="Test",
            )

    def test_handoff_recommendation_validation_whitespace_target_domain(self):
        """Test that whitespace-only target_domain is rejected."""
        with pytest.raises(ValueError, match="target_domain cannot be empty"):
            HandoffRecommendation(
                target_domain="   ",
                confidence=HandoffConfidence.HIGH,
                reason="Test",
            )

    def test_handoff_recommendation_validation_empty_reason(self):
        """Test that empty reason is rejected."""
        with pytest.raises(ValueError, match="reason cannot be empty"):
            HandoffRecommendation(
                target_domain="performance",
                confidence=HandoffConfidence.HIGH,
                reason="",
            )

    def test_handoff_recommendation_validation_short_reason(self):
        """Test that too-short reason is rejected."""
        with pytest.raises(ValueError, match="reason must be at least 10 characters"):
            HandoffRecommendation(
                target_domain="performance",
                confidence=HandoffConfidence.HIGH,
                reason="Too short",
            )

    def test_handoff_recommendation_validation_long_reason_allowed(self):
        """Test that long, descriptive reasons are accepted."""
        long_reason = (
            "User's query is experiencing severe performance degradation "
            "with execution times exceeding 45 seconds. This requires "
            "detailed analysis of Spark UI metrics, stage-level performance, "
            "and potential data skew detection."
        )

        recommendation = HandoffRecommendation(
            target_domain="performance",
            confidence=HandoffConfidence.HIGH,
            reason=long_reason,
        )

        assert recommendation.reason == long_reason

    def test_handoff_recommendation_validation_valid_domains(self):
        """Test that standard domain names are accepted."""
        valid_domains = [
            "performance",
            "finops",
            "governance",
            "security",
            "data_quality",
            "monitoring",
        ]

        for domain in valid_domains:
            recommendation = HandoffRecommendation(
                target_domain=domain,
                confidence=HandoffConfidence.MEDIUM,
                reason="Valid domain test reason here",
            )
            assert recommendation.target_domain == domain

    def test_handoff_recommendation_to_dict(self):
        """Test serialization to dictionary."""
        recommendation = HandoffRecommendation(
            target_domain="performance",
            confidence=HandoffConfidence.HIGH,
            reason="Test reason for handoff",
        )

        result = recommendation.to_dict()

        assert isinstance(result, dict)
        assert result["target_domain"] == "performance"
        assert result["confidence"] == "high"
        assert result["reason"] == "Test reason for handoff"
        assert result["context_to_pass"] is None

    def test_handoff_recommendation_to_dict_with_context(self):
        """Test serialization with context included."""
        context = {"query_id": "abc123", "execution_time_ms": 45000}

        recommendation = HandoffRecommendation(
            target_domain="performance",
            confidence=HandoffConfidence.HIGH,
            reason="Test reason for handoff",
            context_to_pass=context,
        )

        result = recommendation.to_dict()

        assert result["context_to_pass"] == context
        assert result["context_to_pass"]["query_id"] == "abc123"

    def test_handoff_recommendation_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "target_domain": "performance",
            "confidence": "high",
            "reason": "Test reason for handoff",
            "context_to_pass": None,
        }

        recommendation = HandoffRecommendation.from_dict(data)

        assert recommendation.target_domain == "performance"
        assert recommendation.confidence == HandoffConfidence.HIGH
        assert recommendation.reason == "Test reason for handoff"
        assert recommendation.context_to_pass is None

    def test_handoff_recommendation_from_dict_with_context(self):
        """Test deserialization with context."""
        data = {
            "target_domain": "performance",
            "confidence": "medium",
            "reason": "Test reason for handoff",
            "context_to_pass": {"query_id": "xyz789", "warehouse_id": "prod"},
        }

        recommendation = HandoffRecommendation.from_dict(data)

        assert recommendation.context_to_pass is not None
        assert recommendation.context_to_pass["query_id"] == "xyz789"
        assert recommendation.context_to_pass["warehouse_id"] == "prod"

    def test_handoff_recommendation_equality(self):
        """Test equality comparison."""
        rec1 = HandoffRecommendation(
            target_domain="performance",
            confidence=HandoffConfidence.HIGH,
            reason="Test reason for comparison",
        )

        rec2 = HandoffRecommendation(
            target_domain="performance",
            confidence=HandoffConfidence.HIGH,
            reason="Test reason for comparison",
        )

        rec3 = HandoffRecommendation(
            target_domain="finops",
            confidence=HandoffConfidence.HIGH,
            reason="Test reason for comparison",
        )

        assert rec1 == rec2
        assert rec1 != rec3

    def test_handoff_recommendation_hash(self):
        """Test that handoff recommendations are hashable."""
        recommendation = HandoffRecommendation(
            target_domain="performance",
            confidence=HandoffConfidence.HIGH,
            reason="Test reason for hashing",
        )

        # Should be hashable for use in sets/dicts
        rec_set = {recommendation}
        assert recommendation in rec_set

    def test_handoff_recommendation_string_representation(self):
        """Test string representation includes key fields."""
        recommendation = HandoffRecommendation(
            target_domain="performance",
            confidence=HandoffConfidence.HIGH,
            reason="Test reason for string repr",
        )

        str_repr = str(recommendation)
        assert "performance" in str_repr
        assert "high" in str_repr or "HIGH" in str_repr

    def test_multiple_handoff_recommendations(self):
        """Test creating multiple recommendations (typical use case)."""
        recommendations = (
            HandoffRecommendation(
                target_domain="performance",
                confidence=HandoffConfidence.HIGH,
                reason="Deep performance analysis needed for slow query",
            ),
            HandoffRecommendation(
                target_domain="finops",
                confidence=HandoffConfidence.MEDIUM,
                reason="Cost impact analysis would be valuable",
            ),
            HandoffRecommendation(
                target_domain="governance",
                confidence=HandoffConfidence.LOW,
                reason="Optional: Review data access policies",
            ),
        )

        assert len(recommendations) == 3
        assert recommendations[0].confidence == HandoffConfidence.HIGH
        assert recommendations[1].confidence == HandoffConfidence.MEDIUM
        assert recommendations[2].confidence == HandoffConfidence.LOW

    def test_handoff_recommendations_can_be_sorted_by_confidence(self):
        """Test that recommendations can be sorted by confidence."""
        recommendations = [
            HandoffRecommendation(
                target_domain="governance",
                confidence=HandoffConfidence.LOW,
                reason="Low priority governance check needed",
            ),
            HandoffRecommendation(
                target_domain="performance",
                confidence=HandoffConfidence.HIGH,
                reason="High priority performance analysis needed",
            ),
            HandoffRecommendation(
                target_domain="finops",
                confidence=HandoffConfidence.MEDIUM,
                reason="Medium priority cost analysis needed",
            ),
        ]

        sorted_recs = sorted(recommendations, key=lambda r: r.confidence, reverse=True)

        assert sorted_recs[0].confidence == HandoffConfidence.HIGH
        assert sorted_recs[1].confidence == HandoffConfidence.MEDIUM
        assert sorted_recs[2].confidence == HandoffConfidence.LOW
