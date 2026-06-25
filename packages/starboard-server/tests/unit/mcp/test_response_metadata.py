# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Unit tests for MCPResponseMetadata and MCPAgentResponse models."""

import pytest
from pydantic import ValidationError
from starboard_server.mcp.models import MCPAgentResponse, MCPResponseMetadata


class TestMCPResponseMetadata:
    """Tests for MCPResponseMetadata Pydantic model."""

    def test_metadata_parses_required_fields(self) -> None:
        meta = MCPResponseMetadata(
            workspace_id_used="prod",
            domain_selected="query",
            confidence=0.95,
        )
        assert meta.workspace_id_used == "prod"
        assert meta.domain_selected == "query"
        assert meta.confidence == 0.95

    def test_metadata_frozen(self) -> None:
        meta = MCPResponseMetadata(
            workspace_id_used="prod",
            domain_selected="query",
            confidence=0.95,
        )
        with pytest.raises(ValidationError):
            meta.confidence = 0.5  # type: ignore[misc]

    def test_metadata_defaults(self) -> None:
        meta = MCPResponseMetadata(
            workspace_id_used="prod",
            domain_selected="query",
            confidence=0.8,
        )
        assert meta.low_confidence is False
        assert meta.auto_selected_path is False
        assert meta.reasoning_summary == ""
        assert meta.trace_id == ""
        assert meta.duration_ms == 0.0
        assert meta.conversation_id is None

    def test_metadata_all_fields(self) -> None:
        meta = MCPResponseMetadata(
            workspace_id_used="dev",
            domain_selected="job",
            confidence=0.65,
            low_confidence=True,
            auto_selected_path=True,
            reasoning_summary="Routed to job agent",
            trace_id="abc-123",
            duration_ms=42.5,
            conversation_id="conv-1",
        )
        assert meta.low_confidence is True
        assert meta.auto_selected_path is True
        assert meta.reasoning_summary == "Routed to job agent"
        assert meta.trace_id == "abc-123"
        assert meta.duration_ms == 42.5
        assert meta.conversation_id == "conv-1"

    def test_metadata_serialization(self) -> None:
        meta = MCPResponseMetadata(
            workspace_id_used="prod",
            domain_selected="query",
            confidence=0.95,
            trace_id="t-1",
        )
        d = meta.model_dump()
        assert d["workspace_id_used"] == "prod"
        assert d["domain_selected"] == "query"
        assert d["confidence"] == 0.95
        assert d["trace_id"] == "t-1"


class TestMCPAgentResponseWithMetadata:
    """Tests for MCPAgentResponse with envelope and mcp_metadata fields."""

    def test_agent_response_with_metadata(self) -> None:
        meta = MCPResponseMetadata(
            workspace_id_used="prod",
            domain_selected="query",
            confidence=0.9,
        )
        resp = MCPAgentResponse(
            status="success",
            workspace_id_used="prod",
            agent_domain="query",
            response_text="Query optimized",
            mcp_metadata=meta,
        )
        assert resp.mcp_metadata is not None
        assert resp.mcp_metadata.confidence == 0.9

    def test_agent_response_with_envelope(self) -> None:
        resp = MCPAgentResponse(
            status="success",
            workspace_id_used="prod",
            agent_domain="query",
            response_text="Done",
            envelope={"domain": "query", "status": "success", "payload": {}},
        )
        assert resp.envelope is not None
        assert resp.envelope["domain"] == "query"

    def test_agent_response_metadata_defaults_none(self) -> None:
        resp = MCPAgentResponse(
            status="success",
            workspace_id_used="prod",
            agent_domain="query",
            response_text="ok",
        )
        assert resp.mcp_metadata is None
        assert resp.envelope is None

    def test_agent_response_frozen(self) -> None:
        resp = MCPAgentResponse(
            status="success",
            workspace_id_used="prod",
            agent_domain="query",
            response_text="ok",
        )
        with pytest.raises(ValidationError):
            resp.status = "error"  # type: ignore[misc]

    def test_agent_response_serialization_with_metadata(self) -> None:
        meta = MCPResponseMetadata(
            workspace_id_used="prod",
            domain_selected="query",
            confidence=0.85,
            low_confidence=True,
            auto_selected_path=True,
        )
        resp = MCPAgentResponse(
            status="success",
            workspace_id_used="prod",
            agent_domain="query",
            response_text="Result",
            confidence=0.85,
            trace_id="t-1",
            duration_ms=100.0,
            envelope={"status": "success"},
            mcp_metadata=meta,
        )
        d = resp.model_dump()
        assert d["mcp_metadata"]["confidence"] == 0.85
        assert d["mcp_metadata"]["low_confidence"] is True
        assert d["envelope"]["status"] == "success"
