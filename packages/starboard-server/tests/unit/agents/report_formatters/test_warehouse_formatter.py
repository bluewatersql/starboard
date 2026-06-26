# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for WarehouseReportFormatter.

Tests cover:
- Markdown generation for all sections
- Empty/missing section handling
- Edge cases and error handling
- Protocol compliance
"""

from starboard_server.agents.report_formatters.warehouse_formatter import (
    WarehouseReportFormatter,
)


class TestWarehouseReportFormatterProtocol:
    """Tests for ReportFormatter protocol compliance."""

    def test_get_report_type_returns_warehouse(self):
        """Test that formatter reports 'warehouse' type."""
        formatter = WarehouseReportFormatter()
        assert formatter.get_report_type() == "warehouse"


class TestWarehouseReportFormatterSummary:
    """Tests for summary section formatting."""

    def test_format_summary_section(self):
        """Test summary section is formatted correctly."""
        formatter = WarehouseReportFormatter()
        report = {
            "report_type": "warehouse",
            "summary": {
                "overview": "Portfolio analysis complete. 5 warehouses analyzed.",
                "current_state": {
                    "cloud_provider": "AWS",
                    "resource_type": "warehouse",
                    "key_symptoms": ["High queue times", "Low utilization"],
                },
            },
        }

        result = formatter.format_to_markdown(report)

        assert "## Summary" in result
        assert "Portfolio analysis complete" in result
        assert "High queue times" in result or "Key Observations" in result

    def test_format_empty_summary(self):
        """Test handling of missing summary."""
        formatter = WarehouseReportFormatter()
        report = {"report_type": "warehouse"}

        result = formatter.format_to_markdown(report)

        assert "Analysis complete." in result


class TestWarehouseReportFormatterPortfolio:
    """Tests for portfolio summary formatting."""

    def test_format_portfolio_summary(self):
        """Test portfolio summary section."""
        formatter = WarehouseReportFormatter()
        report = {
            "report_type": "warehouse",
            "summary": {"overview": "Test"},
            "portfolio_summary": {
                "total_count": 5,
                "health_distribution": {
                    "healthy": 3,
                    "warning": 1,
                    "critical": 1,
                    "inactive": 0,
                },
                "top_resources": [
                    {
                        "id": "wh_1",
                        "name": "analytics-warehouse",
                        "resource_type": "warehouse",
                        "health_score": 90,
                        "health_status": "healthy",
                    },
                ],
            },
        }

        result = formatter.format_to_markdown(report)

        assert "## Portfolio Overview" in result
        assert "Total Resources" in result
        assert "5" in result
        assert "Healthy" in result
        assert "analytics-warehouse" in result


class TestWarehouseReportFormatterHealth:
    """Tests for health metrics formatting."""

    def test_format_health_metrics(self):
        """Test health metrics section."""
        formatter = WarehouseReportFormatter()
        report = {
            "report_type": "warehouse",
            "summary": {"overview": "Test"},
            "health_metrics": {
                "overall_score": 78,
                "metric_scores": {
                    "latency": 85,
                    "availability": 95,
                    "queue_time": 60,
                    "error_rate": 90,
                },
                "slo_compliance": {
                    "targets_met": 3,
                    "targets_total": 4,
                },
                "risk_factors": ["High queue times during peak hours"],
            },
        }

        result = formatter.format_to_markdown(report)

        assert "## Health Analysis" in result
        assert "78" in result
        assert "Latency" in result
        assert "SLO Compliance" in result
        assert "High queue times" in result


class TestWarehouseReportFormatterTopology:
    """Tests for topology analysis formatting."""

    def test_format_topology_analysis(self):
        """Test topology analysis section."""
        formatter = WarehouseReportFormatter()
        report = {
            "report_type": "warehouse",
            "summary": {"overview": "Test"},
            "topology_analysis": {
                "clusters": [
                    {
                        "id": "cluster_1",
                        "name": "BI Workloads",
                        "resources": ["wh_1", "wh_2"],
                        "similarity_score": 0.85,
                    },
                ],
                "consolidation_opportunities": [
                    {
                        "source_resources": ["wh_1", "wh_2"],
                        "target_resource": "wh_3",
                        "estimated_savings_pct": 25.0,
                        "confidence": "medium",
                        "recommendation": "Consolidate BI warehouses",
                    },
                ],
            },
        }

        result = formatter.format_to_markdown(report)

        assert "## Topology Analysis" in result
        assert "BI Workloads" in result
        assert "85%" in result
        assert "Consolidate BI warehouses" in result
        assert "25%" in result


class TestWarehouseReportFormatterUserActivity:
    """Tests for user activity formatting."""

    def test_format_user_activity(self):
        """Test user activity section."""
        formatter = WarehouseReportFormatter()
        report = {
            "report_type": "warehouse",
            "summary": {"overview": "Test"},
            "user_activity": {
                "period": "30 days",
                "top_users": [
                    {
                        "user_email": "alice@example.com",
                        "query_count": 500,
                        "total_runtime_seconds": 3600.0,
                        "bytes_scanned": 1_000_000_000,
                        "cost_attribution_pct": 35.5,
                    },
                ],
                "allocation_method": "runtime",
            },
        }

        result = formatter.format_to_markdown(report)

        assert "## User Activity" in result
        assert "30 days" in result
        assert "alice@example.com" in result
        assert "500" in result
        assert "35.5%" in result


class TestWarehouseReportFormatterFindings:
    """Tests for performance findings formatting."""

    def test_format_analysis_findings(self):
        """Test analysis findings section (advisor format)."""
        formatter = WarehouseReportFormatter()
        report = {
            "report_type": "warehouse",
            "summary": {"overview": "Test"},
            "analysis": {
                "findings": [
                    {
                        "id": "finding_001",
                        "category": "WAREHOUSE",
                        "title": "Warehouse oversized for workload",
                        "recommendation": "Consider downsizing to medium",
                    },
                ],
            },
        }

        result = formatter.format_to_markdown(report)

        assert "### Performance Recommendations" in result
        assert "Warehouse oversized for workload" in result
        assert "Consider downsizing to medium" in result


class TestWarehouseReportFormatterEdgeCases:
    """Tests for edge cases and error handling."""

    def test_invalid_report_type_returns_default(self):
        """Test handling of non-dict report."""
        formatter = WarehouseReportFormatter()

        result = formatter.format_to_markdown("not a dict")

        assert result == "Analysis complete."

    def test_empty_report_returns_default(self):
        """Test handling of empty report dict."""
        formatter = WarehouseReportFormatter()

        result = formatter.format_to_markdown({})

        assert result == "Analysis complete."

    def test_all_sections_combined(self):
        """Test report with all sections present."""
        formatter = WarehouseReportFormatter()
        report = {
            "report_type": "warehouse",
            "summary": {"overview": "Complete analysis"},
            "portfolio_summary": {
                "total_count": 3,
                "health_distribution": {"healthy": 2, "warning": 1},
            },
            "health_metrics": {"overall_score": 80},
            "topology_analysis": {"clusters": [], "consolidation_opportunities": []},
            "user_activity": {"period": "7 days", "top_users": []},
        }

        result = formatter.format_to_markdown(report)

        # All sections should be present
        assert "## Summary" in result
        assert "## Portfolio Overview" in result
        assert "## Health Analysis" in result
        assert "## Topology Analysis" in result
        assert "## User Activity" in result
