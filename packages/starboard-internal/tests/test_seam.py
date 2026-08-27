# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the no-op sample internal adapter + entry-point seam (Phase-3 D-3.1).

Verifies the real ``starboard_internal`` provider (not an injected fake):

1. The module-level ``noop_sample_provider`` satisfies the public
   ``PortAdapterProvider`` contract and is an ``internal``-tier ``log_retrieval``
   provider.
2. Registering it via the public discovery helper makes it supersede the public
   adapter ONLY when the gate is open (§3.5 additive invariant).
3. The no-op adapter returns an empty bundle and leaks no internal identifiers.
4. When installed, the provider is discoverable through the real
   ``starboard.port_adapters`` entry-point group.
"""

from __future__ import annotations

from importlib import metadata
from pathlib import Path

import pytest
from starboard.ports.discovery import (
    ENTRY_POINT_GROUP,
    INTERNAL_TIER,
    PortAdapterProvider,
    discover_providers,
    register_providers,
)
from starboard.ports.registry import Port, PortRegistry
from starboard_core.ports.log_retrieval import LogQuery
from starboard_internal.adapters import (
    NoOpLogRetrievalAdapter,
    noop_sample_provider,
)


@pytest.mark.unit
class TestNoOpSampleProvider:
    def test_provider_satisfies_public_contract(self) -> None:
        assert isinstance(noop_sample_provider, PortAdapterProvider)
        assert noop_sample_provider.port == Port.LOG_RETRIEVAL
        assert noop_sample_provider.tier == INTERNAL_TIER

    def test_create_builds_the_noop_adapter(self) -> None:
        adapter = noop_sample_provider.create()
        assert isinstance(adapter, NoOpLogRetrievalAdapter)

    async def test_noop_adapter_returns_empty_bundle(self) -> None:
        adapter = NoOpLogRetrievalAdapter()
        bundle = await adapter.fetch(
            LogQuery(entity="cluster", entity_id="abc", paths=("/x",))
        )
        assert bundle.text == ""
        assert bundle.line_count == 0
        assert bundle.paths == ()
        assert bundle.source == "starboard-internal-noop"


@pytest.mark.unit
class TestSeamSelection:
    def test_registers_internal_and_supersedes_only_when_gate_open(self) -> None:
        reg = PortRegistry()
        reg.register_public(Port.LOG_RETRIEVAL, "public-log")
        register_providers(reg, [noop_sample_provider])

        # Gate closed -> public path preserved (additive invariant).
        assert reg.select_adapter(Port.LOG_RETRIEVAL, gate_open=False) == "public-log"
        # Gate open -> the sample internal adapter supersedes.
        assert isinstance(
            reg.select_adapter(Port.LOG_RETRIEVAL, gate_open=True),
            NoOpLogRetrievalAdapter,
        )


@pytest.mark.unit
class TestEntryPointDiscoverable:
    def test_provider_discoverable_via_entry_point_group(self) -> None:
        eps = metadata.entry_points(group=ENTRY_POINT_GROUP)
        if not eps:
            pytest.skip("starboard-internal not installed in this environment")
        providers = discover_providers(strict=True)
        assert any(p.port == Port.LOG_RETRIEVAL for p in providers)
        assert all(isinstance(p, PortAdapterProvider) for p in providers)


@pytest.mark.unit
class TestGovernanceNoInternalIdentifiers:
    def test_sample_adapter_source_has_no_internal_namespaces(self) -> None:
        src = (
            Path(__file__).resolve().parents[1]
            / "starboard_internal"
            / "adapters.py"
        ).read_text(encoding="utf-8")
        forbidden = (
            "centralized_system_tables",
            "fin_live_gold",
            "gtm_",
            "eng_",
            "logfood",
            "clickhouse",
            "hmr_stack_hash",
            "go/",
        )
        lowered = src.lower()
        hits = [tok for tok in forbidden if tok in lowered]
        assert hits == [], f"sample adapter names internal identifiers: {hits}"
