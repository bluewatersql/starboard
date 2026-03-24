"""Tests for report generation utilities.

Coverage targets:
- Confidence and effort indicators
- LLM usage summary reports
- Advisor report generation
- Report string formatting
- Async file write utilities (write_text_file, write_json_file)
"""

import json
from pathlib import Path
from typing import Any

import pytest
from starboard_server.infra.observability.reporting import (
    AnalystReports,
    Utils,
    generate_markdown_report,
    write_json_file,
    write_text_file,
)


class TestUtils:
    """Tests for Utils class methods."""

    def test_confidence_indicator_high(self) -> None:
        """Test confidence indicator for high confidence."""
        # Act
        indicator = Utils.confidence_indicator("high")

        # Assert
        assert indicator == "🟢"

    def test_confidence_indicator_medium(self) -> None:
        """Test confidence indicator for medium confidence."""
        # Act
        indicator = Utils.confidence_indicator("medium")

        # Assert
        assert indicator == "🟠"

    def test_confidence_indicator_low(self) -> None:
        """Test confidence indicator for low confidence."""
        # Act
        indicator = Utils.confidence_indicator("low")

        # Assert
        assert indicator == "🔴"

    def test_confidence_indicator_unknown(self) -> None:
        """Test confidence indicator for unknown value."""
        # Act
        indicator = Utils.confidence_indicator("unknown")

        # Assert
        assert indicator == "⚪"

    def test_effort_indicator_low(self) -> None:
        """Test effort indicator for low effort."""
        # Act
        indicator = Utils.effort_indicator("low")

        # Assert
        assert indicator == "🟢"  # Low effort is good

    def test_effort_indicator_medium(self) -> None:
        """Test effort indicator for medium effort."""
        # Act
        indicator = Utils.effort_indicator("medium")

        # Assert
        assert indicator == "🟠"

    def test_effort_indicator_high(self) -> None:
        """Test effort indicator for high effort."""
        # Act
        indicator = Utils.effort_indicator("high")

        # Assert
        assert indicator == "🔴"  # High effort is warning

    def test_effort_indicator_unknown(self) -> None:
        """Test effort indicator for unknown value."""
        # Act
        indicator = Utils.effort_indicator("unknown")

        # Assert
        assert indicator == "⚪"


class TestAnalystReportsLLMSummary:
    """Tests for LLM usage summary reporting."""

    def test_build_llm_usage_summary_with_token_usage(self, capsys: Any) -> None:
        """Test LLM usage summary with token usage data."""
        # Arrange
        results = {
            "token_usage": {
                "total_tokens": 1000,
                "prompt_tokens": 600,
                "completion_tokens": 400,
            }
        }

        # Act
        AnalystReports.build_llm_usage_summary(results)
        captured = capsys.readouterr()

        # Assert
        assert "LLM Summary" in captured.out
        assert "Token Usage" in captured.out
        assert "1,000" in captured.out or "1000" in captured.out
        assert "600" in captured.out
        assert "400" in captured.out

    def test_build_llm_usage_summary_with_completed_tasks(self, capsys: Any) -> None:
        """Test LLM usage summary with completed tasks."""
        # Arrange
        results = {
            "completed_tasks": ["task1", "task2", "task3"],
            "token_usage": {"total_tokens": 100},
        }

        # Act
        AnalystReports.build_llm_usage_summary(results)
        captured = capsys.readouterr()

        # Assert
        assert "Execution" in captured.out
        assert "Tasks completed: 3" in captured.out
        assert "task1" in captured.out

    def test_build_llm_usage_summary_empty_results(self, capsys: Any) -> None:
        """Test LLM usage summary with empty results."""
        # Arrange
        results: dict[str, Any] = {}

        # Act
        AnalystReports.build_llm_usage_summary(results)
        captured = capsys.readouterr()

        # Assert
        # Should print header even with empty results
        assert "LLM Summary" in captured.out

    def test_build_llm_usage_summary_non_integer_tokens(self, capsys: Any) -> None:
        """Test LLM usage summary with non-integer token values."""
        # Arrange
        results = {
            "token_usage": {
                "total_tokens": "N/A",
                "prompt_tokens": "N/A",
                "completion_tokens": "N/A",
            }
        }

        # Act
        AnalystReports.build_llm_usage_summary(results)
        captured = capsys.readouterr()

        # Assert
        assert "N/A" in captured.out


