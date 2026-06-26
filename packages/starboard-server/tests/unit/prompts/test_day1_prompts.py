# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""
Unit tests for router and query domain prompts (Day 1).

Tests for the extracted router and query prompts to ensure they
maintain expected structure and content.
"""


class TestRouterPrompts:
    """Tests for router domain prompts."""

    def test_router_prompt_exists(self):
        """Test that ROUTER_SYSTEM_PROMPT is exported."""
        from starboard_server.prompts import ROUTER_SYSTEM_PROMPT

        assert ROUTER_SYSTEM_PROMPT is not None
        assert isinstance(ROUTER_SYSTEM_PROMPT, str)

    def test_router_prompt_content(self):
        """Test router prompt contains key elements."""
        from starboard_server.prompts import ROUTER_SYSTEM_PROMPT

        # Check for key routing domains
        # Note: "uc" (Unity Catalog) replaced the deprecated "table" domain
        assert "query:" in ROUTER_SYSTEM_PROMPT
        assert "job:" in ROUTER_SYSTEM_PROMPT
        assert "uc:" in ROUTER_SYSTEM_PROMPT  # Renamed from "table:" in v1.1.0
        assert "compute:" in ROUTER_SYSTEM_PROMPT
        assert "diagnostic:" in ROUTER_SYSTEM_PROMPT
        assert "analytics:" in ROUTER_SYSTEM_PROMPT

        # Check for key tools
        assert "resolve_user_intent" in ROUTER_SYSTEM_PROMPT
        assert "request_user_input" in ROUTER_SYSTEM_PROMPT
        assert "complete" in ROUTER_SYSTEM_PROMPT

    def test_router_prompt_formatting_instructions(self):
        """Test router prompt includes formatting and reasoning instructions."""
        from starboard_server.prompts import ROUTER_SYSTEM_PROMPT

        # Check for reasoning output section (case-insensitive for header style variations)
        assert "reasoning output" in ROUTER_SYSTEM_PROMPT.lower()
        assert "VARY YOUR LANGUAGE" in ROUTER_SYSTEM_PROMPT
        assert "routing options" in ROUTER_SYSTEM_PROMPT.lower()


class TestQueryPrompts:
    """Tests for query domain prompts."""

    def test_query_prompt_exists(self):
        """Test that QUERY_SYSTEM_PROMPT is exported."""
        from starboard_server.prompts import QUERY_SYSTEM_PROMPT

        assert QUERY_SYSTEM_PROMPT is not None
        assert isinstance(QUERY_SYSTEM_PROMPT, str)

    def test_query_prompt_tools(self):
        """Test query prompt lists expected tools."""
        from starboard_server.prompts import QUERY_SYSTEM_PROMPT

        # Check for query-specific tools
        assert "resolve_query" in QUERY_SYSTEM_PROMPT
        assert "analyze_query_plan" in QUERY_SYSTEM_PROMPT
        assert "discover_tables" in QUERY_SYSTEM_PROMPT
        assert "get_table_metadata" in QUERY_SYSTEM_PROMPT
        assert "get_table_history" in QUERY_SYSTEM_PROMPT
        assert "request_user_input" in QUERY_SYSTEM_PROMPT
        assert "complete" in QUERY_SYSTEM_PROMPT

    def test_query_prompt_modes(self):
        """Test query prompt describes ONLINE and OFFLINE modes."""
        from starboard_server.prompts import QUERY_SYSTEM_PROMPT

        assert "ONLINE MODE" in QUERY_SYSTEM_PROMPT
        assert "OFFLINE MODE" in QUERY_SYSTEM_PROMPT
        assert "Mode:" in QUERY_SYSTEM_PROMPT

    def test_query_prompt_output_format(self):
        """Test query prompt specifies output format."""
        from starboard_server.prompts import QUERY_SYSTEM_PROMPT

        # Check for output format section (case-insensitive for header style variations)
        assert "output format" in QUERY_SYSTEM_PROMPT.lower()
        assert "OptimizerAdvisorReport" in QUERY_SYSTEM_PROMPT
        assert "Analysis Findings" in QUERY_SYSTEM_PROMPT
        assert "Query Rewrite" in QUERY_SYSTEM_PROMPT
        assert "Interactive Next Steps" in QUERY_SYSTEM_PROMPT

    def test_query_prompt_template_variables(self):
        """Test query prompt includes template variables."""
        from starboard_server.prompts import QUERY_SYSTEM_PROMPT

        # Check for template placeholders
        assert "{token_budget" in QUERY_SYSTEM_PROMPT
        assert "{mode}" in QUERY_SYSTEM_PROMPT
        assert "{goal}" in QUERY_SYSTEM_PROMPT


class TestBaseUtilities:
    """Tests for base prompt utilities."""

    def test_agent_domain_type_exists(self):
        """Test AgentDomain type is exported."""
        from starboard_server.prompts import AgentDomain

        assert AgentDomain is not None

    def test_agent_domain_literal_values(self):
        """Test AgentDomain Literal contains expected values."""
        from typing import get_args

        from starboard_server.prompts.base import AgentDomain

        # Get the Literal values
        # Note: "uc" (Unity Catalog) replaces the deprecated "table" domain
        # Note: "warehouse" handles SQL warehouse portfolio optimization
        expected_domains = {
            "router",
            "query",
            "job",
            "uc",  # Renamed from "table" in v1.1.0
            "cluster",
            "diagnostic",
            "analytics",
            "warehouse",  # SQL warehouse portfolio optimization
            "discovery",  # Workspace health assessment
        }
        actual_domains = set(get_args(AgentDomain))

        assert actual_domains == expected_domains


class TestBackwardCompatibility:
    """Tests for backward compatibility with old domain_prompts.py."""

    def test_imports_from_main_package(self):
        """Test that all prompts can be imported from main prompts package."""
        from starboard_server.prompts import (
            QUERY_SYSTEM_PROMPT,
            ROUTER_SYSTEM_PROMPT,
            AgentDomain,
        )

        assert AgentDomain is not None
        assert ROUTER_SYSTEM_PROMPT is not None
        assert QUERY_SYSTEM_PROMPT is not None

    def test_prompts_are_strings(self):
        """Test that all prompts are non-empty strings."""
        from starboard_server.prompts import QUERY_SYSTEM_PROMPT, ROUTER_SYSTEM_PROMPT

        assert isinstance(ROUTER_SYSTEM_PROMPT, str)
        assert len(ROUTER_SYSTEM_PROMPT) > 100

        assert isinstance(QUERY_SYSTEM_PROMPT, str)
        assert len(QUERY_SYSTEM_PROMPT) > 100
