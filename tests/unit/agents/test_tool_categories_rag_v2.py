"""Unit tests for tool categories with Analytics V3 RAG context builder."""

from starboard_server.agents.tool_categories import (
    OFFLINE_TOOLS,
    TOOL_OVERLAP_MATRIX,
    get_tools_for_domain,
)


class TestAnalyticsV3RAGTool:
    """Tests for Analytics Agent V3 RAG tool registration."""

    def test_analytics_agent_has_context_builder(self):
        """Analytics agent should expose the consolidated context builder."""
        all_tools = [
            "build_sql_query",
            "validate_sql_query",
            "execute_sql_query",
            "build_analytics_context",
            "request_user_input",
            "complete",
        ]

        analytics_tools = get_tools_for_domain("analytics", all_tools)

        assert "build_analytics_context" in analytics_tools

    def test_diagnostic_agent_has_context_builder(self):
        """Diagnostic agent also needs the context builder."""
        all_tools = ["build_analytics_context"]

        diagnostic_tools = get_tools_for_domain("diagnostic", all_tools)
        assert "build_analytics_context" in diagnostic_tools

    def test_context_builder_is_offline_safe(self):
        """Context builder should be available in offline mode."""
        assert "build_analytics_context" in OFFLINE_TOOLS

    def test_context_builder_in_overlap_matrix(self):
        """Context builder should be registered in overlap matrix."""
        assert "build_analytics_context" in TOOL_OVERLAP_MATRIX
        assert TOOL_OVERLAP_MATRIX["build_analytics_context"] == [
            "analytics",
            "diagnostic",
        ]

    def test_other_agents_dont_have_context_builder(self):
        """Non-analytics agents should not expose the context builder."""
        all_tools = [
            "build_analytics_context",
            "resolve_query",
            "resolve_job",
            "request_user_input",
            "complete",
        ]

        query_tools = get_tools_for_domain("query", all_tools)
        assert "build_analytics_context" not in query_tools
        assert "resolve_query" in query_tools

        job_tools = get_tools_for_domain("job", all_tools)
        assert "build_analytics_context" not in job_tools
        assert "resolve_job" in job_tools

    def test_offline_mode_keeps_context_builder(self):
        """Context builder should remain when filtering online-only tools."""
        all_tools = [
            "build_analytics_context",
            "build_sql_query",
            "validate_sql_query",
            "execute_sql_query",
            "build_analytics_context",
            "request_user_input",
            "complete",
        ]

        analytics_tools = get_tools_for_domain(
            "analytics", all_tools, offline_mode=True
        )

        assert "build_analytics_context" in analytics_tools
        assert "build_sql_query" not in analytics_tools
        assert "validate_sql_query" not in analytics_tools
        assert "execute_sql_query" not in analytics_tools
        assert "build_analytics_context" in analytics_tools
        assert "request_user_input" in analytics_tools
        assert "complete" in analytics_tools
