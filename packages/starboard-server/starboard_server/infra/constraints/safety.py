# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Safety and approval management for operations with side effects."""

from starboard_server.infra.observability.logging import get_logger

logger = get_logger(__name__)


class ApprovalManager:
    """
    Handles user approvals for operations with side effects.

    This class provides interactive approval mechanisms for potentially dangerous
    or resource-intensive operations that modify state or consume significant
    resources. It prompts users via stdin/stdout for explicit confirmation before
    proceeding with side-effect operations.

    All approval methods are static and can be called without instantiation.
    They return standardized "APPROVED" or "DENY" strings to indicate user decision.

    Use Cases:
        - ANALYZE TABLE operations that update table statistics
        - SQL execution that may modify data or schema
        - Expensive operations like OPTIMIZE or VACUUM
        - Any operation requiring explicit user consent
    """

    @staticmethod
    def approve_table_stats_update(tables: list[str]) -> str:
        """
        Prompt user to approve ANALYZE TABLE operations.

        This method requests explicit user confirmation before executing ANALYZE TABLE
        commands, which update table statistics and can be resource-intensive for
        large tables. The prompt displays the list of tables to be analyzed.

        The method handles interrupts (Ctrl+C, EOF) gracefully by treating them as
        denials. Accepts 'yes' or 'y' (case-insensitive) as approval; all other
        inputs are treated as denial.

        Args:
            tables: List of fully qualified table names that will have statistics
                updated via ANALYZE TABLE. Empty list indicates no specific tables.

        Returns:
            "APPROVED" if user explicitly approves with 'yes' or 'y'.
            "DENY" for any other input, interrupts, or errors.
        """
        logger.debug(
            "safety_analyze_table_requested",
            tables=tables,
        )
        try:
            answer = (
                input("Approve ANALYZE TABLE? Type 'yes' to allow: ").strip().lower()
            )
        except (EOFError, KeyboardInterrupt):
            answer = "no"

        return "APPROVED" if answer in {"y", "yes"} else "DENY"

    @staticmethod
    def approve_sql_execution(sql: str) -> str:
        """
        Prompt user to approve SQL execution.

        This method requests explicit user confirmation before executing arbitrary
        SQL statements. It displays the first 100 characters of the SQL query for
        user review. This safety check is particularly important for queries that
        might modify data, alter schema, or consume significant resources.

        The method handles interrupts (Ctrl+C, EOF) gracefully by treating them as
        denials. Accepts 'yes' or 'y' (case-insensitive) as approval; all other
        inputs are treated as denial.

        Args:
            sql: SQL query text to be executed. The first 100 characters are
                displayed to the user for review.

        Returns:
            "APPROVED" if user explicitly approves with 'yes' or 'y'.
            "DENY" for any other input, interrupts, or errors.
        """
        logger.debug(
            "safety_sql_execution_requested",
            sql_preview=sql[:100],
        )
        try:
            answer = (
                input("Approve SQL execution? Type 'yes' to allow: ").strip().lower()
            )
        except (EOFError, KeyboardInterrupt):
            answer = "no"

        return "APPROVED" if answer in {"y", "yes"} else "DENY"