class TestAnalystReportsAdvisor:
    """Tests for advisor report generation."""

    def test_build_advisor_report_string_basic(self) -> None:
        """Test building basic advisor report string."""
        # Arrange
        results = {
            "results": {
                "final_advisor_advice": {
                    "summary": {"overview": "Test overview"},
                    "analysis": {
                        "findings": [
                            {
                                "rank": 1,
                                "title": "Finding 1",
                                "recommendation": "Test recommendation",
                            }
                        ]
                    },
                    "next_steps": [
                        {"rank": 1, "action": "Step 1"},
                        {"rank": 2, "action": "Step 2"},
                    ],
                }
            }
        }

        # Act
        report = AnalystReports.build_advisor_report_string(results)

        # Assert
        assert report
        assert "Findings" in report
        assert "Finding 1" in report

    def test_build_advisor_report_string_empty_advice(self) -> None:
        """Test building report with no advice."""
        # Arrange
        results: dict[str, Any] = {"results": {}}

        # Act
        report = AnalystReports.build_advisor_report_string(results)

        # Assert
        assert report == ""

    def test_build_advisor_report_string_multiple_sections(self) -> None:
        """Test building report with multiple sections."""
        # Arrange
        results = {
            "results": {
                "final_advisor_advice": {
                    "summary": {
                        "overview": "System overview",
                        "current_state": {"key_symptoms": ["Symptom 1", "Symptom 2"]},
                    },
                    "analysis": {
                        "findings": [
                            {"rank": 1, "title": "Finding 1"},
                            {"rank": 2, "title": "Finding 2"},
                            {"rank": 3, "title": "Finding 3"},
                        ]
                    },
                    "next_steps": [
                        {"rank": 1, "action": "Step 1"},
                        {"rank": 2, "action": "Step 2"},
                    ],
                }
            }
        }

        # Act
        report = AnalystReports.build_advisor_report_string(results)

        # Assert
        assert report
        # Should contain findings
        assert "Finding 1" in report or "Finding 2" in report

    def test_build_advisor_report_prints_to_stdout(self, capsys: Any) -> None:
        """Test that build_advisor_report prints to stdout."""
        # Arrange
        results = {
            "results": {
                "final_advisor_advice": {
                    "summary": {"overview": "Test overview"},
                    "analysis": {"findings": [{"rank": 1, "title": "Test finding"}]},
                    "next_steps": [{"rank": 1, "action": "Test step"}],
                }
            }
        }

        # Act
        AnalystReports.build_advisor_report(results)
        captured = capsys.readouterr()

        # Assert
        assert len(captured.out) > 0
        assert "Findings" in captured.out


class TestAnalystReportsEdgeCases:
    """Tests for edge cases in report generation."""

    def test_build_llm_usage_with_partial_data(self, capsys: Any) -> None:
        """Test LLM usage report with partial token data."""
        # Arrange
        results = {
            "token_usage": {
                "total_tokens": 100,
                # Missing prompt_tokens and completion_tokens
            }
        }

        # Act
        AnalystReports.build_llm_usage_summary(results)
        captured = capsys.readouterr()

        # Assert
        assert "100" in captured.out
        assert "N/A" in captured.out

    def test_confidence_indicator_case_insensitive(self) -> None:
        """Test that confidence indicators handle case."""
        # Act & Assert
        assert Utils.confidence_indicator("HIGH") == "⚪"  # Unknown (not matched)
        assert Utils.confidence_indicator("high") == "🟢"
        assert Utils.confidence_indicator("Low") == "⚪"  # Unknown
        assert Utils.confidence_indicator("low") == "🔴"

    def test_effort_indicator_various_values(self) -> None:
        """Test effort indicator with various input values."""
        # Assert
        assert Utils.effort_indicator("low") == "🟢"
        assert Utils.effort_indicator("medium") == "🟠"
        assert Utils.effort_indicator("high") == "🔴"
        assert Utils.effort_indicator("") == "⚪"
        assert Utils.effort_indicator("invalid") == "⚪"

    def test_build_advisor_report_with_minimal_fields(self) -> None:
        """Test advisor report with minimal fields."""
        # Arrange
        results = {
            "results": {
                "final_advisor_advice": {
                    "summary": {},
                    "analysis": {},
                    "next_steps": [],
                }
            }
        }

        # Act
        report = AnalystReports.build_advisor_report_string(results)

        # Assert
        # Should return a report even with empty sections
        assert isinstance(report, str)


