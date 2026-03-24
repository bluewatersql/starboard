# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""Unit tests for MCP response and error models."""

import pytest
from starboard_server.mcp.models import MCPAgentResponse, MCPError, MCPToolResponse


class TestMCPToolResponse:
    """Tests for MCPToolResponse."""

    def test_success_response(self) -> None:
        resp = MCPToolResponse(
            status="success",
            workspace_id_used="prod",
            data={"rows": [1, 2, 3]},
        )
        assert resp.status == "success"
        assert resp.workspace_id_used == "prod"
        assert resp.data == {"rows": [1, 2, 3]}
        assert resp.truncated is False
        assert resp.total_count is None

    def test_truncated_response(self) -> None:
        resp = MCPToolResponse(
            status="truncated",
            workspace_id_used="dev",
            data={"rows": [1]},
            truncated=True,
            total_count=100,
        )
        assert resp.status == "truncated"
        assert resp.truncated is True
        assert resp.total_count == 100

    def test_frozen_model(self) -> None:
        resp = MCPToolResponse(
            status="success",
            workspace_id_used="prod",
            data={},
        )
        with pytest.raises(Exception):
            resp.status = "error"  # type: ignore[misc]


class TestMCPError:
    """Tests for MCPError."""

    def test_serialization(self) -> None:
        err = MCPError(
            code="EXEC_FAILED",
            message="Tool crashed",
            details={"tool": "resolve_query"},
        )
        d = err.model_dump()
        assert d["code"] == "EXEC_FAILED"
        assert d["message"] == "Tool crashed"
        assert d["details"] == {"tool": "resolve_query"}
        assert d["retry_after"] is None

    def test_retry_after(self) -> None:
        err = MCPError(
            code="RATE_LIMITED",
            message="Slow down",
            retry_after=60,
        )
        assert err.retry_after == 60

    def test_frozen_model(self) -> None:
        err = MCPError(code="X", message="Y")
        with pytest.raises(Exception):
            err.code = "Z"  # type: ignore[misc]


class TestMCPAgentResponse:
    """Tests for MCPAgentResponse."""

    def test_agent_response(self) -> None:
        resp = MCPAgentResponse(
            status="success",
            workspace_id_used="prod",
            agent_domain="query",
            response_text="Your query is optimized.",
            tools_used=["resolve_query", "analyze_query_plan"],
            confidence=0.95,
        )
        assert resp.agent_domain == "query"
        assert resp.confidence == 0.95
        assert len(resp.tools_used) == 2

    def test_frozen_model(self) -> None:
        resp = MCPAgentResponse(
            status="success",
            workspace_id_used="x",
            agent_domain="job",
            response_text="ok",
        )
        with pytest.raises(Exception):
            resp.status = "error"  # type: ignore[misc]


class TestAllModelsFrozen:
    """Verify all MCP models use frozen config."""

    @pytest.mark.parametrize(
        "model_cls",
        [MCPToolResponse, MCPError, MCPAgentResponse],
    )
    def test_model_is_frozen(self, model_cls: type) -> None:
        assert model_cls.model_config.get("frozen") is True
