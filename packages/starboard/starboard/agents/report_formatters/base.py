# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Base protocol for report formatters.

This module defines the interface that all report formatters must implement.
Follows the Adapter Pattern to allow type-specific rendering logic.
"""

from typing import Any, Protocol


class ReportFormatter(Protocol):
    """
    Protocol for report formatters.

    All report formatters must implement this interface to be registered
    and used by the formatting registry.

    Example:
        >>> class CustomFormatter:
        ...     def get_report_type(self) -> str:
        ...         return "custom"
        ...
        ...     def format_to_markdown(self, report: dict[str, Any]) -> str:
        ...         return "# Custom Report\\n..."
        >>>
        >>> formatter: ReportFormatter = CustomFormatter()
        >>> result = formatter.format_to_markdown(report_dict)
    """

    def get_report_type(self) -> str:
        """
        Return the report type this formatter handles.

        Returns:
            Report type string (e.g., "advisor", "analytics", "diagnostic")

        Example:
            >>> formatter.get_report_type()
            'advisor'
        """
        ...

    def format_to_markdown(self, report: dict[str, Any]) -> str:
        """
        Format report dictionary to markdown string.

        Args:
            report: Report dictionary (from Pydantic model.model_dump())

        Returns:
            Formatted markdown string for display

        Example:
            >>> report = {"report_type": "advisor", "summary": {...}}
            >>> markdown = formatter.format_to_markdown(report)
            >>> print(markdown)
            ## Summary
            ...
        """
        ...
