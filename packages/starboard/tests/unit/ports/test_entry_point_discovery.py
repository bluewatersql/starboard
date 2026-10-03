# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the ``starboard.port_adapters`` entry-point seam (Phase-3 D-3.1).

Proves the governance-critical properties of the internal-package seam without
requiring ``starboard-internal`` to be installed (entry points are injected):

1. **Parity / additive invariant** — with no internal package present, discovery
   registers nothing internal; every port resolves to its PUBLIC adapter and the
   capability contract is satisfied.
2. **Supersede-when-open** — a discovered ``internal``-tier provider is selected
   ONLY when the gate is open; with the gate closed the public adapter is kept.
3. **Validation** — malformed entry points are skipped (or raised under
   ``strict``) and cannot corrupt the registry.
4. **Governance** — the public package trees contain no ``starboard_internal``
   import (the import-linter contract, asserted here as a source-tree grep).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starboard.ports.discovery import (
    ENTRY_POINT_GROUP,
    INTERNAL_TIER,
    PUBLIC_TIER,
    SimplePortAdapterProvider,
    discover_providers,
    install_entry_point_adapters,
    register_providers,
)
from starboard.ports.registry import Port, PortRegistry


class _FakeEntryPoint:
    """Minimal stand-in for ``importlib.metadata.EntryPoint``."""

    def __init__(self, name: str, obj: object) -> None:
        self.name = name
        self._obj = obj

    def load(self) -> object:
        if isinstance(self._obj, Exception):
            raise self._obj
        return self._obj


class _PublicMarker:
    """A trivial public adapter instance (capability = returns its port name)."""

    def __init__(self, port: str) -> None:
        self.port = port


def _public_registry() -> PortRegistry:
    """A registry with all four public adapters directly registered (app wiring)."""
    reg = PortRegistry()
    for port in Port:
        reg.register_public(port, _PublicMarker(str(port)))
    return reg


@pytest.mark.unit
class TestParityInternalAbsent:
    def test_no_entry_points_registers_nothing_internal(self) -> None:
        reg = _public_registry()
        install_entry_point_adapters(reg, entry_points=[])
        for port in Port:
            assert reg.has_internal(port) is False
            # Capability still satisfied via the public adapter, gate either way.
            assert isinstance(reg.select_adapter(port, gate_open=False), _PublicMarker)
            assert isinstance(reg.select_adapter(port, gate_open=True), _PublicMarker)

    def test_discover_providers_empty_when_no_entry_points(self) -> None:
        assert discover_providers(entry_points=[]) == []


@pytest.mark.unit
class TestSupersedeWhenGateOpen:
    def _internal_ep(self, port: Port) -> _FakeEntryPoint:
        provider = SimplePortAdapterProvider(
            port=port,
            factory=lambda: "internal-adapter",
            tier=INTERNAL_TIER,
        )
        return _FakeEntryPoint("noop_sample", provider)

    def test_internal_selected_only_when_registered_and_gate_open(self) -> None:
        reg = _public_registry()
        install_entry_point_adapters(
            reg, entry_points=[self._internal_ep(Port.LOG_RETRIEVAL)]
        )
        # Gate closed -> public kept (additive invariant).
        assert isinstance(
            reg.select_adapter(Port.LOG_RETRIEVAL, gate_open=False), _PublicMarker
        )
        # Gate open -> discovered internal adapter supersedes.
        assert (
            reg.select_adapter(Port.LOG_RETRIEVAL, gate_open=True)
            == "internal-adapter"
        )
        assert reg.has_internal(Port.LOG_RETRIEVAL) is True
        # Other ports are untouched — still public under either gate state.
        for other in (Port.DIAGNOSTIC_BACKEND, Port.NL_QUERY, Port.FLEET_SQL):
            assert reg.has_internal(other) is False

    def test_public_tier_provider_registers_as_public(self) -> None:
        reg = PortRegistry()
        ep = _FakeEntryPoint(
            "public_sample",
            SimplePortAdapterProvider(
                port=Port.NL_QUERY,
                factory=lambda: "public-nlq",
                tier=PUBLIC_TIER,
            ),
        )
        install_entry_point_adapters(reg, entry_points=[ep])
        assert reg.select_adapter(Port.NL_QUERY, gate_open=False) == "public-nlq"
        assert reg.has_internal(Port.NL_QUERY) is False


@pytest.mark.unit
class TestProviderValidation:
    def test_invalid_provider_skipped_by_default(self) -> None:
        bad = _FakeEntryPoint("bad", object())  # missing port/tier/create
        assert discover_providers(entry_points=[bad]) == []

    def test_invalid_provider_raises_under_strict(self) -> None:
        bad = _FakeEntryPoint("bad", object())
        with pytest.raises(TypeError):
            discover_providers(entry_points=[bad], strict=True)

    def test_unknown_port_rejected(self) -> None:
        bad = _FakeEntryPoint(
            "bad_port",
            SimplePortAdapterProvider(
                port="not_a_port", factory=lambda: None, tier=INTERNAL_TIER
            ),
        )
        assert discover_providers(entry_points=[bad]) == []
        with pytest.raises(ValueError, match="not_a_port"):
            discover_providers(entry_points=[bad], strict=True)

    def test_bad_tier_rejected(self) -> None:
        bad = _FakeEntryPoint(
            "bad_tier",
            SimplePortAdapterProvider(
                port=Port.FLEET_SQL, factory=lambda: None, tier="privileged"
            ),
        )
        assert discover_providers(entry_points=[bad]) == []

    def test_failing_load_skipped_but_others_registered(self) -> None:
        good = _FakeEntryPoint(
            "good",
            SimplePortAdapterProvider(
                port=Port.FLEET_SQL, factory=lambda: "ok", tier=INTERNAL_TIER
            ),
        )
        broken = _FakeEntryPoint("broken", ImportError("boom"))
        providers = discover_providers(entry_points=[broken, good])
        assert len(providers) == 1
        reg = _public_registry()
        register_providers(reg, providers)
        assert reg.select_adapter(Port.FLEET_SQL, gate_open=True) == "ok"


@pytest.mark.unit
class TestContractConstants:
    def test_entry_point_group_name_is_stable(self) -> None:
        # The published contract name other packages register under.
        assert ENTRY_POINT_GROUP == "starboard.port_adapters"


@pytest.mark.unit
class TestGovernanceNoInternalImport:
    """The public trees must never import ``starboard_internal`` (import-linter)."""

    def _public_source_roots(self) -> list[Path]:
        # .../packages/starboard/tests/unit/ports/<this file>
        # parents: [0]=ports [1]=unit [2]=tests [3]=starboard [4]=packages
        packages = Path(__file__).resolve().parents[4]
        roots = [
            packages / "starboard" / "starboard",
            packages / "starboard-core" / "starboard_core",
            packages / "starboard-core" / "starboard_x",
            packages / "starboard-skills" / "starboard_skills",
        ]
        return [r for r in roots if r.exists()]

    def test_public_packages_do_not_import_starboard_internal(self) -> None:
        roots = self._public_source_roots()
        assert roots, "expected to locate the public package source trees"
        pattern = re.compile(
            r"^\s*(?:import\s+starboard_internal|from\s+starboard_internal)",
            re.MULTILINE,
        )
        offenders: list[str] = []
        for root in roots:
            for py in root.rglob("*.py"):
                if pattern.search(py.read_text(encoding="utf-8")):
                    offenders.append(str(py))
        assert offenders == [], f"public code imports starboard_internal: {offenders}"
