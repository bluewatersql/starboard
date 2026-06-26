# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Additional golden tests for Analytics Agent edge cases and scenarios.

These tests capture prompt behavior for edge cases like:
- Very long queries
- Special characters
- Multiple domains
- Complex analytical requests
"""

from __future__ import annotations

import pytest
from starboard_core.domain.models.llm import OptimizationMode
from starboard_server.prompts.factories import build_analytics_prompt
from syrupy.assertion import SnapshotAssertion


class TestAnalyticsEdgeCasePrompts:
    """Golden tests for edge case prompt scenarios."""

    def test_very_long_query_goal(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Prompt with very long goal statement."""
        long_goal = (
            "I need a comprehensive analysis of our Databricks costs over the past 6 months, "
            "broken down by workspace, warehouse type (SQL vs Jobs), cluster configuration, "
            "and job frequency. Specifically, I want to identify the top 10 most expensive "
            "jobs, understand if there are any wasteful spending patterns like idle clusters "
            "or oversized warehouses, and get recommendations for cost optimization including "
            "right-sizing warehouses, adjusting auto-stop settings, and optimizing job schedules. "
            "Additionally, I need projections for the next quarter based on current trends and "
            "a comparison against our allocated budget of $500,000 per month."
        )

        prompt = build_analytics_prompt(
            mode=OptimizationMode.ONLINE,
            goal=long_goal,
            budget_remaining=1_500_000,
        )

        assert snapshot == prompt

    def test_special_characters_in_goal(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Prompt with special characters in goal."""
        goal_with_special_chars = (
            "Analyze costs for warehouses: 'prod-etl' & 'prod-analytics' "
            "(including $USD calculations). Compare Q1 vs Q2 performance @ 95% confidence."
        )

        prompt = build_analytics_prompt(
            mode=OptimizationMode.ONLINE,
            goal=goal_with_special_chars,
            budget_remaining=50_000,
        )

        assert snapshot == prompt

    def test_multi_domain_analysis_goal(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Prompt for multi-domain cost analysis."""
        goal = (
            "Cross-domain analysis: Compare costs between SQL warehouses and job clusters. "
            "Include Unity Catalog storage costs and Delta Live Tables pipeline expenses. "
            "Identify which workload type (ETL, BI, ML) drives the most cost."
        )

        prompt = build_analytics_prompt(
            mode=OptimizationMode.ONLINE,
            goal=goal,
            budget_remaining=100_000,
        )

        assert snapshot == prompt

    def test_diagnostic_mode_with_error_scenario(
        self, snapshot: SnapshotAssertion
    ) -> None:
        """Golden test: Diagnostic mode for cost anomaly investigation."""
        goal = (
            "Investigate sudden 300% cost spike in warehouse 'analytics-prod' on 2024-12-15. "
            "Identify which queries caused the increase and determine if it was a legitimate "
            "workload change or a configuration issue."
        )

        prompt = build_analytics_prompt(
            mode=OptimizationMode.DIAGNOSTIC,
            goal=goal,
            budget_remaining=75_000,
        )

        assert snapshot == prompt

    def test_offline_mode_comprehensive_report(
        self, snapshot: SnapshotAssertion
    ) -> None:
        """Golden test: Offline mode for comprehensive cost report."""
        goal = (
            "Generate quarterly FinOps report with cost trends, efficiency metrics, "
            "budget variance analysis, and optimization opportunities. Include executive "
            "summary and detailed recommendations."
        )

        prompt = build_analytics_prompt(
            mode=OptimizationMode.OFFLINE,
            goal=goal,
            budget_remaining=200_000,
        )

        assert snapshot == prompt

    def test_zero_budget_remaining(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Prompt when budget is depleted."""
        prompt = build_analytics_prompt(
            mode=OptimizationMode.ONLINE,
            goal="Urgent: Budget exceeded. Identify top cost drivers immediately.",
            budget_remaining=0,
        )

        assert snapshot == prompt

    def test_large_budget_remaining(self, snapshot: SnapshotAssertion) -> None:
        """Golden test: Prompt with very large budget remaining."""
        prompt = build_analytics_prompt(
            mode=OptimizationMode.ONLINE,
            goal="Optimize costs while maintaining performance",
            budget_remaining=10_000_000,  # $10M remaining
        )

        assert snapshot == prompt


class TestAnalyticsPromptContentValidation:
    """Validation tests for edge case prompt content (non-snapshot)."""

    def test_long_goal_preserved_in_prompt(self) -> None:
        """Verify long goals are fully preserved in prompt."""
        long_goal = "A" * 1000  # 1000 character goal

        prompt = build_analytics_prompt(
            mode=OptimizationMode.ONLINE,
            goal=long_goal,
            budget_remaining=50_000,
        )

        assert long_goal in prompt, "Long goal should be preserved in full"

    def test_special_characters_not_mangled(self) -> None:
        """Verify special characters are not mangled in prompt."""
        special_chars = "'\"&<>()[]{}@#$%^*+=|\\:;"
        goal = f"Analyze costs for: {special_chars}"

        prompt = build_analytics_prompt(
            mode=OptimizationMode.ONLINE,
            goal=goal,
            budget_remaining=50_000,
        )

        assert special_chars in prompt, "Special characters should be preserved"

    def test_zero_budget_includes_warning_context(self) -> None:
        """Verify zero budget scenario provides appropriate context."""
        prompt = build_analytics_prompt(
            mode=OptimizationMode.ONLINE,
            goal="Budget analysis",
            budget_remaining=0,
        )

        # Should mention budget constraint
        assert "0" in prompt or "zero" in prompt.lower() or "depleted" in prompt.lower()

    def test_diagnostic_mode_includes_investigation_context(self) -> None:
        """Verify diagnostic mode prompt includes investigation framing."""
        prompt = build_analytics_prompt(
            mode=OptimizationMode.DIAGNOSTIC,
            goal="Investigate cost spike",
            budget_remaining=50_000,
        )

        # Should include diagnostic-specific language
        assert "diagnostic" in prompt.lower() or "investigate" in prompt.lower()

    def test_offline_mode_allows_comprehensive_analysis(self) -> None:
        """Verify offline mode prompt allows for longer analysis."""
        prompt = build_analytics_prompt(
            mode=OptimizationMode.OFFLINE,
            goal="Quarterly report",
            budget_remaining=50_000,
        )

        # Should mention offline context (no strict time limits)
        assert "offline" in prompt.lower()


class TestAnalyticsPromptConsistency:
    """Tests for prompt consistency across scenarios."""

    @pytest.mark.parametrize(
        "goal",
        [
            "Simple cost query",
            "Complex multi-domain analysis with long explanation and multiple requirements",
            "Cost query with 'special' & unusual (characters) @#$%",
        ],
    )
    def test_all_goals_produce_valid_prompts(self, goal: str) -> None:
        """Verify all goal variations produce valid prompts."""
        prompt = build_analytics_prompt(
            mode=OptimizationMode.ONLINE,
            goal=goal,
            budget_remaining=50_000,
        )

        # Basic validity checks
        assert len(prompt) > 1000, "Prompt should be substantial"
        assert goal in prompt, "Goal should appear in prompt"
        assert "analytics" in prompt.lower() or "finops" in prompt.lower()

    @pytest.mark.parametrize(
        "budget",
        [0, 100, 10_000, 1_000_000, 100_000_000],
    )
    def test_all_budgets_produce_valid_prompts(self, budget: int) -> None:
        """Verify all budget values produce valid prompts."""
        prompt = build_analytics_prompt(
            mode=OptimizationMode.ONLINE,
            goal="Cost analysis",
            budget_remaining=budget,
        )

        assert len(prompt) > 1000, "Prompt should be substantial"
        # Budget may not appear in prompt depending on prompt template
        # Just verify prompt is valid
        assert "analytics" in prompt.lower() or "finops" in prompt.lower()
