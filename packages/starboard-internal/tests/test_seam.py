# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Entry-point seam tests for the gated internal adapters (Phase-3 D6/D7/D8).

Verifies the real ``starboard_internal`` providers (not injected fakes):

1. All four module-level providers satisfy the public ``PortAdapterProvider``
   contract and are ``internal``-tier providers for their declared port.
2. ``create()`` builds the concrete adapter class for each port.
3. Registered via the public discovery helper, each supersedes the public
   adapter ONLY when the gate is open (§3.5 additive invariant).
4. When installed, all four providers are discoverable through the real
   ``starboard.port_adapters`` entry-point group, one per port.
"""

from __future__ import annotations

from importlib import metadata

import pytest
from starboard.ports.discovery import (
    ENTRY_POINT_GROUP,
    INTERNAL_TIER,
    PortAdapterProvider,
    discover_providers,
    register_providers,
)
from starboard.ports.registry import Port, PortRegistry
from starboard_internal.adapters import (
    CentralizedFleetSqlAdapter,
    CuratedGenieRoomAdapter,
    DbrDoctorAdapter,
    LogsSummariserAdapter,
    diagnostic_backend_provider,
    fleet_sql_provider,
    log_retrieval_provider,
    nl_query_provider,
)

_PROVIDERS = (
    (log_retrieval_provider, Port.LOG_RETRIEVAL, LogsSummariserAdapter),
    (diagnostic_backend_provider, Port.DIAGNOSTIC_BACKEND, DbrDoctorAdapter),
    (fleet_sql_provider, Port.FLEET_SQL, CentralizedFleetSqlAdapter),
    (nl_query_provider, Port.NL_QUERY, CuratedGenieRoomAdapter),
)


@pytest.mark.unit
class TestProvidersSatisfyContract:
    def test_all_providers_are_internal_tier_for_their_port(self) -> None:
        for provider, port, _ in _PROVIDERS:
            assert isinstance(provider, PortAdapterProvider)
            assert provider.port == port
            assert provider.tier == INTERNAL_TIER

    def test_create_builds_the_concrete_adapter(self) -> None:
        for provider, _, adapter_cls in _PROVIDERS:
            assert isinstance(provider.create(), adapter_cls)

    def test_one_provider_per_distinct_port(self) -> None:
        ports = [port for _, port, _ in _PROVIDERS]
        assert sorted(ports) == sorted(set(ports)) == sorted(Port)


@pytest.mark.unit
class TestSeamSelection:
    def test_internal_supersedes_public_only_when_gate_open(self) -> None:
        reg = PortRegistry()
        for _, port, _ in _PROVIDERS:
            reg.register_public(port, f"public-{port}")
        register_providers(reg, [p for p, _, _ in _PROVIDERS])

        for _, port, adapter_cls in _PROVIDERS:
            # Gate closed -> public path preserved (additive invariant).
            assert reg.select_adapter(port, gate_open=False) == f"public-{port}"
            # Gate open -> the internal adapter supersedes.
            assert isinstance(
                reg.select_adapter(port, gate_open=True), adapter_cls
            )


@pytest.mark.unit
class TestEntryPointDiscoverable:
    def test_all_four_providers_discoverable_via_entry_point_group(self) -> None:
        eps = metadata.entry_points(group=ENTRY_POINT_GROUP)
        if not eps:
            pytest.skip("starboard-internal not installed in this environment")
        providers = discover_providers(strict=True)
        discovered_ports = {p.port for p in providers}
        for _, port, _ in _PROVIDERS:
            assert port in discovered_ports
        assert all(isinstance(p, PortAdapterProvider) for p in providers)
