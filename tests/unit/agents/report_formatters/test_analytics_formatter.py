# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for AnalyticsReportFormatter.

Tests cover:
- Cost summary formatting
- Cost findings with savings estimates
- Multiple findings ranked by savings
- Visualization recommendations
- Chart metadata display
- Next steps
- Edge cases
"""

import pytest
from starboard_server.agents.report_formatters.analytics_formatter import (
    AnalyticsReportFormatter,
)


class TestAnalyticsReportFormatter:
    """Test AnalyticsReportFormatter markdown generation."""

    @pytest.fixture
    def formatter(self):
        """Create formatter instance."""
        return AnalyticsReportFormatter()

    def test_get_report_type(self, formatter):
        """Test that formatter reports correct type."""
        assert formatter.get_report_type() == "analytics"

    def test_minimal_report(self, formatter):
        """Test formatting minimal valid report."""
        report = {
            "report_type": "analytics",
            "summary": {
                "overview": "Cost analysis complete",
                "current_state": {"cloud_provider": "AWS"},
            },
            "findings": [
                {
                    "id": "finops_001",
                    "category": "COST_OPTIMIZATION",
                    "title": "Test finding",
                    "recommendation": "Test fix",
                    "cost_impact": {
                        "current_monthly_cost": 100.00,
                        "projected_savings_monthly": 50.00,
                        "cost_unit": "dollar",
                        "savings_pct": 50.0,
                        "confidence": "medium",
                    },
                    "effort": {"level": "low"},
                    "rank": 1,
                }
            ],
            "cost_summary": {
                "primary_metric": "list_cost",
                "primary_metric_unit": "USD",
                "total": 1000.00,
                "mean": 100.00,
                "max": 500.00,
                "cost_trend": "stable",
                "period": "30 days",
            },
            "next_steps": [
                {
                    "id": "next_1",
                    "number": 1,
                    "title": "Implement savings",
                    "description": "Apply cost optimization recommendations",
                    "action_type": "continue",
                }
            ],
        }

        result = formatter.format_to_markdown(report)

        assert "Summary" in result
        assert "Cost analysis complete" in result
        assert "Cost Overview" in result
        assert "Cost Optimization Opportunities" in result
        # NOTE: Next Steps are now rendered by frontend, not included in markdown output

    def test_cost_summary_formatting(self, formatter):
        """Test cost summary section formatting."""
        report = {
            "report_type": "analytics",
            "summary": {
                "overview": "Test",
                "current_state": {"cloud_provider": "AWS"},
            },
            "findings": [
                {
                    "id": "test",
                    "category": "COST_OPTIMIZATION",
                    "title": "Test",
                    "recommendation": "Test",
                    "cost_impact": {
                        "current_monthly_cost": 100.00,
                        "projected_savings_monthly": 50.00,
                        "cost_unit": "dollar",
                        "savings_pct": 50.0,
                        "confidence": "low",
                    },
                    "effort": {"level": "low"},
                    "rank": 1,
                }
            ],
            "cost_summary": {
                "primary_metric": "cost",
                "primary_metric_unit": "dollar",
                "total": 45000.00,
                "mean": 1500.00,
                "max": 5000.00,
                "cost_trend": "increasing",
                "period": "30 days",
                "top_contributors": [
                    {
                        "id": "wh_1",
                        "name": "warehouse_1",
                        "value": 15000.00,
                        "unit": "dollar",
                        "notes": None,
                    },
                    {
                        "id": "job_2",
                        "name": "job_2",
                        "value": 12000.00,
                        "unit": "dollar",
                        "notes": None,
                    },
                    {
                        "id": "cluster_3",
                        "name": "cluster_3",
                        "value": 10000.00,
                        "unit": "dollar",
                        "notes": None,
                    },
                ],
            },
            "next_steps": [
                {
                    "id": "next_1",
                    "number": 1,
                    "title": "Test",
                    "description": "Continue with implementation",
                    "action_type": "continue",
                }
            ],
        }

        result = formatter.format_to_markdown(report)

        assert "## Cost Overview" in result
        assert "45,000.00" in result  # Check for the numeric value
        assert "**Period:** 30 days" in result
        assert "📈" in result  # increasing trend emoji
        assert "Increasing" in result
        assert "**Top Contributors:**" in result
        assert "warehouse_1" in result
        assert "job_2" in result
        assert "cluster_3" in result

    def test_cost_trend_stable(self, formatter):
        """Test stable cost trend formatting."""
        report = {
            "report_type": "analytics",
            "summary": {
                "overview": "Test",
                "current_state": {"cloud_provider": "AWS"},
            },
            "findings": [
                {
                    "id": "test",
                    "category": "COST_OPTIMIZATION",
                    "title": "Test",
                    "recommendation": "Test",
                    "cost_impact": {
                        "current_monthly_cost": 100.00,
                        "projected_savings_monthly": 50.00,
                        "cost_unit": "dollar",
                        "savings_pct": 50.0,
                        "confidence": "low",
                    },
                    "effort": {"level": "low"},
                    "rank": 1,
                }
            ],
            "cost_summary": {
                "primary_metric": "cost",
                "primary_metric_unit": "dollar",
                "total": 1000.00,
                "mean": 100.00,
                "max": 500.00,
                "cost_trend": "stable",
                "period": "30 days",
            },
            "next_steps": [
                {
                    "id": "next_1",
                    "number": 1,
                    "title": "Test",
                    "description": "Continue with implementation",
                    "action_type": "continue",
                }
            ],
        }

        result = formatter.format_to_markdown(report)

        assert "➡️" in result  # stable trend emoji
        assert "Stable" in result

    def test_cost_trend_decreasing(self, formatter):
        """Test decreasing cost trend formatting."""
        report = {
            "report_type": "analytics",
            "summary": {
                "overview": "Test",
                "current_state": {"cloud_provider": "AWS"},
            },
            "findings": [
                {
                    "id": "test",
                    "category": "COST_OPTIMIZATION",
                    "title": "Test",
                    "recommendation": "Test",
                    "cost_impact": {
                        "current_monthly_cost": 100.00,
                        "projected_savings_monthly": 50.00,
                        "cost_unit": "dollar",
                        "savings_pct": 50.0,
                        "confidence": "low",
                    },
                    "effort": {"level": "low"},
                    "rank": 1,
                }
            ],
            "cost_summary": {
                "primary_metric": "cost",
                "primary_metric_unit": "dollar",
                "total": 1000.00,
                "mean": 143.00,
                "max": 300.00,
                "cost_trend": "decreasing",
                "period": "7 days",
            },
            "next_steps": [
                {
                    "id": "next_1",
                    "number": 1,
                    "title": "Test",
                    "description": "Continue with implementation",
                    "action_type": "continue",
                }
            ],
        }

        result = formatter.format_to_markdown(report)

        assert "📉" in result  # decreasing trend emoji
        assert "Decreasing" in result

    def test_cost_finding_formatting(self, formatter):
        """Test cost finding section formatting."""
        report = {
            "report_type": "analytics",
            "summary": {
                "overview": "Test",
                "current_state": {"cloud_provider": "AWS"},
            },
            "findings": [
                {
                    "id": "finops_001",
                    "category": "WASTE_DETECTION",
                    "title": "Idle warehouse consuming $2,400/month",
                    "recommendation": "Enable auto-stop after 10 minutes",
                    "cost_impact": {
                        "current_monthly_cost": 2400.00,
                        "projected_savings_monthly": 2040.00,
                        "cost_unit": "dollar",
                        "savings_pct": 85.0,
                        "confidence": "high",
                    },
                    "effort": {"level": "low", "estimate_hours": 0.5},
                    "risks": ["10-minute startup delay when first query runs"],
                    "rank": 1,
                }
            ],
            "cost_summary": {
                "primary_metric": "cost",
                "primary_metric_unit": "dollar",
                "total": 2400.00,
                "mean": 80.00,
                "max": 200.00,
                "cost_trend": "stable",
                "period": "30 days",
            },
            "next_steps": [
                {
                    "id": "next_1",
                    "number": 1,
                    "title": "Implement auto-stop",
                    "description": "Configure automatic stopping for idle resources",
                    "action_type": "continue",
                }
            ],
        }

        result = formatter.format_to_markdown(report)

        assert "## Cost Optimization Opportunities" in result
        assert "### 1. Idle warehouse consuming $2,400/month" in result
        assert "**Category:** Waste Detection" in result
        assert "Enable auto-stop after 10 minutes" in result
        assert "**Current Monthly Cost:** $2,400.00" in result
        assert "**Projected Savings:** $2,040.00/month (85%)" in result
        assert "**Confidence:** High" in result
        assert "**Effort:** Low (~0.5h)" in result
        # Risks section is present if risks are defined - check in formatter implementation

    def test_multiple_findings_ranked(self, formatter):
        """Test multiple findings ranked by savings."""
        report = {
            "report_type": "analytics",
            "summary": {
                "overview": "Multiple opportunities found",
                "current_state": {"cloud_provider": "AWS"},
            },
            "findings": [
                {
                    "id": "finops_001",
                    "category": "WASTE_DETECTION",
                    "title": "High-value opportunity",
                    "recommendation": "Fix 1",
                    "cost_impact": {
                        "current_monthly_cost": 2000.00,
                        "projected_savings_monthly": 1800.00,
                        "cost_unit": "dollar",
                        "savings_pct": 90.0,
                        "confidence": "high",
                    },
                    "effort": {"level": "low"},
                    "rank": 1,
                },
                {
                    "id": "finops_002",
                    "category": "UTILIZATION",
                    "title": "Medium-value opportunity",
                    "recommendation": "Fix 2",
                    "cost_impact": {
                        "current_monthly_cost": 1000.00,
                        "projected_savings_monthly": 500.00,
                        "cost_unit": "dollar",
                        "savings_pct": 50.0,
                        "confidence": "medium",
                    },
                    "effort": {"level": "medium"},
                    "rank": 2,
                },
                {
                    "id": "finops_003",
                    "category": "PERFORMANCE_COST",
                    "title": "Low-value opportunity",
                    "recommendation": "Fix 3",
                    "cost_impact": {
                        "current_monthly_cost": 500.00,
                        "projected_savings_monthly": 100.00,
                        "cost_unit": "dollar",
                        "savings_pct": 20.0,
                        "confidence": "low",
                    },
                    "effort": {"level": "high"},
                    "rank": 3,
                },
            ],
            "cost_summary": {
                "primary_metric": "cost",
                "primary_metric_unit": "dollar",
                "total": 3500.00,
                "mean": 116.67,
                "max": 350.00,
                "cost_trend": "increasing",
                "period": "30 days",
            },
            "next_steps": [
                {
                    "id": "next_1",
                    "number": 1,
                    "title": "Implement top savings",
                    "description": "Apply highest-impact cost optimizations",
                    "action_type": "continue",
                }
            ],
        }

        result = formatter.format_to_markdown(report)

        assert "### 1. High-value opportunity" in result
        assert "### 2. Medium-value opportunity" in result
        assert "### 3. Low-value opportunity" in result
        assert "$1,800.00/month (90%)" in result
        assert "$500.00/month (50%)" in result
        assert "$100.00/month (20%)" in result

    def test_finding_without_risks(self, formatter):
        """Test finding without risks field."""
        report = {
            "report_type": "analytics",
            "summary": {
                "overview": "Test",
                "current_state": {"cloud_provider": "AWS"},
            },
            "findings": [
                {
                    "id": "finops_001",
                    "category": "COST_OPTIMIZATION",
                    "title": "Low-risk change",
                    "recommendation": "Apply fix",
                    "cost_impact": {
                        "current_monthly_cost": 500.00,
                        "projected_savings_monthly": 250.00,
                        "cost_unit": "dollar",
                        "savings_pct": 50.0,
                        "confidence": "high",
                    },
                    "effort": {"level": "low"},
                    # No risks specified
                    "rank": 1,
                }
            ],
            "cost_summary": {
                "primary_metric": "cost",
                "primary_metric_unit": "dollar",
                "total": 500.00,
                "mean": 16.67,
                "max": 50.00,
                "cost_trend": "stable",
                "period": "30 days",
            },
            "next_steps": [
                {
                    "id": "next_1",
                    "number": 1,
                    "title": "Implement",
                    "description": "Continue with implementation",
                    "action_type": "continue",
                }
            ],
        }

        result = formatter.format_to_markdown(report)

        assert "**Risks:**" not in result  # No risks section

    def test_visualization_recommendation(self, formatter):
        """Test visualization recommendation section.

        Note: Visualization section is commented out in formatter for CLI/console output.
        """
        report = {
            "report_type": "analytics",
            "summary": {
                "overview": "Test",
                "current_state": {"cloud_provider": "AWS"},
            },
            "findings": [
                {
                    "id": "test",
                    "category": "COST_OPTIMIZATION",
                    "title": "Test",
                    "recommendation": "Test",
                    "cost_impact": {
                        "current_monthly_cost": 100.00,
                        "projected_savings_monthly": 50.00,
                        "cost_unit": "dollar",
                        "savings_pct": 50.0,
                        "confidence": "low",
                    },
                    "effort": {"level": "low"},
                    "rank": 1,
                }
            ],
            "cost_summary": {
                "primary_metric": "cost",
                "primary_metric_unit": "dollar",
                "total": 1000.00,
                "mean": 100.00,
                "max": 500.00,
                "cost_trend": "stable",
                "period": "30 days",
            },
            "visualization": {
                "recommended_chart": "line",
                "primary_metric": "total_cost",
                "primary_dimension": "usage_date",
                "time_dimension": "usage_date",
                "notes": "Use line chart to show cost trends over time",
            },
            "next_steps": [
                {
                    "id": "next_1",
                    "number": 1,
                    "title": "Test",
                    "description": "Continue with implementation",
                    "action_type": "continue",
                }
            ],
        }

        result = formatter.format_to_markdown(report)

        # Visualization section is intentionally hidden for CLI
        # Just ensure report generates without errors
        assert "## Summary" in result
        assert "## Cost Overview" in result

    def test_visualization_without_time_dimension(self, formatter):
        """Test visualization without time dimension.

        Note: Visualization section is commented out in formatter for CLI/console output.
        """
        report = {
            "report_type": "analytics",
            "summary": {
                "overview": "Test",
                "current_state": {"cloud_provider": "AWS"},
            },
            "findings": [
                {
                    "id": "test",
                    "category": "COST_OPTIMIZATION",
                    "title": "Test",
                    "recommendation": "Test",
                    "cost_impact": {
                        "current_monthly_cost": 100.00,
                        "projected_savings_monthly": 50.00,
                        "cost_unit": "dollar",
                        "savings_pct": 50.0,
                        "confidence": "low",
                    },
                    "effort": {"level": "low"},
                    "rank": 1,
                }
            ],
            "cost_summary": {
                "primary_metric": "cost",
                "primary_metric_unit": "dollar",
                "total": 1000.00,
                "mean": 100.00,
                "max": 500.00,
                "cost_trend": "stable",
                "period": "30 days",
            },
            "visualization": {
                "recommended_chart": "bar",
                "primary_metric": "cost",
                "primary_dimension": "resource_name",
                # No time_dimension
                "notes": "Bar chart for resource comparison",
            },
            "next_steps": [
                {
                    "id": "next_1",
                    "number": 1,
                    "title": "Test",
                    "description": "Continue with implementation",
                    "action_type": "continue",
                }
            ],
        }

        result = formatter.format_to_markdown(report)

        # Visualization section is intentionally hidden for CLI
        # Just ensure report generates without errors
        assert "## Summary" in result
        assert "## Cost Overview" in result

    def test_no_visualization(self, formatter):
        """Test report without visualization recommendation."""
        report = {
            "report_type": "analytics",
            "summary": {
                "overview": "Test",
                "current_state": {"cloud_provider": "AWS"},
            },
            "findings": [
                {
                    "id": "test",
                    "category": "COST_OPTIMIZATION",
                    "title": "Test",
                    "recommendation": "Test",
                    "cost_impact": {
                        "current_monthly_cost": 100.00,
                        "projected_savings_monthly": 50.00,
                        "cost_unit": "dollar",
                        "savings_pct": 50.0,
                        "confidence": "low",
                    },
                    "effort": {"level": "low"},
                    "rank": 1,
                }
            ],
            "cost_summary": {
                "primary_metric": "cost",
                "primary_metric_unit": "dollar",
                "total": 1000.00,
                "mean": 100.00,
                "max": 500.00,
                "cost_trend": "stable",
                "period": "30 days",
            },
            # No visualization
            "next_steps": [
                {
                    "id": "next_1",
                    "number": 1,
                    "title": "Test",
                    "description": "Continue with implementation",
                    "action_type": "continue",
                }
            ],
        }

        result = formatter.format_to_markdown(report)

        assert "## 📊 Recommended Visualization" not in result

    def test_cost_summary_without_contributors(self, formatter):
        """Test cost summary without top contributors."""
        report = {
            "report_type": "analytics",
            "summary": {
                "overview": "Test",
                "current_state": {"cloud_provider": "AWS"},
            },
            "findings": [
                {
                    "id": "test",
                    "category": "COST_OPTIMIZATION",
                    "title": "Test",
                    "recommendation": "Test",
                    "cost_impact": {
                        "current_monthly_cost": 100.00,
                        "projected_savings_monthly": 50.00,
                        "cost_unit": "dollar",
                        "savings_pct": 50.0,
                        "confidence": "low",
                    },
                    "effort": {"level": "low"},
                    "rank": 1,
                }
            ],
            "cost_summary": {
                "primary_metric": "cost",
                "primary_metric_unit": "dollar",
                "total": 1000.00,
                "mean": 100.00,
                "max": 500.00,
                "cost_trend": "stable",
                "period": "30 days",
                # No top_contributors
            },
            "next_steps": [
                {
                    "id": "next_1",
                    "number": 1,
                    "title": "Test",
                    "description": "Continue with implementation",
                    "action_type": "continue",
                }
            ],
        }

        result = formatter.format_to_markdown(report)

        assert "## Cost Overview" in result
        assert "1,000.00" in result  # Check for the numeric value
        assert "**Top Contributors:**" not in result  # No contributors section

    def test_category_formatting(self, formatter):
        """Test that category names are properly formatted."""
        report = {
            "report_type": "analytics",
            "summary": {
                "overview": "Test",
                "current_state": {"cloud_provider": "AWS"},
            },
            "findings": [
                {
                    "id": "finops_001",
                    "category": "WASTE_DETECTION",
                    "title": "Test",
                    "recommendation": "Test",
                    "cost_impact": {
                        "current_monthly_cost": 100.00,
                        "projected_savings_monthly": 50.00,
                        "cost_unit": "dollar",
                        "savings_pct": 50.0,
                        "confidence": "low",
                    },
                    "effort": {"level": "low"},
                    "rank": 1,
                }
            ],
            "cost_summary": {
                "primary_metric": "cost",
                "primary_metric_unit": "dollar",
                "total": 1000.00,
                "mean": 100.00,
                "max": 500.00,
                "cost_trend": "stable",
                "period": "30 days",
            },
            "next_steps": [
                {
                    "id": "next_1",
                    "number": 1,
                    "title": "Test",
                    "description": "Continue with implementation",
                    "action_type": "continue",
                }
            ],
        }

        result = formatter.format_to_markdown(report)

        # WASTE_DETECTION should become "Waste Detection"
        assert "**Category:** Waste Detection" in result

    def test_invalid_report_dict(self, formatter):
        """Test handling of invalid report structure."""
        report = {"report_type": "analytics"}  # Missing required fields

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

    def test_new_cost_summary_schema(self, formatter):
        """Test new cost summary schema with primary_metric and DBU units."""
        report = {
            "report_type": "analytics",
            "summary": {
                "overview": "DBU usage analysis",
                "current_state": {"cloud_provider": "AWS"},
            },
            "findings": [
                {
                    "id": "finops_001",
                    "category": "UTILIZATION",
                    "title": "High DBU consumption",
                    "recommendation": "Optimize job configuration",
                    "cost_impact": {
                        "current_monthly_cost": 1000.00,
                        "projected_savings_monthly": 200.00,
                        "cost_unit": "dbu",
                        "savings_pct": 20.0,
                        "confidence": "medium",
                    },
                    "effort": {"level": "medium"},
                    "rank": 1,
                }
            ],
            "cost_summary": {
                "primary_metric": "run_dbus",
                "primary_metric_unit": "DBU",
                "total": 11.67,
                "mean": 3.89,
                "max": 8.50,
                "cost_trend": "increasing",
                "period": "30 days",
                "top_contributors": [
                    {
                        "id": "job_123",
                        "name": "ETL Pipeline",
                        "value": 5.84,
                        "unit": "DBU",
                        "notes": "31 runs",
                    }
                ],
            },
            "next_steps": [
                {
                    "id": "step_1",
                    "number": 1,
                    "title": "Optimize expensive job",
                    "description": "Review job configuration for cost reduction",
                    "action_type": "route",
                    "target_agent": "job",
                    "tool_name": None,
                    "parameters": {"job_id": "123"},
                }
            ],
        }

        result = formatter.format_to_markdown(report)

        # Check DBU formatting
        assert "**Total DBUs:** 11.67" in result
        assert "**Average:** 3.89 DBUs" in result
        assert "**Maximum:** 8.50 DBUs" in result

        # Check top contributor formatting
        assert "**Top Contributors:**" in result
        assert "ETL Pipeline: 5.84 DBUs (31 runs)" in result

        # Check cost impact with DBU unit
        assert "**Current Monthly Usage:** 1,000.00 DBUs" in result
        assert "**Projected Savings:** 200.00 DBUs/month (20%)" in result

        # NOTE: Next Steps are now rendered by frontend, not included in markdown output

    def test_backward_compatible_cost_summary(self, formatter):
        """Test backward compatibility with old cost_summary schema."""
        report = {
            "report_type": "analytics",
            "summary": {
                "overview": "Old schema test",
                "current_state": {"cloud_provider": "AWS"},
            },
            "findings": [
                {
                    "id": "finops_001",
                    "category": "COST_OPTIMIZATION",
                    "title": "Test",
                    "recommendation": "Test",
                    "cost_impact": {
                        "current_monthly_cost": 100.00,
                        "projected_savings_monthly": 50.00,
                        "cost_unit": "dollar",
                        "savings_pct": 50.0,
                        "confidence": "medium",
                    },
                    "effort": {"level": "low"},
                    "rank": 1,
                }
            ],
            "cost_summary": {
                "primary_metric": "cost",
                "primary_metric_unit": "dollar",
                "total": 1000.00,
                "mean": 100.00,
                "max": 500.00,
                "cost_trend": "stable",
                "period": "30 days",
            },
            "next_steps": [
                {
                    "id": "next_1",
                    "number": 1,
                    "title": "Implement",
                    "description": "Continue with implementation",
                    "action_type": "continue",
                }
            ],
        }

        result = formatter.format_to_markdown(report)

        # Should still format properly with backward compatibility
        assert "## Cost Overview" in result
        assert "1,000.00" in result  # Check for the numeric value
