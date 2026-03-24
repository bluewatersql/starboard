"""Test Analytics V1 prompt formatting to catch brace escaping errors."""

import pytest
from starboard_server.prompts.analytics.v1 import ANALYTICS_SYSTEM_PROMPT


def test_analytics_v1_prompt_formatting():
    """Test that the Analytics V1 prompt formats without KeyError.

    This test catches brace escaping errors that cause KeyError during .format().
    """
    # Test with typical values
    prompt = ANALYTICS_SYSTEM_PROMPT.format(
        goal="Analyze warehouse costs",
        mode="online",
    )

    assert len(prompt) > 10000, "Prompt should be substantial"
    assert "Show me warehouse costs" not in prompt  # Shouldn't have literal examples
    assert "build_analytics_context" in prompt  # Should describe context builder
    assert "build_sql_query" in prompt
    assert "validate_sql_query" in prompt
    assert "execute_sql_query" in prompt


def test_analytics_v1_prompt_no_unescaped_braces():
    """Verify no unescaped braces remain in formatted prompt."""
    prompt = ANALYTICS_SYSTEM_PROMPT.format(
        goal="Test goal",
        mode="online",
    )

    # After formatting, there should be no single braces (all should be doubled or literal)
    # We check for common patterns that indicate formatting errors
    error_patterns = [
        '{"sql"',  # Should be {{"sql"
        '{"is_valid"',  # Should be {{"is_valid"
        '{"results"',  # Should be {{"results"
        '{"category"',  # Should be {{"category"
    ]

    for pattern in error_patterns:
        assert pattern not in prompt, f"Found unescaped pattern: {pattern}"


def test_analytics_v1_prompt_with_edge_cases():
    """Test prompt formatting with edge case values."""
    # Empty goal
    prompt1 = ANALYTICS_SYSTEM_PROMPT.format(goal="", mode="online")
    assert len(prompt1) > 10000

    # Long goal with special chars
    prompt2 = ANALYTICS_SYSTEM_PROMPT.format(
        goal="Find all jobs where cost > $1000 and runtime > 1hr",
        mode="offline",
    )
    assert len(prompt2) > 10000

    # Goal with braces (should not cause issues)
    prompt3 = ANALYTICS_SYSTEM_PROMPT.format(
        goal="Show me {warehouse_id} costs",
        mode="online",
    )
    assert len(prompt3) > 10000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