class TestReportingIntegration:
    """Integration tests for reporting functionality."""

    def test_full_report_workflow(self, capsys: Any) -> None:
        """Test complete reporting workflow."""
        # Arrange
        results = {
            "token_usage": {
                "total_tokens": 5000,
                "prompt_tokens": 3000,
                "completion_tokens": 2000,
            },
            "completed_tasks": ["discover", "analyze", "recommend"],
            "results": {
                "final_advisor_advice": {
                    "summary": {"overview": "System analysis"},
                    "analysis": {
                        "findings": [
                            {
                                "rank": 1,
                                "title": "Add index for performance",
                                "recommendation": "Create B-tree index",
                            }
                        ]
                    },
                    "next_steps": [{"rank": 1, "action": "Implement index"}],
                }
            },
        }

        # Act
        AnalystReports.build_llm_usage_summary(results)
        AnalystReports.build_advisor_report(results)
        captured = capsys.readouterr()

        # Assert
        # LLM summary should be present
        assert "LLM Summary" in captured.out
        assert "5,000" in captured.out or "5000" in captured.out

        # Execution should be present
        assert "Execution" in captured.out
        assert "3" in captured.out

        # Advisor report should be present
        assert "Findings" in captured.out or "index" in captured.out

    def test_report_with_empty_completed_tasks(self, capsys: Any) -> None:
        """Test report with empty completed tasks list."""
        # Arrange
        results = {"completed_tasks": [], "token_usage": {"total_tokens": 100}}

        # Act
        AnalystReports.build_llm_usage_summary(results)
        captured = capsys.readouterr()

        # Assert
        assert "Tasks completed: 0" in captured.out


class TestAnalystReportsMarkdown:
    """Tests for markdown report generation."""

    def test_build_advisor_report_markdown_basic(self) -> None:
        """Test building markdown advisor report."""
        # Arrange
        results = {
            "results": {
                "final_advisor_advice": {
                    "summary": {"overview": "Test overview"},
                    "analysis": {"findings": [{"rank": 1, "title": "Test finding"}]},
                    "next_steps": [{"rank": 1, "action": "Test action"}],
                }
            }
        }

        # Act
        report = AnalystReports.build_advisor_report_markdown(results)

        # Assert
        assert report
        assert isinstance(report, str)

    def test_build_advisor_report_markdown_empty(self) -> None:
        """Test building markdown report with no advice."""
        # Arrange
        results: dict[str, Any] = {"results": {}}

        # Act
        report = AnalystReports.build_advisor_report_markdown(results)

        # Assert
        assert report == ""

    def test_build_advisor_report_markdown_with_json_string_analysis(self) -> None:
        """Test markdown report with JSON string instead of dict."""
        # Arrange
        results: dict[str, Any] = {
            "results": {
                "final_advisor_advice": {
                    "summary": {},
                    "analysis": '{"findings": []}',  # JSON string
                    "next_steps": [],
                }
            }
        }

        # Act
        report = AnalystReports.build_advisor_report_markdown(results)

        # Assert
        assert isinstance(report, str)

    def test_build_advisor_report_markdown_with_invalid_json(self) -> None:
        """Test markdown report with invalid JSON string."""
        # Arrange
        results = {
            "results": {
                "final_advisor_advice": {
                    "summary": {},
                    "analysis": "invalid json",
                    "next_steps": "also invalid",
                }
            }
        }

        # Act
        report = AnalystReports.build_advisor_report_markdown(results)

        # Assert
        assert isinstance(report, str)

    def test_build_advisor_report_markdown_complex(self) -> None:
        """Test markdown report with complex nested data."""
        # Arrange
        results = {
            "results": {
                "final_advisor_advice": {
                    "summary": {
                        "overview": "Complex system",
                        "current_state": {"key_symptoms": ["Symptom 1"]},
                    },
                    "analysis": {
                        "findings": [
                            {
                                "rank": 1,
                                "title": "Finding 1",
                                "recommendation": "Do this",
                                "impact_estimate": {
                                    "confidence": "high",
                                    "latency_pct": 50,
                                },
                                "effort": {"level": "low"},
                            }
                        ]
                    },
                    "next_steps": [
                        {"rank": 1, "action": "Action 1"},
                        {"rank": 2, "action": "Action 2"},
                    ],
                }
            }
        }

        # Act
        report = AnalystReports.build_advisor_report_markdown(results)

        # Assert
        assert report
        assert len(report) > 100  # Should be substantial


