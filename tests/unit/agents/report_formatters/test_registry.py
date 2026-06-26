# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for ReportFormatterRegistry.

Tests cover:
- Formatter registration
- Formatter retrieval
- Report formatting dispatch
- Error handling
- Global registry usage
"""

import pytest
from starboard_server.agents.report_formatters import (
    AdvisorReportFormatter,
    AnalyticsReportFormatter,
    ReportFormatterRegistry,
    format_agent_report,
    get_formatter_registry,
)


class TestReportFormatterRegistry:
    """Test ReportFormatterRegistry functionality."""

    @pytest.fixture
    def registry(self):
        """Create fresh registry for testing."""
        return ReportFormatterRegistry()

    def test_register_formatter(self, registry):
        """Test registering a formatter."""
        formatter = AdvisorReportFormatter()
        registry.register(formatter)

        assert "advisor" in registry.get_registered_types()

    def test_register_multiple_formatters(self, registry):
        """Test registering multiple formatters."""
        registry.register(AdvisorReportFormatter())
        registry.register(AnalyticsReportFormatter())

        types = registry.get_registered_types()
        assert "advisor" in types
        assert "analytics" in types
        assert len(types) == 2

    def test_get_formatter(self, registry):
        """Test retrieving registered formatter."""
        advisor_formatter = AdvisorReportFormatter()
        registry.register(advisor_formatter)

        retrieved = registry.get_formatter("advisor")
        assert retrieved.get_report_type() == "advisor"

    def test_get_unregistered_formatter_raises(self, registry):
        """Test that getting unregistered formatter raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            registry.get_formatter("nonexistent")

        assert "No formatter registered" in str(exc_info.value)
        assert "nonexistent" in str(exc_info.value)

    def test_format_advisor_report(self, registry):
        """Test formatting advisor report through registry."""
        registry.register(AdvisorReportFormatter())

        report = {
            "report_type": "advisor",
            "summary": {
                "overview": "Test overview",
                "current_state": {"cloud_provider": "AWS"},
            },
            "analysis": {"findings": []},
            "next_steps": [{"rank": 1, "action": "Test action"}],
        }

        result = registry.format_report(report)

        assert "## Summary" in result
        assert "Test overview" in result

    def test_format_analytics_report(self, registry):
        """Test formatting analytics report through registry."""
        registry.register(AnalyticsReportFormatter())

        report = {
            "report_type": "analytics",
            "summary": {
                "overview": "Cost analysis",
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
                        "savings_pct": 50.0,
                        "confidence": "medium",
                    },
                    "effort": {"level": "low"},
                    "rank": 1,
                }
            ],
            "cost_summary": {
                "total_cost": 1000.00,
                "cost_trend": "stable",
                "period": "30 days",
            },
            "next_steps": [{"rank": 1, "action": "Implement"}],
        }

        result = registry.format_report(report)

        assert "## Cost Overview" in result
        assert "Cost analysis" in result

    def test_format_report_missing_type_raises(self, registry):
        """Test that report without report_type raises ValueError."""
        registry.register(AdvisorReportFormatter())

        report = {"summary": {"overview": "Test"}}  # No report_type

        with pytest.raises(ValueError) as exc_info:
            registry.format_report(report)

        assert "report_type" in str(exc_info.value).lower()

    def test_format_report_invalid_type_raises(self, registry):
        """Test that report with invalid type raises ValueError."""
        registry.register(AdvisorReportFormatter())

        report = {"report_type": "invalid", "summary": {}}

        with pytest.raises(ValueError) as exc_info:
            registry.format_report(report)

        assert "No formatter registered" in str(exc_info.value)

    def test_format_report_not_dict_raises(self, registry):
        """Test that non-dict report raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            registry.format_report("not a dict")

        assert "must be dict" in str(exc_info.value).lower()

    def test_get_registered_types_empty(self, registry):
        """Test getting types from empty registry."""
        types = registry.get_registered_types()
        assert types == []

    def test_get_registered_types_after_registration(self, registry):
        """Test getting types after registration."""
        registry.register(AdvisorReportFormatter())
        registry.register(AnalyticsReportFormatter())

        types = registry.get_registered_types()
        assert set(types) == {"advisor", "analytics"}


class TestGlobalRegistry:
    """Test global registry and public API functions."""

    def test_format_agent_report_advisor(self):
        """Test global format_agent_report with advisor report."""
        report = {
            "report_type": "advisor",
            "summary": {
                "overview": "Test overview",
                "current_state": {"cloud_provider": "AWS"},
            },
            "analysis": {"findings": []},
            "next_steps": [{"rank": 1, "action": "Test"}],
        }

        result = format_agent_report(report)

        assert isinstance(result, str)
        assert "## Summary" in result
        assert "Test overview" in result

    def test_format_agent_report_analytics(self):
        """Test global format_agent_report with analytics report."""
        report = {
            "report_type": "analytics",
            "summary": {
                "overview": "Cost analysis",
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
                        "savings_pct": 50.0,
                        "confidence": "medium",
                    },
                    "effort": {"level": "low"},
                    "rank": 1,
                }
            ],
            "cost_summary": {
                "total_cost": 1000.00,
                "cost_trend": "stable",
                "period": "30 days",
            },
            "next_steps": [{"rank": 1, "action": "Test"}],
        }

        result = format_agent_report(report)

        assert isinstance(result, str)
        assert "## Cost Overview" in result

    def test_get_formatter_registry(self):
        """Test accessing global registry."""
        registry = get_formatter_registry()

        assert isinstance(registry, ReportFormatterRegistry)

        # Should have both formatters registered by default
        types = registry.get_registered_types()
        assert "advisor" in types
        assert "analytics" in types

    def test_global_registry_has_formatters(self):
        """Test that global registry is pre-configured."""
        registry = get_formatter_registry()

        # Should be able to get both formatters
        advisor_formatter = registry.get_formatter("advisor")
        analytics_formatter = registry.get_formatter("analytics")

        assert advisor_formatter.get_report_type() == "advisor"
        assert analytics_formatter.get_report_type() == "analytics"
