"""Tests for AdvisorReportFormatter.

Tests cover:
- Basic markdown formatting
- Summary section with current state
- Findings/recommendations section
- Impact estimates
- Effort estimates
- Fixes/code snippets
- Query rewrites
- Next steps
- Edge cases (empty data, missing fields)
"""

import pytest
from starboard_server.agents.report_formatters.advisor_formatter import (
    AdvisorReportFormatter,
)


class TestAdvisorReportFormatter:
    """Test AdvisorReportFormatter markdown generation."""

    @pytest.fixture
    def formatter(self):
        """Create formatter instance."""
        return AdvisorReportFormatter()

    def test_get_report_type(self, formatter):
        """Test that formatter reports correct type."""
        assert formatter.get_report_type() == "advisor"

    def test_minimal_report(self, formatter):
        """Test formatting minimal valid report."""
        report = {
            "report_type": "advisor",
            "summary": {
                "overview": "Test overview",
                "current_state": {"cloud_provider": "AWS"},
            },
            "analysis": {"findings": []},
            "next_steps": [
                {
                    "id": "test_1",
                    "number": 1,
                    "title": "Test action",
                    "description": "Test description",
                    "action_type": "continue",
                    "target_agent": None,
                    "tool_name": None,
                    "parameters": None,
                }
            ],
        }

        result = formatter.format_to_markdown(report)

        assert "## Summary" in result
        assert "Test overview" in result
        # NOTE: Next Steps are now rendered by frontend, not included in markdown output

    def test_summary_with_symptoms(self, formatter):
        """Test summary formatting with key symptoms."""
        report = {
            "report_type": "advisor",
            "summary": {
                "overview": "Query performance issues detected",
                "current_state": {
                    "cloud_provider": "AWS",
                    "key_symptoms": ["High scan times", "No predicate pushdown"],
                },
            },
            "analysis": {"findings": []},
            "next_steps": [
                {
                    "id": "add_index_1",
                    "number": 1,
                    "title": "Add index",
                    "description": None,
                    "action_type": "continue",
                    "target_agent": None,
                    "tool_name": None,
                    "parameters": None,
                }
            ],
        }

        result = formatter.format_to_markdown(report)

        assert "## Summary" in result
        assert "Query performance issues detected" in result
        assert "**Key Symptoms:**" in result
        assert "High scan times" in result
        assert "No predicate pushdown" in result

    def test_single_finding(self, formatter):
        """Test formatting single finding."""
        report = {
            "report_type": "advisor",
            "summary": {
                "overview": "Test",
                "current_state": {"cloud_provider": "AWS"},
            },
            "analysis": {
                "findings": [
                    {
                        "id": "finding_001",
                        "category": "QUERY",
                        "title": "Add index on user_id column",
                        "recommendation": "Create index to speed up lookups",
                        "proofs": {"evidence": ["Full table scan detected"]},
                        "impact_estimate": {
                            "query_time_pct": -50.0,
                            "cost_pct": -30.0,
                            "confidence": "high",
                        },
                        "effort": {"level": "low", "estimate_hours": 0.5},
                        "rank": 1,
                    }
                ]
            },
            "next_steps": [
                {
                    "id": "implement_1",
                    "number": 1,
                    "title": "Implement index",
                    "description": None,
                    "action_type": "continue",
                    "target_agent": None,
                    "tool_name": None,
                    "parameters": None,
                }
            ],
        }

        result = formatter.format_to_markdown(report)

        assert "## Recommendations" in result
        assert "### 1. Add index on user_id column" in result
        assert "**Category:** QUERY" in result
        assert "Create index to speed up lookups" in result
        assert "**Impact:**" in result
        assert "50% faster" in result
        assert "30% cheaper" in result
        assert "high confidence" in result
        assert "**Effort:** Low" in result
        assert "0.5" in result

    def test_multiple_findings(self, formatter):
        """Test formatting multiple findings."""
        report = {
            "report_type": "advisor",
            "summary": {
                "overview": "Multiple optimization opportunities",
                "current_state": {"cloud_provider": "AWS"},
            },
            "analysis": {
                "findings": [
                    {
                        "id": "finding_001",
                        "category": "QUERY",
                        "title": "First finding",
                        "recommendation": "First fix",
                        "proofs": {},
                        "impact_estimate": {
                            "query_time_pct": -40.0,
                            "confidence": "high",
                        },
                        "effort": {"level": "low"},
                        "rank": 1,
                    },
                    {
                        "id": "finding_002",
                        "category": "TABLE",
                        "title": "Second finding",
                        "recommendation": "Second fix",
                        "proofs": {},
                        "impact_estimate": {
                            "query_time_pct": -20.0,
                            "confidence": "medium",
                        },
                        "effort": {"level": "medium"},
                        "rank": 2,
                    },
                ]
            },
            "next_steps": [
                {
                    "id": "apply_1",
                    "number": 1,
                    "title": "Apply first fix",
                    "description": None,
                    "action_type": "continue",
                    "target_agent": None,
                    "tool_name": None,
                    "parameters": None,
                },
                {
                    "id": "apply_2",
                    "number": 2,
                    "title": "Apply second fix",
                    "description": None,
                    "action_type": "continue",
                    "target_agent": None,
                    "tool_name": None,
                    "parameters": None,
                },
            ],
        }

        result = formatter.format_to_markdown(report)

        assert "## Recommendations" in result
        assert "### 1. First finding" in result
        assert "### 2. Second finding" in result
        assert "**Category:** QUERY" in result
        assert "**Category:** TABLE" in result
        assert "40% faster" in result
        assert "20% faster" in result

    def test_finding_with_fixes(self, formatter):
        """Test formatting finding with code fixes."""
        report = {
            "report_type": "advisor",
            "summary": {
                "overview": "Test",
                "current_state": {"cloud_provider": "AWS"},
            },
            "analysis": {
                "findings": [
                    {
                        "id": "finding_001",
                        "category": "QUERY",
                        "title": "Optimize JOIN",
                        "recommendation": "Use broadcast join",
                        "proofs": {},
                        "impact_estimate": {
                            "query_time_pct": -30.0,
                            "confidence": "high",
                        },
                        "effort": {"level": "low"},
                        "fixes": [
                            {
                                "type": "SQL_REWRITE",
                                "snippet": "SELECT /*+ BROADCAST(t2) */ * FROM t1 JOIN t2",
                                "notes": "Using broadcast join for small table",
                            }
                        ],
                        "rank": 1,
                    }
                ]
            },
            "next_steps": [
                {
                    "id": "apply_1",
                    "number": 1,
                    "title": "Apply fix",
                    "description": None,
                    "action_type": "continue",
                    "target_agent": None,
                    "tool_name": None,
                    "parameters": None,
                }
            ],
        }

        result = formatter.format_to_markdown(report)

        assert "**Suggested Changes:**" in result
        assert "```sql" in result
        assert "BROADCAST(t2)" in result
        assert "```" in result
        assert "Using broadcast join" in result

    def test_query_rewrite_section(self, formatter):
        """Test query rewrite section formatting."""
        report = {
            "report_type": "advisor",
            "summary": {
                "overview": "Test",
                "current_state": {"cloud_provider": "AWS"},
            },
            "analysis": {
                "findings": [],
                "query_rewrite": {
                    "applicable": True,
                    "sql": "SELECT * FROM users WHERE id = 123",
                    "notes": "Optimized query with predicate pushdown",
                },
            },
            "next_steps": [
                {
                    "id": "rewrite_1",
                    "number": 1,
                    "title": "Apply rewrite",
                    "description": None,
                    "action_type": "continue",
                    "target_agent": None,
                    "tool_name": None,
                    "parameters": None,
                }
            ],
        }

        result = formatter.format_to_markdown(report)

        assert "## Optimized Query" in result
        assert "```sql" in result
        assert "SELECT * FROM users WHERE id = 123" in result
        assert "Optimized query with predicate pushdown" in result

    def test_query_rewrite_not_applicable(self, formatter):
        """Test that non-applicable query rewrite is not shown."""
        report = {
            "report_type": "advisor",
            "summary": {
                "overview": "Test",
                "current_state": {"cloud_provider": "AWS"},
            },
            "analysis": {
                "findings": [],
                "query_rewrite": {
                    "applicable": False,
                    "sql": "",
                    "notes": "Query already optimal",
                },
            },
            "next_steps": [
                {
                    "id": "none_1",
                    "number": 1,
                    "title": "None needed",
                    "description": None,
                    "action_type": "continue",
                    "target_agent": None,
                    "tool_name": None,
                    "parameters": None,
                }
            ],
        }

        result = formatter.format_to_markdown(report)

        assert "## Optimized Query" not in result

    def test_impact_estimate_positive_values(self, formatter):
        """Test impact estimate with positive values (worse performance)."""
        report = {
            "report_type": "advisor",
            "summary": {
                "overview": "Test",
                "current_state": {"cloud_provider": "AWS"},
            },
            "analysis": {
                "findings": [
                    {
                        "id": "finding_001",
                        "category": "WARNING",
                        "title": "Potential regression",
                        "recommendation": "Review carefully",
                        "proofs": {},
                        "impact_estimate": {
                            "query_time_pct": 25.0,  # Slower!
                            "cost_pct": 15.0,  # More expensive!
                            "confidence": "medium",
                        },
                        "effort": {"level": "high"},
                        "rank": 1,
                    }
                ]
            },
            "next_steps": [
                {
                    "id": "test_1",
                    "number": 1,
                    "title": "Test thoroughly",
                    "description": None,
                    "action_type": "continue",
                    "target_agent": None,
                    "tool_name": None,
                    "parameters": None,
                }
            ],
        }

        result = formatter.format_to_markdown(report)

        assert "25% slower" in result
        assert "15% more expensive" in result

    def test_effort_without_hours(self, formatter):
        """Test effort estimate without hours."""
        report = {
            "report_type": "advisor",
            "summary": {
                "overview": "Test",
                "current_state": {"cloud_provider": "AWS"},
            },
            "analysis": {
                "findings": [
                    {
                        "id": "finding_001",
                        "category": "QUERY",
                        "title": "Test finding",
                        "recommendation": "Test fix",
                        "proofs": {},
                        "impact_estimate": {
                            "query_time_pct": -10.0,
                            "confidence": "low",
                        },
                        "effort": {"level": "medium"},  # No hours specified
                        "rank": 1,
                    }
                ]
            },
            "next_steps": [
                {
                    "id": "test_1",
                    "number": 1,
                    "title": "Test",
                    "description": None,
                    "action_type": "continue",
                    "target_agent": None,
                    "tool_name": None,
                    "parameters": None,
                }
            ],
        }

        result = formatter.format_to_markdown(report)

        assert "**Effort:** Medium" in result
        assert "hours" not in result.lower()

    def test_empty_findings(self, formatter):
        """Test report with no findings."""
        report = {
            "report_type": "advisor",
            "summary": {
                "overview": "No issues found",
                "current_state": {"cloud_provider": "AWS"},
            },
            "analysis": {"findings": []},
            "next_steps": [
                {
                    "id": "monitor_1",
                    "number": 1,
                    "title": "Continue monitoring",
                    "description": None,
                    "action_type": "continue",
                    "target_agent": None,
                    "tool_name": None,
                    "parameters": None,
                }
            ],
        }

        result = formatter.format_to_markdown(report)

        assert "## Summary" in result
        assert "No issues found" in result
        assert "## Recommendations" not in result  # No findings section
        # NOTE: Next Steps are now rendered by frontend, not included in markdown output

    def test_missing_optional_fields(self, formatter):
        """Test finding with missing optional fields."""
        report = {
            "report_type": "advisor",
            "summary": {
                "overview": "Test",
                "current_state": {"cloud_provider": "AWS"},
            },
            "analysis": {
                "findings": [
                    {
                        "id": "finding_001",
                        "category": "QUERY",
                        "title": "Simple finding",
                        # No recommendation
                        "proofs": {},
                        "impact_estimate": {
                            "query_time_pct": 0,  # Zero impact
                            "cost_pct": 0,
                            "confidence": "low",
                        },
                        "effort": {},  # Empty effort
                        "rank": 1,
                    }
                ]
            },
            "next_steps": [
                {
                    "id": "review_1",
                    "number": 1,
                    "title": "Review",
                    "description": None,
                    "action_type": "continue",
                    "target_agent": None,
                    "tool_name": None,
                    "parameters": None,
                }
            ],
        }

        result = formatter.format_to_markdown(report)

        # Should still render without errors
        assert "## Recommendations" in result
        assert "### 1. Simple finding" in result
        # Impact should not be shown (zero values)
        assert "**Impact:**" not in result

    def test_multiple_next_steps(self, formatter):
        """Test formatting multiple next steps."""
        report = {
            "report_type": "advisor",
            "summary": {
                "overview": "Test",
                "current_state": {"cloud_provider": "AWS"},
            },
            "analysis": {"findings": []},
            "next_steps": [
                {
                    "id": "first_1",
                    "number": 1,
                    "title": "First step",
                    "description": None,
                    "action_type": "continue",
                    "target_agent": None,
                    "tool_name": None,
                    "parameters": None,
                },
                {
                    "id": "second_2",
                    "number": 2,
                    "title": "Second step",
                    "description": None,
                    "action_type": "continue",
                    "target_agent": None,
                    "tool_name": None,
                    "parameters": None,
                },
                {
                    "id": "third_3",
                    "number": 3,
                    "title": "Third step",
                    "description": None,
                    "action_type": "continue",
                    "target_agent": None,
                    "tool_name": None,
                    "parameters": None,
                },
            ],
        }

        result = formatter.format_to_markdown(report)

        # NOTE: Next Steps are now rendered by frontend, not included in markdown output
        assert "## Summary" in result
        assert "Test" in result

    def test_invalid_report_dict(self, formatter):
        """Test handling of invalid report structure."""
        # Missing required fields
        report = {"report_type": "advisor"}

        result = formatter.format_to_markdown(report)

        # Should return fallback message without crashing
        assert isinstance(result, str)
        assert len(result) > 0

    def test_empty_report(self, formatter):
        """Test handling of empty report dict."""
        report = {}

        result = formatter.format_to_markdown(report)

        # Should return fallback message
        assert isinstance(result, str)
        assert len(result) > 0
