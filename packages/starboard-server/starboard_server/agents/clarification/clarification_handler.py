# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Clarification handler for multi-agent routing.

Handles user clarification when intent classification confidence is low,
presenting available domain options in a natural conversational flow.

Follows Python AI Agent Engineering Standards:
- Single responsibility (clarification presentation)
- Pure logic (no side effects beyond event generation)
- Explicit configuration
- Type hints on all functions
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import structlog

from starboard_server.agents.events import FinalOutputEvent, ThinkingEvent

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class DomainOption:
    """
    A selectable domain option for clarification.

    Attributes:
        display_text: Human-readable description shown to user
        domain_key: Internal domain identifier (query, job, uc, etc.)
    """

    display_text: str
    domain_key: str


# Default domain options presented to users
DEFAULT_DOMAIN_OPTIONS = [
    DomainOption("A specific SQL query (provide statement_id or SQL)", "query"),
    DomainOption("A Databricks job (provide job_id or job name)", "job"),
    DomainOption(
        "Unity Catalog: table metadata, lineage, governance (provide table name)", "uc"
    ),
    DomainOption("Cluster configuration (provide cluster_id)", "cluster"),
    DomainOption("SQL warehouse analysis (provide warehouse_id)", "warehouse"),
    DomainOption("Troubleshoot a specific issue (describe the problem)", "diagnostic"),
]


class ClarificationHandler:
    """
    Handles user clarification for multi-agent routing.

    When intent classification confidence is low, this handler:
    1. Filters available domain options (excluding disabled domains)
    2. Builds a friendly clarification message with numbered options
    3. Returns streaming events (ThinkingEvent + FinalOutputEvent)

    Design:
    - Stateless (no instance state)
    - Pure functions (deterministic output)
    - Configurable domain options
    - Returns events for streaming

    Example:
        ```python
        handler = ClarificationHandler(
            disabled_domains=["compute"],
            domain_options=DEFAULT_DOMAIN_OPTIONS,
        )

        events = handler.generate_clarification_events()
        for event in events:
            yield event
        ```
    """

    def __init__(
        self,
        disabled_domains: list[str] | None = None,
        domain_options: list[DomainOption] | None = None,
    ) -> None:
        """
        Initialize clarification handler.

        Args:
            disabled_domains: List of domain keys to exclude from options
                            (e.g., ["compute", "diagnostic"])
            domain_options: Available domain options (defaults to DEFAULT_DOMAIN_OPTIONS)
        """
        self.disabled_domains = set(disabled_domains or [])
        self.domain_options = domain_options or DEFAULT_DOMAIN_OPTIONS

    def has_available_options(self) -> bool:
        """
        Check if any domain options are available after filtering.

        Returns:
            True if at least one domain option is available, False otherwise
        """
        enabled_options = self._get_enabled_options()
        return len(enabled_options) > 0

    def generate_clarification_events(
        self,
    ) -> Iterator[ThinkingEvent | FinalOutputEvent]:
        """
        Generate clarification events for streaming to user.

        Returns:
            Iterator of StreamingEvent (ThinkingEvent followed by FinalOutputEvent)

        Raises:
            ValueError: If no domain options are available (all disabled)

        Example:
            ```python
            for event in handler.generate_clarification_events():
                yield event
            ```
        """
        enabled_options = self._get_enabled_options()

        if not enabled_options:
            raise ValueError(
                "Cannot generate clarification: all domain options are disabled"
            )

        clarification_text = self._build_clarification_message(enabled_options)

        # Send as ThinkingEvent (MESSAGE_DELTA in frontend)
        yield ThinkingEvent(
            step=0,
            content=clarification_text,
        )

        # Complete with FinalOutputEvent (MESSAGE_STOP in frontend)
        # Note: clarification handler doesn't generate reports, just text
        yield FinalOutputEvent(
            output={
                "clarification_text": clarification_text,
                "complete_report": None,
            },
        )

    def _get_enabled_options(self) -> list[DomainOption]:
        """
        Filter domain options to only include enabled domains.

        Returns:
            List of DomainOption that are not in disabled_domains
        """
        return [
            option
            for option in self.domain_options
            if option.domain_key not in self.disabled_domains
        ]

    def _build_clarification_message(self, options: list[DomainOption]) -> str:
        """
        Build friendly clarification message with numbered options.

        Args:
            options: List of enabled DomainOption to present

        Returns:
            Formatted clarification message string

        Example output:
            ```
            I'm not sure I understand what you're asking. Can you clarify what you'd like help with?

            1. A specific SQL query (provide statement_id or SQL)
            2. A Databricks job (provide job_id or job name)
            3. Unity Catalog: table metadata, lineage, governance (provide table name)

            Just type the number or describe what you need help with.
            ```
        """
        lines = [
            "I'm not sure I understand what you're asking. Can you clarify what you'd like help with?",
            "",
        ]

        # Add numbered options
        for idx, option in enumerate(options, start=1):
            lines.append(f"{idx}. {option.display_text}")

        # Add footer
        lines.append("")
        lines.append("Just type the number or describe what you need help with.")

        return "\n".join(lines)
