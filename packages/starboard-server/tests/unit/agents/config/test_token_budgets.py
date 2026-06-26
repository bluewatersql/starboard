# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for token budget enforcement defaults and per-domain limits.

Tests cover:
- enforce_budget defaults to True in AgentConfig
- enforce_budget defaults to True in TokenBudget
- Per-domain limits applied correctly via get_budget_for_domain
- Warning at 80% threshold
- Exhaustion log at 100% budget
"""

import structlog.testing
from starboard_server.adapters.llm.openai.tokens import TokenBudget
from starboard_server.agents.config.agent_config import (
    DEFAULT_TOKEN_BUDGETS,
    AgentConfig,
)


class TestAgentConfigBudgetDefaults:
    """Tests for AgentConfig budget defaults."""

    def test_enforce_budget_defaults_to_true(self):
        config = AgentConfig()
        assert config.enforce_budget is True

    def test_enforce_budget_can_be_disabled(self):
        config = AgentConfig(enforce_budget=False)
        assert config.enforce_budget is False


class TestPerDomainBudgets:
    """Tests for per-domain token budget limits."""

    def test_known_domains_have_budgets(self):
        assert AgentConfig.get_budget_for_domain("query") == 60_000
        assert AgentConfig.get_budget_for_domain("job") == 95_000
        assert AgentConfig.get_budget_for_domain("uc") == 120_000
        assert AgentConfig.get_budget_for_domain("cluster") == 72_000
        assert AgentConfig.get_budget_for_domain("warehouse") == 72_000
        assert AgentConfig.get_budget_for_domain("analytics") == 95_000
        assert AgentConfig.get_budget_for_domain("diagnostic") == 120_000
        assert AgentConfig.get_budget_for_domain("router") == 30_000

    def test_unknown_domain_falls_back(self):
        assert AgentConfig.get_budget_for_domain("unknown") == 25_000

    def test_default_token_budgets_dict_exists(self):
        assert isinstance(DEFAULT_TOKEN_BUDGETS, dict)
        assert len(DEFAULT_TOKEN_BUDGETS) == 8


class TestTokenBudgetEnforcement:
    """Tests for TokenBudget enforcement defaults."""

    def test_enforced_defaults_to_true(self):
        budget = TokenBudget()
        assert budget.enforced is True

    def test_enforced_can_be_disabled(self):
        budget = TokenBudget(enforced=False)
        assert budget.enforced is False


class TestTokenBudgetWarningThresholds:
    """Tests for 80% warning and 100% exhaustion logging."""

    def test_warning_at_80_percent(self):
        budget = TokenBudget(session_cap_tokens=1000, enforced=True)

        with structlog.testing.capture_logs() as logs:
            # Charge 800 tokens (80%)
            budget.charge(
                "analysis", "x" * 3200, "", prompt_tokens=800, completion_tokens=0
            )

        assert any("budget_warning" in log.get("event", "") for log in logs)

    def test_exhaustion_at_100_percent(self):
        budget = TokenBudget(session_cap_tokens=1000, enforced=True)

        with structlog.testing.capture_logs() as logs:
            # Charge 1000 tokens (100%)
            budget.charge(
                "analysis", "x" * 4000, "", prompt_tokens=1000, completion_tokens=0
            )

        assert any("budget_exhausted" in log.get("event", "") for log in logs)

    def test_no_warning_below_80_percent(self):
        budget = TokenBudget(session_cap_tokens=1000, enforced=True)

        with structlog.testing.capture_logs() as logs:
            # Charge 700 tokens (70%)
            budget.charge(
                "analysis", "x" * 2800, "", prompt_tokens=700, completion_tokens=0
            )

        budget_warnings = [
            log
            for log in logs
            if "budget_warning" in log.get("event", "")
            or "budget_exhausted" in log.get("event", "")
        ]
        assert len(budget_warnings) == 0
