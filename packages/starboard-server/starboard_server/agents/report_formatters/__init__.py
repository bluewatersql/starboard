"""Report formatting adapters for multi-agent system.

This module provides type-specific formatters for converting agent reports
to readable markdown. Uses the Adapter Pattern to allow extensible formatting.

Public API:
    format_agent_report(report: dict) -> str
        Main function to format any agent report to markdown.
        Auto-dispatches based on report['report_type'].

    get_formatter_registry() -> ReportFormatterRegistry
        Access the global registry (for testing or custom formatters).

Supported Report Types:
    - "advisor": AdvisorReport (query, job, UC agents)
    - "analytics": AnalyticsReport (FinOps agent)
    - "cluster": ClusterReport (cluster agent)
    - "diagnostic": DiagnosticReport (diagnostic agent)
    - "warehouse": WarehouseReport (warehouse agent)

Adding New Report Types:
    1. Create MyReportFormatter class implementing ReportFormatter protocol
    2. Register: get_formatter_registry().register(MyReportFormatter())

Example:
    >>> from starboard_server.agents.report_formatters import format_agent_report
    >>>
    >>> # Format advisor report
    >>> advisor_report = {"report_type": "advisor", "summary": {...}, ...}
    >>> markdown = format_agent_report(advisor_report)
    >>> print(markdown)
    ## Summary
    ...
    >>>
    >>> # Format warehouse report
    >>> warehouse_report = {"report_type": "warehouse", "portfolio_summary": {...}, ...}
    >>> markdown = format_agent_report(warehouse_report)
    >>> print(markdown)
    ## Portfolio Overview
    ...
"""

from starboard_server.agents.report_formatters.advisor_formatter import (
    AdvisorReportFormatter,
)
from starboard_server.agents.report_formatters.analytics_formatter import (
    AnalyticsReportFormatter,
)
from starboard_server.agents.report_formatters.base import ReportFormatter
from starboard_server.agents.report_formatters.cluster_formatter import (
    ClusterReportFormatter,
)
from starboard_server.agents.report_formatters.diagnostic_formatter import (
    DiagnosticReportFormatter,
)
from starboard_server.agents.report_formatters.registry import (
    ReportFormatterRegistry,
    format_agent_report,
    get_formatter_registry,
)
from starboard_server.agents.report_formatters.warehouse_formatter import (
    WarehouseReportFormatter,
)

__all__ = [
    # Public API (recommended)
    "format_agent_report",
    "get_formatter_registry",
    # Protocol and base classes
    "ReportFormatter",
    "ReportFormatterRegistry",
    # Concrete formatters (for testing/registration)
    "AdvisorReportFormatter",
    "AnalyticsReportFormatter",
    "ClusterReportFormatter",
    "DiagnosticReportFormatter",
    "WarehouseReportFormatter",
]
