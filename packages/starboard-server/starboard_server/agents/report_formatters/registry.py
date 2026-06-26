# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Formatter registry for dispatching to type-specific formatters.

The registry pattern allows runtime dispatch to the appropriate formatter
based on report_type, enabling extensible formatting without conditional logic.
"""

from typing import Any

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
from starboard_server.agents.report_formatters.warehouse_formatter import (
    WarehouseReportFormatter,
)
from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class ReportFormatterRegistry:
    """
    Registry for report formatters.

    Maintains a mapping of report types to formatter instances and dispatches
    format requests to the appropriate formatter.

    Example:
        >>> registry = ReportFormatterRegistry()
        >>> registry.register(AdvisorReportFormatter())
        >>> markdown = registry.format_report({"report_type": "advisor", ...})
    """

    def __init__(self):
        """Initialize registry with empty formatter map."""
        self._formatters: dict[str, ReportFormatter] = {}

    def register(self, formatter: ReportFormatter) -> None:
        """
        Register a formatter for a report type.

        Args:
            formatter: Formatter instance implementing ReportFormatter protocol

        Example:
            >>> registry = ReportFormatterRegistry()
            >>> registry.register(AdvisorReportFormatter())
        """
        report_type = formatter.get_report_type()
        self._formatters[report_type] = formatter
        logger.debug(
            "formatter_registered",
            report_type=report_type,
            formatter_class=formatter.__class__.__name__,
        )

    def get_formatter(self, report_type: str) -> ReportFormatter:
        """
        Get formatter for a report type.

        Args:
            report_type: Report type string (e.g., "advisor", "analytics")

        Returns:
            Formatter instance for the report type

        Raises:
            ValueError: If no formatter registered for report type

        Example:
            >>> formatter = registry.get_formatter("advisor")
            >>> markdown = formatter.format_to_markdown(report_dict)
        """
        if report_type not in self._formatters:
            available = list(self._formatters.keys())
            raise ValueError(
                f"No formatter registered for report type: '{report_type}'. "
                f"Available types: {available}"
            )

        return self._formatters[report_type]

    def format_report(self, report: dict[str, Any]) -> str:
        """
        Format report using appropriate formatter.

        Automatically selects formatter based on report['report_type'].

        Args:
            report: Report dictionary (from Pydantic model.model_dump())

        Returns:
            Formatted markdown string

        Raises:
            ValueError: If report_type missing or no formatter registered

        Example:
            >>> report = {"report_type": "advisor", "summary": {...}}
            >>> markdown = registry.format_report(report)
        """
        if not isinstance(report, dict):
            logger.error(
                "format_report_invalid_type",
                report_type=type(report).__name__,
            )
            raise ValueError(f"Report must be dict, got {type(report).__name__}")

        report_type = report.get("report_type")
        if not report_type:
            logger.error("format_report_missing_type", report_keys=list(report.keys()))
            raise ValueError(
                "Report dict must include 'report_type' field. "
                f"Keys present: {list(report.keys())}"
            )

        try:
            formatter = self.get_formatter(report_type)
            result = formatter.format_to_markdown(report)
            logger.debug(
                "report_formatted",
                report_type=report_type,
                length=len(result),
            )
            return result

        except (ImportError, AttributeError) as e:
            logger.error(
                "format_report_failed",
                report_type=report_type,
                error=str(e),
                error_type=type(e).__name__,
            )
            # Re-raise with context
            raise ValueError(f"Failed to format {report_type} report: {e}") from e

    def get_registered_types(self) -> list[str]:
        """
        Get list of registered report types.

        Returns:
            List of report type strings

        Example:
            >>> types = registry.get_registered_types()
            >>> print(types)
            ['advisor', 'analytics']
        """
        return list(self._formatters.keys())


# =============================================================================
# Global Registry Instance
# =============================================================================

# Create global registry and register formatters
_global_registry = ReportFormatterRegistry()
_global_registry.register(AdvisorReportFormatter())
_global_registry.register(AnalyticsReportFormatter())
_global_registry.register(ClusterReportFormatter())
_global_registry.register(DiagnosticReportFormatter())
_global_registry.register(WarehouseReportFormatter())


def format_agent_report(report: dict[str, Any]) -> str:
    """
    Format any agent report to markdown.

    Public API function that uses the global registry. This replaces
    the old format_optimizer_report() function with type-based dispatch.

    Args:
        report: Report dictionary (from Pydantic model.model_dump())

    Returns:
        Formatted markdown string

    Raises:
        ValueError: If report invalid or no formatter registered

    Example:
        >>> from starboard_server.agents.report_formatters import format_agent_report
        >>>
        >>> # Advisor report (optimization agents)
        >>> advisor_report = {"report_type": "advisor", ...}
        >>> markdown = format_agent_report(advisor_report)
        >>>
        >>> # Analytics report (FinOps agent)
        >>> analytics_report = {"report_type": "analytics", ...}
        >>> markdown = format_agent_report(analytics_report)

    Note:
        This function uses the global registry instance. To use a custom
        registry, create your own ReportFormatterRegistry and call
        format_report() directly.
    """
    return _global_registry.format_report(report)


def get_formatter_registry() -> ReportFormatterRegistry:
    """
    Get the global formatter registry.

    Use this if you need access to the registry for testing or
    to register custom formatters.

    Returns:
        Global ReportFormatterRegistry instance

    Example:
        >>> registry = get_formatter_registry()
        >>> registry.register(CustomFormatter())
    """
    return _global_registry