class TestWriteTextFile:
    """Tests for async write_text_file utility."""

    @pytest.mark.asyncio
    async def test_write_text_file_creates_file(self, tmp_path: Path) -> None:
        """write_text_file should create a file with the given content."""
        filepath = tmp_path / "output.txt"
        content = "Hello, async world!"

        await write_text_file(filepath, content)

        assert filepath.exists()
        assert filepath.read_text(encoding="utf-8") == content

    @pytest.mark.asyncio
    async def test_write_text_file_overwrites_existing(self, tmp_path: Path) -> None:
        """write_text_file should overwrite existing files."""
        filepath = tmp_path / "output.txt"
        filepath.write_text("old content")

        await write_text_file(filepath, "new content")

        assert filepath.read_text(encoding="utf-8") == "new content"

    @pytest.mark.asyncio
    async def test_write_text_file_unicode(self, tmp_path: Path) -> None:
        """write_text_file should handle Unicode content correctly."""
        filepath = tmp_path / "unicode.txt"
        content = "Unicode: \u00e9\u00e8\u00ea \u00fc\u00f6\u00e4 \u4f60\u597d"

        await write_text_file(filepath, content)

        assert filepath.read_text(encoding="utf-8") == content


class TestWriteJsonFile:
    """Tests for async write_json_file utility."""

    @pytest.mark.asyncio
    async def test_write_json_file_creates_file(self, tmp_path: Path) -> None:
        """write_json_file should create a JSON file with the given data."""
        filepath = tmp_path / "output.json"
        data = {"key": "value", "number": 42}

        await write_json_file(filepath, data)

        assert filepath.exists()
        loaded = json.loads(filepath.read_text(encoding="utf-8"))
        assert loaded == data

    @pytest.mark.asyncio
    async def test_write_json_file_with_string_path(self, tmp_path: Path) -> None:
        """write_json_file should accept string paths."""
        filepath = tmp_path / "output.json"
        data = {"items": [1, 2, 3]}

        await write_json_file(str(filepath), data)

        assert filepath.exists()
        loaded = json.loads(filepath.read_text(encoding="utf-8"))
        assert loaded == data

    @pytest.mark.asyncio
    async def test_write_json_file_with_indent(self, tmp_path: Path) -> None:
        """write_json_file should respect indent parameter."""
        filepath = tmp_path / "output.json"
        data = {"key": "value"}

        await write_json_file(filepath, data, indent=4)

        content = filepath.read_text(encoding="utf-8")
        # 4-space indent results in "    " before "key"
        assert "    " in content

    @pytest.mark.asyncio
    async def test_write_json_file_nested_data(self, tmp_path: Path) -> None:
        """write_json_file should handle nested structures."""
        filepath = tmp_path / "nested.json"
        data = {
            "outer": {
                "inner": [1, 2, {"deep": True}],
            },
            "list": ["a", "b"],
        }

        await write_json_file(filepath, data)

        loaded = json.loads(filepath.read_text(encoding="utf-8"))
        assert loaded == data


class TestGenerateMarkdownReport:
    """Tests for generate_markdown_report utility."""

    def test_normalize_spacing(self) -> None:
        """Should collapse multiple newlines to double newlines."""
        content = "Header\n\n\n\nBody\n\n\n\n\nFooter"
        result = generate_markdown_report(content)
        assert result == "Header\n\nBody\n\nFooter\n"

    def test_trailing_newline(self) -> None:
        """Should ensure trailing newline."""
        result = generate_markdown_report("content")
        assert result.endswith("\n")

    def test_strips_whitespace(self) -> None:
        """Should strip leading and trailing whitespace."""
        result = generate_markdown_report("  content  ")
        assert result == "content\n"
