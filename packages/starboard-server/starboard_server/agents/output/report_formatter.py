# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""DEPRECATED: Use starboard_server.agents.report_formatters instead.

This module is deprecated in favor of the new adapter-based formatter system.
Use format_agent_report() from report_formatters for polymorphic report handling.

Migration:
    Old: from starboard_server.agents.output.report_formatter import format_optimizer_report
    New: from starboard_server.agents.report_formatters import format_agent_report
"""

import warnings
from typing import Any

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


def format_optimizer_report(complete_report: dict[str, Any]) -> str:
    """DEPRECATED: Format OptimizerAdvisorReport dict into readable markdown.

    This function is deprecated. Use format_agent_report() instead.

    Handles the comprehensive report structure with summary, analysis findings,
    evidence, impact estimates, and next steps.

    Args:
        complete_report: Dictionary representation of OptimizerAdvisorReport

    Returns:
        Formatted markdown string for display

    Example:
        ```python
        formatted = format_optimizer_report(report_dict)
        # Returns markdown with ## Summary, ## Recommendations, etc.
        ```
    """
    warnings.warn(
        "format_optimizer_report is deprecated. Use format_agent_report() from "
        "starboard_server.agents.report_formatters instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    # Forward to new formatter
    from starboard_server.agents.report_formatters import format_agent_report

    return format_agent_report(complete_report)
