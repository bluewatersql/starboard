# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.

"""Unit tests for MCPCircuitBreakerRegistry."""

from starboard.infra.reliability.circuit_breaker import (
    CircuitBreakerConfig,
    CircuitState,
)
from starboard.mcp.circuit_breaker_registry import MCPCircuitBreakerRegistry


class TestLazyCreation:
    """Tests for lazy breaker creation."""

    def test_lazy_creation(self) -> None:
        registry = MCPCircuitBreakerRegistry()
        assert registry.get_all_states() == {}
        breaker = registry.get("workspace-1")
        assert breaker is not None
        assert len(registry.get_all_states()) == 1

    def test_same_workspace_returns_same_breaker(self) -> None:
        registry = MCPCircuitBreakerRegistry()
        b1 = registry.get("ws-a")
        b2 = registry.get("ws-a")
        assert b1 is b2

    def test_different_workspaces_independent(self) -> None:
        registry = MCPCircuitBreakerRegistry()
        b1 = registry.get("ws-a")
        b2 = registry.get("ws-b")
        assert b1 is not b2
        assert b1.name != b2.name


class TestGetAllStates:
    """Tests for state reporting."""

    def test_get_all_states(self) -> None:
        registry = MCPCircuitBreakerRegistry()
        registry.get("ws-1")
        registry.get("ws-2")
        states = registry.get_all_states()
        assert len(states) == 2
        assert states["ws-1"] == CircuitState.CLOSED
        assert states["ws-2"] == CircuitState.CLOSED


class TestCustomConfig:
    """Tests for custom circuit breaker configuration."""

    def test_custom_config_applied(self) -> None:
        config = CircuitBreakerConfig(failure_threshold=3, recovery_timeout=30.0)
        registry = MCPCircuitBreakerRegistry(config=config)
        breaker = registry.get("ws-1")
        assert breaker.failure_threshold == 3
        assert breaker.recovery_timeout == 30.0
