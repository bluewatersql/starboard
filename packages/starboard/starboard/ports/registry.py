# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Port -> adapter selection seam (Phase-2 C5).

The registry threads a ``gate_open`` flag (from the employee-context detector on
the auth resolver) into adapter selection. In Phase 2 **only public adapters are
registered**, so ``select_adapter`` always returns the public adapter regardless
of the gate — this is the additive invariant (UNIFIED_PLAN §3.5): closing the
gate never removes a capability, and (with no internal adapter wired) a wrong
"internal context" signal cannot leak data.

Internal adapters attach in Phase 3 via :meth:`PortRegistry.register_internal`;
they are then selected only when the gate is open.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class Port(StrEnum):
    """The four internal-data-enablement ports."""

    LOG_RETRIEVAL = "log_retrieval"
    DIAGNOSTIC_BACKEND = "diagnostic_backend"
    NL_QUERY = "nl_query"
    FLEET_SQL = "fleet_sql"


class PortRegistry:
    """Holds public (and, in Phase 3, internal) adapters per port."""

    def __init__(self) -> None:
        self._public: dict[Port, Any] = {}
        self._internal: dict[Port, Any] = {}

    def register_public(self, port: Port | str, adapter: Any) -> None:
        """Register the PUBLIC adapter for ``port`` (the universal path)."""
        self._public[Port(port)] = adapter

    def register_internal(self, port: Port | str, adapter: Any) -> None:
        """Register a gated INTERNAL adapter for ``port`` (Phase 3).

        Registering an internal adapter does not, by itself, change behavior:
        it is selected only when ``select_adapter`` is called with
        ``gate_open=True``.
        """
        self._internal[Port(port)] = adapter

    def has_internal(self, port: Port | str) -> bool:
        """Whether an internal adapter is registered for ``port``."""
        return Port(port) in self._internal

    def select_adapter(self, port: Port | str, *, gate_open: bool = False) -> Any:
        """Return the adapter to use for ``port``.

        Returns the internal adapter only when the gate is open **and** an
        internal adapter is registered; otherwise the public adapter. Raises
        ``KeyError`` if no public adapter is registered for the port.
        """
        port = Port(port)
        if gate_open and port in self._internal:
            return self._internal[port]
        return self._public[port]
