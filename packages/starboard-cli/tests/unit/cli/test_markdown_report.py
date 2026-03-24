"""Tests for markdown report generation.

Tests cover:
- _generate_markdown_report function
- Various output formats
- complete_report handling
- Legacy format fallback
"""

from unittest.mock import patch

from starboard_cli.cli.main import _generate_markdown_report


class TestGenerateMarkdownReport:
    """Tests for _generate_markdown_report function."""

    def test_generates_header(self):
        """Test that report has header."""
        output = {"user_goal": "test goal"}

        result = _generate_markdown_report(output)

        assert "# Starboard Agent Analysis Report" in result
        assert "**Generated**:" in result

    def test_includes_goal(self):
        """Test that user goal is included."""
        output = {"user_goal": "optimize my query"}

        result = _generate_markdown_report(output)

        assert "## Goal" in result
        assert "optimize my query" in result

    def test_includes_summary(self):
        """Test that summary is included."""
        output = {
            "user_goal": "test",
            "summary": "This is the summary of the analysis.",
        }

        result = _generate_markdown_report(output)

        assert "## Summary" in result
        assert "This is the summary of the analysis." in result

    def test_includes_recommendations(self):
        """Test that recommendations are formatted."""
        output = {
            "user_goal": "test",
            "recommendations": [
                {
                    "title": "Add Index",
                    "description": "Add an index to improve performance.",
                    "implementation": "CREATE INDEX ...",
                },
                {
                    "title": "Optimize Query",
                    "description": "Rewrite the query for efficiency.",
                },
            ],
        }

        result = _generate_markdown_report(output)

        assert "## Recommendations" in result
        assert "### 1. Add Index" in result
        assert "Add an index to improve performance." in result
        assert "**Implementation:**" in result
        assert "CREATE INDEX ..." in result
        assert "### 2. Optimize Query" in result
        assert "Rewrite the query for efficiency." in result

    def test_includes_metadata(self):
        """Test that execution metadata is included."""
        output = {
            "user_goal": "test",
            "steps_taken": 5,
            "tools_used": ["tool1", "tool2"],
            "tokens_used": 1500,
            "cost_usd": 0.0234,
            "duration_seconds": 12.5,
        }

        result = _generate_markdown_report(output)

        assert "## Execution Metadata" in result
        assert "**Steps taken**: 5" in result
        assert "tool1, tool2" in result
        assert "1,500" in result  # Formatted with comma
        assert "$0.0234" in result
        assert "12.50s" in result

    def test_handles_missing_tools(self):
        """Test that missing tools_used is handled."""
        output = {"user_goal": "test", "tools_used": []}

        result = _generate_markdown_report(output)

        assert "**Tools used**: N/A" in result

    def test_handles_none_tools(self):
        """Test that None tools_used is handled."""
        output = {"user_goal": "test"}

        result = _generate_markdown_report(output)

        assert "**Tools used**: N/A" in result

    def test_handles_non_integer_tokens(self):
        """Test that non-integer tokens_used is handled."""
        output = {"user_goal": "test", "tokens_used": "N/A"}

        result = _generate_markdown_report(output)

        assert "**Tokens used**: N/A" in result

    def test_uses_complete_report_when_available(self):
        """Test that complete_report is used with formatter."""
        output = {
            "user_goal": "test goal",
            "complete_report": {
                "type": "job_analysis",
                "content": {"findings": []},
            },
        }

        with patch(
            "starboard_server.agents.report_formatters.format_agent_report"
        ) as mock_format:
            mock_format.return_value = "## Formatted Report Content"

            result = _generate_markdown_report(output)

            mock_format.assert_called_once_with(output["complete_report"])
            assert "## Formatted Report Content" in result
            assert "## Goal" in result
            assert "test goal" in result

    def test_falls_back_on_formatter_error(self):
        """Test that legacy format is used if formatter fails."""
        output = {
            "user_goal": "test goal",
            "summary": "fallback summary",
            "complete_report": {"invalid": "data"},
        }

        with patch(
            "starboard_server.agents.report_formatters.format_agent_report"
        ) as mock_format:
            mock_format.side_effect = Exception("Formatter error")

            result = _generate_markdown_report(output)

            # Should fall back to legacy formatting
            assert "## Summary" in result
            assert "fallback summary" in result

    def test_falls_back_when_formatter_returns_none(self):
        """Test that legacy format is used if formatter returns None."""
        output = {
            "user_goal": "test goal",
            "summary": "fallback summary",
            "complete_report": {},
        }

        with patch(
            "starboard_server.agents.report_formatters.format_agent_report"
        ) as mock_format:
            mock_format.return_value = None

            result = _generate_markdown_report(output)

            # Should fall back to legacy formatting
            assert "## Summary" in result
            assert "fallback summary" in result

    def test_complete_report_includes_conversation_id(self):
        """Test that complete report includes conversation ID."""
        output = {
            "user_goal": "test",
            "conversation_id": "conv_abc123",
            "complete_report": {"data": "test"},
        }

        with patch(
            "starboard_server.agents.report_formatters.format_agent_report"
        ) as mock_format:
            mock_format.return_value = "## Report"

            result = _generate_markdown_report(output)

            assert "**Conversation ID**: conv_abc123" in result

    def test_complete_report_includes_cost(self):
        """Test that complete report includes cost metadata."""
        output = {
            "user_goal": "test",
            "tokens_used": 5000,
            "cost_usd": 0.125,
            "complete_report": {"data": "test"},
        }

        with patch(
            "starboard_server.agents.report_formatters.format_agent_report"
        ) as mock_format:
            mock_format.return_value = "## Report"

            result = _generate_markdown_report(output)

            assert "**Tokens Used**: 5,000" in result
            assert "**Cost**: $0.1250" in result

    def test_handles_recommendation_without_title(self):
        """Test that recommendation without title gets default."""
        output = {
            "user_goal": "test",
            "recommendations": [
                {"description": "Some recommendation without title"},
            ],
        }

        result = _generate_markdown_report(output)

        assert "### 1. Recommendation" in result
        assert "Some recommendation without title" in result

    def test_handles_empty_output(self):
        """Test that empty output doesn't crash."""
        output = {}

        result = _generate_markdown_report(output)

        assert "# Starboard Agent Analysis Report" in result
        # Should not have goal section
        assert "## Goal" not in result

    def test_handles_zero_cost(self):
        """Test that zero cost is formatted correctly."""
        output = {
            "user_goal": "test",
            "cost_usd": 0,
            "tokens_used": 0,
        }

        result = _generate_markdown_report(output)

        assert "$0.0000" in result
