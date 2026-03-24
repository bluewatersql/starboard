"""
Tests for ClarificationHandler.

This module tests:
- Domain option filtering (enabled/disabled)
- Clarification message generation
- Event streaming (ThinkingEvent + FinalOutputEvent)
- Edge cases (all domains disabled, empty options)

Follows Python AI Agent Engineering Standards:
- Test edge cases
- Descriptive test names
- 100% coverage for critical paths
"""

from __future__ import annotations

import pytest
from starboard_server.agents.clarification.clarification_handler import (
    DEFAULT_DOMAIN_OPTIONS,
    ClarificationHandler,
    DomainOption,
)
from starboard_server.agents.events import FinalOutputEvent, ThinkingEvent


class TestClarificationHandler:
    """Test suite for ClarificationHandler."""

    def test_init_with_defaults(self):
        """Test initialization with default parameters."""
        handler = ClarificationHandler()

        assert handler.disabled_domains == set()
        assert handler.domain_options == DEFAULT_DOMAIN_OPTIONS

    def test_init_with_disabled_domains(self):
        """Test initialization with disabled domains."""
        handler = ClarificationHandler(disabled_domains=["cluster", "diagnostic"])

        assert handler.disabled_domains == {"cluster", "diagnostic"}
        assert handler.domain_options == DEFAULT_DOMAIN_OPTIONS

    def test_init_with_custom_options(self):
        """Test initialization with custom domain options."""
        custom_options = [
            DomainOption("Custom option 1", "custom1"),
            DomainOption("Custom option 2", "custom2"),
        ]

        handler = ClarificationHandler(domain_options=custom_options)

        assert handler.domain_options == custom_options

    def test_has_available_options_all_enabled(self):
        """Test has_available_options when all domains are enabled."""
        handler = ClarificationHandler(disabled_domains=[])

        assert handler.has_available_options() is True

    def test_has_available_options_some_disabled(self):
        """Test has_available_options when some domains are disabled."""
        handler = ClarificationHandler(disabled_domains=["cluster", "diagnostic"])

        assert handler.has_available_options() is True

    def test_has_available_options_all_disabled(self):
        """Test has_available_options when all domains are disabled."""
        all_domains = [opt.domain_key for opt in DEFAULT_DOMAIN_OPTIONS]
        handler = ClarificationHandler(disabled_domains=all_domains)

        assert handler.has_available_options() is False

    def test_generate_clarification_events_structure(self):
        """Test that events are generated in correct order."""
        handler = ClarificationHandler()

        events = list(handler.generate_clarification_events())

        assert len(events) == 2
        assert isinstance(events[0], ThinkingEvent)
        assert isinstance(events[1], FinalOutputEvent)

    def test_generate_clarification_events_content(self):
        """Test clarification message content."""
        handler = ClarificationHandler(disabled_domains=["cluster"])

        events = list(handler.generate_clarification_events())

        thinking_event = events[0]
        assert "I'm not sure I understand" in thinking_event.content
        assert "1. A specific SQL query" in thinking_event.content
        assert "2. A Databricks job" in thinking_event.content
        assert "3. Unity Catalog:" in thinking_event.content
        # Cluster should be skipped (disabled), warehouse is 4, diagnostic is 5
        assert "4. SQL warehouse analysis" in thinking_event.content
        assert "5. Troubleshoot a specific issue" in thinking_event.content
        assert "type the number or describe" in thinking_event.content

    def test_generate_clarification_events_filters_disabled(self):
        """Test that disabled domains are excluded from options."""
        handler = ClarificationHandler(disabled_domains=["query", "job"])

        events = list(handler.generate_clarification_events())

        thinking_event = events[0]
        content = thinking_event.content

        # Disabled domains should not appear
        assert "SQL query" not in content
        assert "Databricks job" not in content

        # Enabled domains should appear
        assert "Unity Catalog:" in content
        assert "Cluster configuration" in content
        assert "SQL warehouse analysis" in content
        assert "Troubleshoot" in content

    def test_generate_clarification_events_all_disabled_raises(self):
        """Test that ValueError is raised when all domains are disabled."""
        all_domains = [opt.domain_key for opt in DEFAULT_DOMAIN_OPTIONS]
        handler = ClarificationHandler(disabled_domains=all_domains)

        with pytest.raises(
            ValueError, match="Cannot generate clarification: all domain options"
        ):
            list(handler.generate_clarification_events())

    def test_generate_clarification_events_final_output_structure(self):
        """Test FinalOutputEvent structure."""
        handler = ClarificationHandler()

        events = list(handler.generate_clarification_events())
        final_event = events[1]

        assert final_event.output is not None
        # formatted_report is no longer generated - clients render from complete_report
        assert "complete_report" in final_event.output
        assert final_event.output["complete_report"] is None
        # FinalOutputEvent has type, output, metadata (no step attribute)

    def test_get_enabled_options_filters_correctly(self):
        """Test _get_enabled_options filtering logic."""
        handler = ClarificationHandler(disabled_domains=["query", "diagnostic"])

        enabled = handler._get_enabled_options()

        assert len(enabled) == 4  # 6 total - 2 disabled
        enabled_keys = {opt.domain_key for opt in enabled}
        assert "query" not in enabled_keys
        assert "diagnostic" not in enabled_keys
        assert "job" in enabled_keys
        assert "uc" in enabled_keys
        assert "cluster" in enabled_keys
        assert "warehouse" in enabled_keys

    def test_build_clarification_message_formatting(self):
        """Test clarification message formatting."""
        handler = ClarificationHandler()

        options = [
            DomainOption("First option", "first"),
            DomainOption("Second option", "second"),
        ]

        message = handler._build_clarification_message(options)

        # Check structure
        lines = message.split("\n")
        assert (
            lines[0]
            == "I'm not sure I understand what you're asking. Can you clarify what you'd like help with?"
        )
        assert lines[1] == ""  # Empty line
        assert lines[2] == "1. First option"
        assert lines[3] == "2. Second option"
        assert lines[4] == ""  # Empty line
        assert "type the number" in lines[5]

    def test_build_clarification_message_empty_options(self):
        """Test message building with empty options list."""
        handler = ClarificationHandler()

        message = handler._build_clarification_message([])

        # Should still have header and footer
        assert "I'm not sure I understand" in message
        assert "type the number" in message


class TestDomainOption:
    """Test suite for DomainOption dataclass."""

    def test_domain_option_creation(self):
        """Test creating a DomainOption."""
        option = DomainOption("Test display text", "test_key")

        assert option.display_text == "Test display text"
        assert option.domain_key == "test_key"

    def test_domain_option_frozen(self):
        """Test that DomainOption is immutable."""
        option = DomainOption("Test", "test")

        with pytest.raises(AttributeError):
            option.display_text = "New value"  # type: ignore

    def test_default_domain_options_structure(self):
        """Test DEFAULT_DOMAIN_OPTIONS has expected structure."""
        assert len(DEFAULT_DOMAIN_OPTIONS) == 6

        # Check all expected domains are present
        domain_keys = {opt.domain_key for opt in DEFAULT_DOMAIN_OPTIONS}
        assert domain_keys == {
            "query",
            "job",
            "uc",
            "cluster",
            "warehouse",
            "diagnostic",
        }

        # Check all have display text
        for option in DEFAULT_DOMAIN_OPTIONS:
            assert len(option.display_text) > 0
            assert len(option.domain_key) > 0
