# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Unit tests for MCP result formatter."""

from starboard.agents.output.llm_responses import ToolResult
from starboard.mcp.result_formatter import format_tool_result


class TestFormatSuccess:
    """Tests for successful formatting."""

    def test_format_tool_result_success(self) -> None:
        tr = ToolResult(
            tool_call_id="c1",
            tool_name="resolve_query",
            content='{"sql": "SELECT 1"}',
        )
        resp = format_tool_result(tr, "ws-1")
        assert resp.status == "success"
        assert resp.workspace_id_used == "ws-1"
        assert resp.data == {"sql": "SELECT 1"}
        assert resp.truncated is False

    def test_format_tool_result_handles_raw_dict(self) -> None:
        data = {"key": "value", "num": 42}
        resp = format_tool_result(data, "ws-2")
        assert resp.status == "success"
        assert resp.data["key"] == "value"
        assert resp.data["num"] == 42

    def test_format_tool_result_empty_result(self) -> None:
        tr = ToolResult(tool_call_id="c1", tool_name="t", content="")
        resp = format_tool_result(tr, "ws-1")
        assert resp.status == "success"
        assert resp.data == {}

    def test_format_tool_result_preserves_trace_id_and_duration(self) -> None:
        tr = ToolResult(
            tool_call_id="c1",
            tool_name="t",
            content='{"x": 1}',
        )
        resp = format_tool_result(tr, "ws-1", trace_id="abc-123", duration_ms=42.5)
        assert resp.trace_id == "abc-123"
        assert resp.duration_ms == 42.5


class TestFormatError:
    """Tests for error formatting."""

    def test_format_tool_result_error_from_tool_result(self) -> None:
        tr = ToolResult(
            tool_call_id="c1",
            tool_name="bad_tool",
            content="",
            error="Something went wrong",
        )
        resp = format_tool_result(tr, "ws-1")
        assert resp.status == "error"
        assert resp.data == {"error": "Something went wrong"}


class TestTruncation:
    """Tests for truncation behavior."""

    def test_format_tool_result_truncates_when_over_limit(self) -> None:
        large_data = {"items": list(range(1000))}
        resp = format_tool_result(large_data, "ws-1", max_response_size_bytes=100)
        assert resp.truncated is True
        assert resp.status == "truncated"

    def test_format_tool_result_sets_truncated_flag(self) -> None:
        large_data = {"results": ["x" * 100 for _ in range(50)]}
        resp = format_tool_result(large_data, "ws-1", max_response_size_bytes=200)
        assert resp.truncated is True
        assert resp.warnings is not None
        assert any("truncated" in w.lower() for w in resp.warnings)

    def test_format_tool_result_sets_total_count_when_applicable(self) -> None:
        data = {"results": [1, 2, 3, 4, 5]}
        resp = format_tool_result(data, "ws-1")
        assert resp.total_count == 5

    def test_format_tool_result_no_total_count_without_list(self) -> None:
        data = {"key": "value"}
        resp = format_tool_result(data, "ws-1")
        assert resp.total_count is None

    def test_does_not_truncate_within_limit(self) -> None:
        data = {"x": 1}
        resp = format_tool_result(data, "ws-1", max_response_size_bytes=32_768)
        assert resp.truncated is False
        assert resp.status == "success"
