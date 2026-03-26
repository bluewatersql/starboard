# Copyright (c) 2025 Starboard AI
# Licensed under the MIT License (see LICENSE file in the root directory)

"""Per-workspace circuit breaker registry.

Lazily creates and manages ``AsyncCircuitBreaker`` instances for each
workspace, allowing independent failure isolation.
"""

from __future__ import annotations

from starboard_server.infra.observability.logging import get_logger

from starboard_server.infra.reliability.circuit_breaker import (
    AsyncCircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
)

logger = get_logger(__name__)


class MCPCircuitBreakerRegistry:
    """Manage per-workspace circuit breakers.

    Breakers are lazily created on first access for a given workspace ID.
    Each workspace has an independent breaker so that failures in one
    workspace do not affect others.

    Args:
        config: Circuit breaker configuration applied to all breakers.
            Uses defaults if ``None``.
    """

    def __init__(self, config: CircuitBreakerConfig | None = None) -> None:
        self._config = config or CircuitBreakerConfig()
        self._breakers: dict[str, AsyncCircuitBreaker] = {}

    def get(self, workspace_id: str) -> AsyncCircuitBreaker:
        """Get or create a circuit breaker for a workspace.

        Args:
            workspace_id: Workspace identifier.

        Returns:
            The circuit breaker instance for this workspace.
        """
        if workspace_id not in self._breakers:
            self._breakers[workspace_id] = AsyncCircuitBreaker(
                config=self._config,
                name=f"mcp-{workspace_id}",
            )
            logger.debug(
                "circuit_breaker_created",
                workspace_id=workspace_id,
            )
        return self._breakers[workspace_id]

    def get_all_states(self) -> dict[str, CircuitState]:
        """Get the current state of all created breakers.

        Returns:
            Mapping of workspace ID to circuit state.
        """
        return {ws_id: breaker.state for ws_id, breaker in self._breakers.items()}
