# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Unit tests for MCPCostTag."""

from dataclasses import FrozenInstanceError

import pytest
from starboard.mcp.config import CostAttribution, WorkspaceProfile
from starboard.mcp.observability import MCPCostTag


class TestMCPCostTag:
    """Tests for MCPCostTag dataclass."""

    def test_mcp_cost_tag_frozen(self) -> None:
        tag = MCPCostTag(agent="query", workspace_id="prod", mcp_session_id="s1")
        with pytest.raises(FrozenInstanceError):
            tag.agent = "job"  # type: ignore[misc]

    def test_mcp_cost_tag_default_feature(self) -> None:
        tag = MCPCostTag(agent="query", workspace_id="prod", mcp_session_id="s1")
        assert tag.feature == "mcp"

    def test_mcp_cost_tag_from_workspace_profile(self) -> None:
        profile = WorkspaceProfile(
            host="https://prod.databricks.com",
            token_env="PROD_TOKEN",
            cost_attribution=CostAttribution(
                tenant_id="tenant-1",
                user_id="user@example.com",
                team="data-eng",
                environment="production",
            ),
        )
        attr = profile.cost_attribution
        assert attr is not None
        tag = MCPCostTag(
            agent="query",
            workspace_id="prod",
            mcp_session_id="s1",
            tenant_id=attr.tenant_id,
            user_id=attr.user_id,
            team=attr.team,
            environment=attr.environment,
        )
        assert tag.tenant_id == "tenant-1"
        assert tag.user_id == "user@example.com"
        assert tag.team == "data-eng"
        assert tag.environment == "production"

    def test_mcp_cost_tag_to_dict(self) -> None:
        tag = MCPCostTag(
            agent="query",
            workspace_id="prod",
            mcp_session_id="s1",
            tenant_id="t1",
        )
        d = tag.to_dict()
        assert d["feature"] == "mcp"
        assert d["agent"] == "query"
        assert d["workspace_id"] == "prod"
        assert d["tenant_id"] == "t1"
        # None values should be omitted
        assert "team" not in d
        assert "environment" not in d

    def test_mcp_cost_tag_optional_fields_default_none(self) -> None:
        tag = MCPCostTag(agent="job", workspace_id="dev", mcp_session_id="s2")
        assert tag.tenant_id is None
        assert tag.user_id is None
        assert tag.team is None
        assert tag.environment is None
