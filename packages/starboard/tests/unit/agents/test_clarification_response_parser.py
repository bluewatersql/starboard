# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Tests for ClarificationResponseParser.

This module tests:
- Numeric choice parsing (1-5)
- Keyword matching (sql, job, table, cluster, troubleshoot)
- Disabled domain filtering
- Edge cases (invalid input, out of range, ambiguous)

Follows Python AI Agent Engineering Standards:
- Test edge cases
- Descriptive test names
- 100% coverage for critical paths
"""

from __future__ import annotations

from starboard.agents.clarification.clarification_handler import (
    DEFAULT_DOMAIN_OPTIONS,
    DomainOption,
)
from starboard.agents.clarification.clarification_response_parser import (
    ClarificationResponseParser,
)


class TestClarificationResponseParser:
    """Test suite for ClarificationResponseParser."""

    def test_init_with_defaults(self):
        """Test initialization with default parameters."""
        parser = ClarificationResponseParser(domain_options=DEFAULT_DOMAIN_OPTIONS)

        assert (
            len(parser._enabled_options) == 6
        )  # query, job, uc, cluster, warehouse, diagnostic
        assert parser.disabled_domains == set()

    def test_init_with_disabled_domains(self):
        """Test initialization with disabled domains."""
        parser = ClarificationResponseParser(
            domain_options=DEFAULT_DOMAIN_OPTIONS,
            disabled_domains=["cluster", "diagnostic"],
        )

        assert len(parser._enabled_options) == 4  # query, job, uc, warehouse
        assert "cluster" not in parser._enabled_options
        assert "diagnostic" not in parser._enabled_options
        assert "query" in parser._enabled_options

    def test_parse_numeric_choice_first_option(self):
        """Test parsing numeric choice for first option."""
        parser = ClarificationResponseParser(domain_options=DEFAULT_DOMAIN_OPTIONS)

        result = parser.parse("1")

        assert result == "query"

    def test_parse_numeric_choice_last_option(self):
        """Test parsing numeric choice for last option."""
        parser = ClarificationResponseParser(domain_options=DEFAULT_DOMAIN_OPTIONS)

        result = parser.parse(
            "6"
        )  # 6 options now: query, job, uc, cluster, warehouse, diagnostic

        assert result == "diagnostic"

    def test_parse_numeric_choice_middle_option(self):
        """Test parsing numeric choice for middle option."""
        parser = ClarificationResponseParser(domain_options=DEFAULT_DOMAIN_OPTIONS)

        result = parser.parse("3")

        assert result == "uc"

    def test_parse_numeric_choice_out_of_range(self):
        """Test parsing numeric choice out of valid range."""
        parser = ClarificationResponseParser(domain_options=DEFAULT_DOMAIN_OPTIONS)

        result = parser.parse("99")

        assert result is None

    def test_parse_numeric_choice_zero(self):
        """Test parsing zero returns None."""
        parser = ClarificationResponseParser(domain_options=DEFAULT_DOMAIN_OPTIONS)

        result = parser.parse("0")

        assert result is None

    def test_parse_numeric_choice_with_disabled_domains(self):
        """Test numeric choice respects disabled domains."""
        parser = ClarificationResponseParser(
            domain_options=DEFAULT_DOMAIN_OPTIONS,
            disabled_domains=["query"],  # Disable first option
        )

        # "1" now maps to "job" (second option becomes first)
        result = parser.parse("1")

        assert result == "job"

    def test_parse_keyword_query(self):
        """Test parsing query keywords."""
        parser = ClarificationResponseParser(domain_options=DEFAULT_DOMAIN_OPTIONS)

        assert parser.parse("query") == "query"
        assert parser.parse("sql") == "query"
        assert parser.parse("statement") == "query"
        assert parser.parse("I need help with SQL") == "query"

    def test_parse_keyword_job(self):
        """Test parsing job keywords."""
        parser = ClarificationResponseParser(domain_options=DEFAULT_DOMAIN_OPTIONS)

        assert parser.parse("job") == "job"
        assert parser.parse("databricks job") == "job"
        assert parser.parse("workflow") == "job"
        assert parser.parse("help with job 123") == "job"

    def test_parse_keyword_table(self):
        """Test parsing table keywords."""
        parser = ClarificationResponseParser(domain_options=DEFAULT_DOMAIN_OPTIONS)

        assert parser.parse("table") == "uc"
        assert parser.parse("metadata") == "uc"
        assert parser.parse("lineage") == "uc"
        assert parser.parse("schema") == "uc"
        assert parser.parse("catalog") == "uc"
        assert parser.parse("unity catalog") == "uc"

    def test_parse_keyword_cluster(self):
        """Test parsing cluster keywords."""
        parser = ClarificationResponseParser(domain_options=DEFAULT_DOMAIN_OPTIONS)

        assert parser.parse("cluster") == "cluster"
        assert parser.parse("autoscaling") == "cluster"
        assert parser.parse("spark config") == "cluster"

    def test_parse_keyword_warehouse(self):
        """Test parsing warehouse keywords."""
        parser = ClarificationResponseParser(domain_options=DEFAULT_DOMAIN_OPTIONS)

        assert parser.parse("warehouse") == "warehouse"

    def test_parse_keyword_diagnostic(self):
        """Test parsing diagnostic keywords."""
        parser = ClarificationResponseParser(domain_options=DEFAULT_DOMAIN_OPTIONS)

        assert parser.parse("diagnostic") == "diagnostic"
        assert parser.parse("troubleshoot") == "diagnostic"
        assert parser.parse("debug") == "diagnostic"
        assert parser.parse("error") == "diagnostic"
        assert parser.parse("issue") == "diagnostic"

    def test_parse_keyword_case_insensitive(self):
        """Test keyword parsing is case insensitive."""
        parser = ClarificationResponseParser(domain_options=DEFAULT_DOMAIN_OPTIONS)

        assert parser.parse("SQL") == "query"
        assert parser.parse("JOB") == "job"
        assert parser.parse("Cluster") == "cluster"

    def test_parse_keyword_with_whitespace(self):
        """Test keyword parsing handles whitespace."""
        parser = ClarificationResponseParser(domain_options=DEFAULT_DOMAIN_OPTIONS)

        assert parser.parse("  sql  ") == "query"
        assert parser.parse("\tjob\n") == "job"

    def test_parse_keyword_disabled_domain_returns_none(self):
        """Test keyword match for disabled domain returns None."""
        parser = ClarificationResponseParser(
            domain_options=DEFAULT_DOMAIN_OPTIONS,
            disabled_domains=["query"],
        )

        # "sql" keyword maps to "query" which is disabled
        result = parser.parse("sql")

        assert result is None

    def test_parse_invalid_input_returns_none(self):
        """Test invalid input returns None."""
        parser = ClarificationResponseParser(domain_options=DEFAULT_DOMAIN_OPTIONS)

        assert parser.parse("hello") is None
        assert parser.parse("invalid") is None
        assert parser.parse("random text") is None

    def test_parse_empty_string_returns_none(self):
        """Test empty string returns None."""
        parser = ClarificationResponseParser(domain_options=DEFAULT_DOMAIN_OPTIONS)

        assert parser.parse("") is None
        assert parser.parse("   ") is None

    def test_is_valid_numeric_choice_valid(self):
        """Test is_valid_numeric_choice with valid inputs."""
        parser = ClarificationResponseParser(domain_options=DEFAULT_DOMAIN_OPTIONS)

        assert parser.is_valid_numeric_choice("1") is True
        assert parser.is_valid_numeric_choice("3") is True
        assert parser.is_valid_numeric_choice("5") is True

    def test_is_valid_numeric_choice_invalid(self):
        """Test is_valid_numeric_choice with invalid inputs."""
        parser = ClarificationResponseParser(domain_options=DEFAULT_DOMAIN_OPTIONS)

        assert parser.is_valid_numeric_choice("0") is False
        assert parser.is_valid_numeric_choice("7") is False  # 6 options now
        assert parser.is_valid_numeric_choice("99") is False
        assert parser.is_valid_numeric_choice("abc") is False
        assert parser.is_valid_numeric_choice("") is False

    def test_get_enabled_domain_count_all_enabled(self):
        """Test get_enabled_domain_count with all domains enabled."""
        parser = ClarificationResponseParser(domain_options=DEFAULT_DOMAIN_OPTIONS)

        assert (
            parser.get_enabled_domain_count() == 6
        )  # query, job, uc, cluster, warehouse, diagnostic

    def test_get_enabled_domain_count_some_disabled(self):
        """Test get_enabled_domain_count with some domains disabled."""
        parser = ClarificationResponseParser(
            domain_options=DEFAULT_DOMAIN_OPTIONS,
            disabled_domains=["cluster", "diagnostic"],
        )

        assert parser.get_enabled_domain_count() == 4  # query, job, uc, warehouse

    def test_get_domain_for_number_valid(self):
        """Test get_domain_for_number with valid choices."""
        parser = ClarificationResponseParser(domain_options=DEFAULT_DOMAIN_OPTIONS)

        assert parser.get_domain_for_number(1) == "query"
        assert parser.get_domain_for_number(2) == "job"
        assert parser.get_domain_for_number(3) == "uc"
        assert parser.get_domain_for_number(4) == "cluster"
        assert parser.get_domain_for_number(5) == "warehouse"
        assert parser.get_domain_for_number(6) == "diagnostic"

    def test_get_domain_for_number_invalid(self):
        """Test get_domain_for_number with invalid choices."""
        parser = ClarificationResponseParser(domain_options=DEFAULT_DOMAIN_OPTIONS)

        assert parser.get_domain_for_number(0) is None
        assert parser.get_domain_for_number(7) is None  # 6 domains now
        assert parser.get_domain_for_number(99) is None
        assert parser.get_domain_for_number(-1) is None

    def test_get_domain_for_number_with_disabled_domains(self):
        """Test get_domain_for_number respects disabled domains."""
        parser = ClarificationResponseParser(
            domain_options=DEFAULT_DOMAIN_OPTIONS,
            disabled_domains=["query", "cluster"],
        )

        # With query and cluster disabled, we have: job, uc, warehouse, diagnostic
        assert parser.get_domain_for_number(1) == "job"
        assert parser.get_domain_for_number(2) == "uc"
        assert parser.get_domain_for_number(3) == "warehouse"
        assert parser.get_domain_for_number(4) == "diagnostic"
        assert parser.get_domain_for_number(5) is None  # Out of range

    def test_custom_domain_options(self):
        """Test with custom domain options."""
        custom_options = [
            DomainOption("Custom option 1", "custom1"),
            DomainOption("Custom option 2", "custom2"),
        ]

        parser = ClarificationResponseParser(domain_options=custom_options)

        assert parser.parse("1") == "custom1"
        assert parser.parse("2") == "custom2"
        assert parser.parse("3") is None
        assert parser.get_enabled_domain_count() == 2

    def test_keyword_priority_first_match_wins(self):
        """Test that first matching keyword wins."""
        parser = ClarificationResponseParser(domain_options=DEFAULT_DOMAIN_OPTIONS)

        # "job" keyword should match before "workflow" (both map to "job")
        result = parser.parse("job workflow")

        assert result == "job"
