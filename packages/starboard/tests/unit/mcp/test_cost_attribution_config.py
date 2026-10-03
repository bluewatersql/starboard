# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Unit tests for CostAttribution config model."""

import pytest
from pydantic import ValidationError
from starboard.mcp.config import (
    CostAttribution,
    MCPServerConfig,
    WorkspaceProfile,
)


class TestCostAttributionModel:
    """Tests for CostAttribution Pydantic model."""

    def test_cost_attribution_model_parses(self) -> None:
        ca = CostAttribution(
            tenant_id="t1",
            user_id="u1",
            team="data",
            environment="production",
        )
        assert ca.tenant_id == "t1"
        assert ca.user_id == "u1"
        assert ca.team == "data"
        assert ca.environment == "production"

    def test_cost_attribution_frozen(self) -> None:
        ca = CostAttribution(tenant_id="t1")
        with pytest.raises(ValidationError):
            ca.tenant_id = "t2"  # type: ignore[misc]

    def test_cost_attribution_all_optional(self) -> None:
        ca = CostAttribution()
        assert ca.tenant_id is None
        assert ca.user_id is None
        assert ca.team is None
        assert ca.environment is None


class TestWorkspaceProfileCostAttribution:
    """Tests for WorkspaceProfile with cost_attribution."""

    def test_workspace_profile_accepts_cost_attribution(self) -> None:
        profile = WorkspaceProfile(
            host="https://prod.databricks.com",
            token_env="PROD_TOKEN",
            cost_attribution=CostAttribution(tenant_id="t1"),
        )
        assert profile.cost_attribution is not None
        assert profile.cost_attribution.tenant_id == "t1"

    def test_workspace_profile_cost_attribution_defaults_none(self) -> None:
        profile = WorkspaceProfile(
            host="https://prod.databricks.com",
            token_env="PROD_TOKEN",
        )
        assert profile.cost_attribution is None

    def test_workspace_profile_token_budget(self) -> None:
        profile = WorkspaceProfile(
            host="https://prod.databricks.com",
            token_env="PROD_TOKEN",
            token_budget=100_000,
        )
        assert profile.token_budget == 100_000


class TestMCPServerConfigTokenBudget:
    """Tests for MCPServerConfig with token_budget."""

    def test_server_config_token_budget(self) -> None:
        config = MCPServerConfig(
            default_workspace_id="prod",
            workspaces={
                "prod": WorkspaceProfile(
                    host="https://prod.databricks.com",
                    token_env="PROD_TOKEN",
                ),
            },
            token_budget=500_000,
        )
        assert config.token_budget == 500_000

    def test_server_config_token_budget_defaults_none(self) -> None:
        config = MCPServerConfig(
            default_workspace_id="prod",
            workspaces={
                "prod": WorkspaceProfile(
                    host="https://prod.databricks.com",
                    token_env="PROD_TOKEN",
                ),
            },
        )
        assert config.token_budget is None
