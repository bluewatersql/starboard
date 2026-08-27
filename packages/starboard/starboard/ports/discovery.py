# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Entry-point discovery for port adapters (Phase-3 D-3.1).

This is the *public* half of the internal-package seam. Adapters for the four
C5 data-enablement ports are discovered through the ``starboard.port_adapters``
Python entry-point group and layered onto a :class:`~starboard.ports.registry.PortRegistry`.

**The contract (group ``starboard.port_adapters``).** Each entry point resolves
to a :class:`PortAdapterProvider` — an object exposing:

* ``port``: the target port, a :class:`~starboard.ports.registry.Port` value
  (``"log_retrieval" | "diagnostic_backend" | "nl_query" | "fleet_sql"``);
* ``tier``: ``"public"`` or ``"internal"``;
* ``create()``: a zero-argument factory returning the adapter instance.

Declared in a distributing package's ``pyproject.toml`` as, e.g.::

    [project.entry-points."starboard.port_adapters"]
    my_adapter = "my_pkg.adapters:my_provider"

**Additive by construction (UNIFIED_PLAN §3.5).** Discovery only *adds* to the
registry; it never removes a public adapter. A provider whose ``tier`` is
``"internal"`` is registered via :meth:`PortRegistry.register_internal`, so it is
selected **only** when the gate is open (``select_adapter(..., gate_open=True)``).
With no internal package installed, discovery finds no internal providers and the
registry is unchanged — every port still resolves to its public adapter and every
capability keeps working. The internal adapter *supersedes* the public one only
when both (a) it is installed/registered and (b) the gate is open.

The module deliberately depends on nothing heavier than
:mod:`starboard.ports.registry` and :mod:`importlib.metadata`, so importing it
never drags in the SDK/model stack.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from importlib import metadata
from typing import Any, Protocol, runtime_checkable

from starboard.ports.registry import Port, PortRegistry

#: The entry-point group name distributing packages register adapters under.
ENTRY_POINT_GROUP = "starboard.port_adapters"

#: Tier markers for :attr:`PortAdapterProvider.tier`.
PUBLIC_TIER = "public"
INTERNAL_TIER = "internal"

_VALID_TIERS = (PUBLIC_TIER, INTERNAL_TIER)


@runtime_checkable
class PortAdapterProvider(Protocol):
    """Structural contract every ``starboard.port_adapters`` entry point satisfies.

    Attributes:
        port: The target port (a :class:`Port` value or its string).
        tier: ``"public"`` or ``"internal"``.

    Methods:
        create: Zero-argument factory returning the adapter instance to register.
    """

    port: str
    tier: str

    def create(self) -> Any:
        """Build and return the adapter instance for :attr:`port`."""
        ...


@dataclass(frozen=True)
class SimplePortAdapterProvider:
    """A ready-made :class:`PortAdapterProvider` backed by a factory callable.

    Distributing packages (public or internal) can expose a module-level
    instance of this and point their entry point at it, instead of hand-rolling
    a provider class.

    Args:
        port: The target port.
        factory: Zero-argument callable that builds the adapter instance.
        tier: ``"public"`` (default) or ``"internal"``.
    """

    port: str
    factory: Any
    tier: str = PUBLIC_TIER

    def create(self) -> Any:
        return self.factory()


class _EntryPointLike(Protocol):
    """Structural type for an ``importlib.metadata.EntryPoint`` (test-injectable)."""

    name: str

    def load(self) -> Any: ...


def _iter_entry_points(
    *, group: str, entry_points: Iterable[_EntryPointLike] | None
) -> Iterable[_EntryPointLike]:
    """Yield entry points for ``group`` (or the injected ``entry_points``)."""
    if entry_points is not None:
        return entry_points
    return metadata.entry_points(group=group)


def discover_providers(
    *,
    group: str = ENTRY_POINT_GROUP,
    entry_points: Iterable[_EntryPointLike] | None = None,
    strict: bool = False,
) -> list[PortAdapterProvider]:
    """Load and validate every provider registered under ``group``.

    Args:
        group: Entry-point group name (defaults to :data:`ENTRY_POINT_GROUP`).
        entry_points: Optional pre-collected entry points (for tests); when
            ``None``, they are read from installed distributions.
        strict: When ``True``, an invalid entry point raises; otherwise it is
            skipped so one bad plugin cannot break discovery for the rest.

    Returns:
        The validated providers, in discovery order.
    """
    providers: list[PortAdapterProvider] = []
    for ep in _iter_entry_points(group=group, entry_points=entry_points):
        try:
            provider = ep.load()
            _validate_provider(provider)
        except Exception:
            if strict:
                raise
            continue
        providers.append(provider)
    return providers


def _validate_provider(provider: Any) -> None:
    """Raise ``TypeError``/``ValueError`` if ``provider`` breaks the contract."""
    if not isinstance(provider, PortAdapterProvider):
        raise TypeError(
            f"entry point object {provider!r} is not a PortAdapterProvider "
            "(needs 'port', 'tier', and a callable 'create')"
        )
    # Validate the declared port is one of the known ports (raises ValueError).
    Port(provider.port)
    if provider.tier not in _VALID_TIERS:
        raise ValueError(
            f"provider tier {provider.tier!r} must be one of {_VALID_TIERS}"
        )


def register_providers(
    registry: PortRegistry, providers: Iterable[PortAdapterProvider]
) -> PortRegistry:
    """Register each provider's adapter into ``registry`` by tier.

    ``internal``-tier providers register via
    :meth:`PortRegistry.register_internal` (selected only when the gate is open);
    everything else registers via :meth:`PortRegistry.register_public`. Returns
    the same ``registry`` for chaining.
    """
    for provider in providers:
        adapter = provider.create()
        if provider.tier == INTERNAL_TIER:
            registry.register_internal(provider.port, adapter)
        else:
            registry.register_public(provider.port, adapter)
    return registry


def install_entry_point_adapters(
    registry: PortRegistry,
    *,
    group: str = ENTRY_POINT_GROUP,
    entry_points: Iterable[_EntryPointLike] | None = None,
    strict: bool = False,
) -> PortRegistry:
    """Discover ``group`` providers and register them onto ``registry``.

    This is the single call app wiring makes to layer discovered adapters on top
    of the directly-registered public adapters. Additive: with no internal
    package installed, nothing internal is registered and selection is unchanged.
    """
    providers = discover_providers(
        group=group, entry_points=entry_points, strict=strict
    )
    return register_providers(registry, providers)
