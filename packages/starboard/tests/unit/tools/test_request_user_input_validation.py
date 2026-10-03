# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Tests for request_user_input tool validation.

This tests the safety-net guardrail that catches date clarification questions.
The primary fix is in parameter_validator.py which auto-applies defaults.
"""

import pytest
from starboard.tools.request_user_input_tool import _is_blocked_question


class TestBlockedQuestionDetection:
    """Test the _is_blocked_question validation function."""

    @pytest.mark.parametrize(
        "question",
        [
            # Asking user to CHOOSE between rolling and calendar - should be blocked
            "Do you want a rolling window or calendar month?",
            "Should I use rolling 30 days or calendar month?",
            "Rolling versus calendar - which do you prefer?",
            # Asking WHAT date/time range to use - should be blocked
            "Which date range should I use?",
            "What time period do you want?",
            # Clarifying date interpretation - should be blocked
            "Did you mean calendar or rolling for 'last month'?",
            "Do you mean rolling or calendar month?",
        ],
    )
    def test_date_range_questions_are_blocked(self, question: str):
        """Questions asking user to clarify date interpretations should be blocked."""
        is_blocked, reason = _is_blocked_question(question)
        assert is_blocked, f"Question should be blocked: {question}"
        assert "30 days" in reason.lower() or "default" in reason.lower()

    @pytest.mark.parametrize(
        "question",
        [
            # Legitimate ID questions - should NOT be blocked
            "Which job would you like me to analyze?",
            "I found 5 jobs matching 'ETL'. Which one?",
            "What is the job_id?",
            "Which warehouse should I focus on?",
            "I need the cluster_id to proceed.",
            # Clarification about entities - should NOT be blocked
            "I found multiple queries matching your description. Which one?",
            "There are 3 tables with similar names. Please specify.",
            "Which specific resource are you asking about?",
            # General help questions - should NOT be blocked
            "What would you like help with?",
            "Can you provide more details about the issue?",
            # Questions that MENTION dates but don't ask to clarify - should NOT be blocked
            "I'll analyze the last 30 days. Which workspace should I use?",
            "For the previous month's data, which job should I focus on?",
        ],
    )
    def test_legitimate_questions_are_not_blocked(self, question: str):
        """Legitimate questions should not be blocked."""
        is_blocked, reason = _is_blocked_question(question)
        assert not is_blocked, f"Question should NOT be blocked: {question}"
        assert reason == ""


class TestRequestUserInputToolValidation:
    """Integration tests for the full tool with validation."""

    @pytest.mark.asyncio
    async def test_blocked_question_returns_rejection(self):
        """Blocked questions should return a rejection immediately."""
        from starboard.tools.request_user_input_tool import RequestUserInputTool

        tool = RequestUserInputTool(events=None, timeout_seconds=1.0)

        result = await tool.request_user_input(
            question="Do you want the rolling 30 days or calendar month?",
            context="Cost analysis",
        )

        assert result["status"] == "rejected"
        assert "error" in result
        assert "default" in result["error"].lower()
        assert "question_rejected" in result

    @pytest.mark.asyncio
    async def test_legitimate_question_proceeds(self):
        """Legitimate questions should proceed (will timeout since no response)."""
        from starboard.tools.request_user_input_tool import RequestUserInputTool

        tool = RequestUserInputTool(events=None, timeout_seconds=0.1)

        result = await tool.request_user_input(
            question="Which job would you like me to analyze?",
            context="Job optimization",
        )

        # Should timeout, not be rejected
        assert result["status"] == "timeout"
        assert "rejected" not in result.get("status", "")
