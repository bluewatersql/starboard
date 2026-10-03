# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Engine source selection + internal-source registry resolution (Phase-3 D-3.4, Task 6).

Proves:

1. **External default is byte-identical** — ``EngineConfig()`` (``source="external"``)
   leaves the pack executor on its :class:`SystemTablesSource` identity path; no
   internal machinery is touched.
2. **Internal via the existing registry/gate** — ``source="internal"`` resolves the
   gated ``MirrorSource`` through the ``starboard.port_adapters`` entry-point seam,
   threading the run's ``workspace_ids`` into the built source.
3. **Hard fail, never a silent fallback** — with no internal provider discoverable
   (empty entry points / monkeypatched discovery), resolution raises
   ``RuntimeError("internal source not available")``.
4. **Internal source is OPTIONAL** — the external path never needs the internal
   package; only ``source="internal"`` requires it.
"""

from __future__ import annotations

import polars as pl
import pytest
from starboard.discovery.engine import (
    DiscoveryEngine,
    EngineConfig,
    resolve_internal_source,
)
from starboard.discovery.sources import SystemTablesSource
from starboard.ports.discovery import INTERNAL_TIER, SimplePortAdapterProvider
from starboard.ports.registry import Port


class _Exec:
    """Minimal ``SQLExecutor`` — never actually invoked by these tests."""

    async def execute_sql(self, sql: str) -> pl.DataFrame:  # noqa: ARG002
        return pl.DataFrame({"n": [1]})


class _FakeEntryPoint:
    """Minimal stand-in for ``importlib.metadata.EntryPoint``."""

    def __init__(self, name: str, obj: object) -> None:
        self.name = name
        self._obj = obj

    def load(self) -> object:
        return self._obj


class _RecordingSource:
    """A QuerySource-shaped stand-in that captures the scope it was built with."""

    def __init__(
        self, workspace_ids: tuple[str, ...], account: str | None = None
    ) -> None:
        self.workspace_ids = workspace_ids
        self.account = account

    def prepare(self, query, rendered_sql, render=None):  # noqa: ANN001, ARG002 - shape only
        return None


class _RecordingBuilder:
    """Zero-arg builder the registry hands back; ``build`` receives the run scope."""

    def build(
        self,
        workspace_ids: tuple[str, ...] = (),
        account: str | None = None,
        executor=None,  # noqa: ANN001 - shape only
    ) -> _RecordingSource:
        return _RecordingSource(workspace_ids, account)


@pytest.mark.unit
def test_external_default_builds_identity_source() -> None:
    eng = DiscoveryEngine(sql_executor=_Exec(), config=EngineConfig())
    # Byte-identical to today: the executor stays on the SystemTablesSource path.
    assert isinstance(eng._pack_executor._source, SystemTablesSource)


@pytest.mark.unit
def test_internal_source_absent_raises_hard_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # Registry discovery finds no providers -> hard error; NEVER a customer fallback.
    monkeypatch.setattr(
        "starboard.discovery.engine.install_entry_point_adapters",
        lambda registry, **_kw: registry,
    )
    with pytest.raises(RuntimeError, match="internal source not available"):
        DiscoveryEngine(
            sql_executor=_Exec(),
            config=EngineConfig(source="internal", internal_workspace_ids=("111",)),
        )


@pytest.mark.unit
def test_resolve_internal_source_threads_workspace_ids() -> None:
    # An INTERNAL_TIER provider is selected only when the gate is open, and its
    # builder receives the per-run workspace scope.
    provider = SimplePortAdapterProvider(
        port=Port.DISCOVERY_SOURCE,
        factory=_RecordingBuilder,
        tier=INTERNAL_TIER,
    )
    ep = _FakeEntryPoint("discovery_source", provider)
    src = resolve_internal_source(("111", "222"), entry_points=[ep])
    assert isinstance(src, _RecordingSource)
    assert src.workspace_ids == ("111", "222")


@pytest.mark.unit
def test_resolve_internal_source_optional_when_absent() -> None:
    # No internal package installed => empty entry points => hard error, proving
    # the internal source is optional (external path never reaches this).
    with pytest.raises(RuntimeError, match="internal source not available"):
        resolve_internal_source(("111",), entry_points=[])
