# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for ToolExecutor circuit breaker integration.

Tests cover:
- Tool failures increment circuit breaker
- Circuit opens after threshold failures
- Open circuit returns error result without calling tool
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard.agents.domain.tool_executor import (
    ToolExecutor,
)
from starboard.agents.output.llm_responses import ToolCall, ToolResult


def _make_tool_call(name: str = "test_tool", arguments: str = "{}") -> ToolCall:
    return ToolCall(id="tc_1", name=name, arguments=arguments)


def _make_tool_result(error: str | None = None) -> ToolResult:
    return ToolResult(
        tool_call_id="tc_1",
        tool_name="test_tool",
        content='{"ok": true}',
        error=error,
    )


class TestToolExecutorCircuitBreaker:
    """Tests for circuit breaker integration in ToolExecutor."""

    @pytest.mark.asyncio
    async def test_tool_failures_increment_circuit_breaker(self):
        """Tool execution exceptions are recorded by circuit breaker."""
        registry = MagicMock()
        registry.execute_tool = AsyncMock(side_effect=RuntimeError("API down"))

        executor = ToolExecutor(
            tool_registry=registry,
            enable_retry=False,
            circuit_breaker_threshold=5,
        )

        tc = _make_tool_call()
        await executor._execute_single_tool(tc, {})

        cb = executor._circuit_breakers["test_tool"]
        assert cb.get_failure_count() == 1

    @pytest.mark.asyncio
    async def test_circuit_opens_after_threshold_failures(self):
        """Circuit opens after enough consecutive failures."""
        registry = MagicMock()
        registry.execute_tool = AsyncMock(side_effect=RuntimeError("API down"))

        executor = ToolExecutor(
            tool_registry=registry,
            enable_retry=False,
            circuit_breaker_threshold=3,
        )

        tc = _make_tool_call()
        for _ in range(3):
            await executor._execute_single_tool(tc, {})

        cb = executor._circuit_breakers["test_tool"]
        from starboard.infra.reliability.circuit_breaker import CircuitState

        assert cb._state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_open_circuit_returns_error_without_calling_tool(self):
        """When circuit is open, tool is not called and error result returned."""
        call_count = 0

        async def counting_execute(**kwargs):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("API down")

        registry = MagicMock()
        registry.execute_tool = AsyncMock(side_effect=counting_execute)

        executor = ToolExecutor(
            tool_registry=registry,
            enable_retry=False,
            circuit_breaker_threshold=2,
        )

        tc = _make_tool_call()

        # Trigger 2 failures to open circuit
        await executor._execute_single_tool(tc, {})
        await executor._execute_single_tool(tc, {})
        assert call_count == 2

        # Next call should be rejected by circuit breaker
        result = await executor._execute_single_tool(tc, {})
        assert result.success is False
        assert "Circuit breaker open" in (result.error or "")
        # Tool was NOT called again
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_successful_tool_resets_failure_count(self):
        """A successful tool call resets the circuit breaker failure count."""
        call_idx = 0

        async def alternating_execute(**kwargs):
            nonlocal call_idx
            call_idx += 1
            if call_idx <= 2:
                raise RuntimeError("API down")
            return _make_tool_result()

        registry = MagicMock()
        registry.execute_tool = AsyncMock(side_effect=alternating_execute)

        executor = ToolExecutor(
            tool_registry=registry,
            enable_retry=False,
            circuit_breaker_threshold=5,
        )

        tc = _make_tool_call()

        # 2 failures
        await executor._execute_single_tool(tc, {})
        await executor._execute_single_tool(tc, {})
        cb = executor._circuit_breakers["test_tool"]
        assert cb.get_failure_count() == 2

        # 1 success resets
        result = await executor._execute_single_tool(tc, {})
        assert result.success is True
        assert cb.get_failure_count() == 0
