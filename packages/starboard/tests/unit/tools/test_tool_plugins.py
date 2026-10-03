# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the ``starboard.mcp_tools`` per-domain plugin seam (Phase-3 B5).

Proves the layered-catalog properties without requiring any plugin package to be
installed (entry points are injected):

1. **Degrade cleanly** — with no plugin present, discovery returns an empty
   catalog and nothing breaks.
2. **Discoverable via entry point** — an injected plugin is discovered,
   registered by name, instantiable, and selectable by domain.
3. **Validation** — malformed entry points are skipped (or raised under
   ``strict``) and cannot corrupt the catalog.
4. **Duplicate-name safety** — a second plugin under an existing name is
   rejected (first wins) unless explicitly replaced / strict.
"""

from __future__ import annotations

import pytest
from starboard.tools.plugins import (
    ENTRY_POINT_GROUP,
    SimpleToolPlugin,
    ToolCatalog,
    ToolPlugin,
    discover_tool_plugins,
    install_entry_point_tools,
    register_tool_plugins,
)


class _FakeEntryPoint:
    """Minimal stand-in for ``importlib.metadata.EntryPoint``."""

    def __init__(self, name: str, obj: object) -> None:
        self.name = name
        self._obj = obj

    def load(self) -> object:
        if isinstance(self._obj, Exception):
            raise self._obj
        return self._obj


def _plugin(name: str, domain: str, tool: object = "tool") -> SimpleToolPlugin:
    return SimpleToolPlugin(name=name, domain=domain, factory=lambda: tool)


@pytest.mark.unit
class TestDegradeCleanlyWhenAbsent:
    def test_no_entry_points_yields_empty_catalog(self) -> None:
        catalog = install_entry_point_tools(entry_points=[])
        assert isinstance(catalog, ToolCatalog)
        assert len(catalog) == 0
        assert catalog.names() == []
        assert catalog.domains() == []
        assert catalog.by_domain("jobs") == []
        assert catalog.create_all() == {}

    def test_discover_returns_empty_list_when_absent(self) -> None:
        assert discover_tool_plugins(entry_points=[]) == []


@pytest.mark.unit
class TestDiscoverableViaEntryPoint:
    def test_injected_plugin_is_discovered_and_registered(self) -> None:
        ep = _FakeEntryPoint("sample_jobs_health", _plugin("sample_jobs_health", "jobs"))
        catalog = install_entry_point_tools(entry_points=[ep])
        assert "sample_jobs_health" in catalog
        assert catalog.has("sample_jobs_health")
        assert catalog.names() == ["sample_jobs_health"]
        assert catalog.get("sample_jobs_health").domain == "jobs"

    def test_tool_is_instantiable_on_demand(self) -> None:
        marker = object()
        ep = _FakeEntryPoint("t", _plugin("t", "warehouse", tool=marker))
        catalog = install_entry_point_tools(entry_points=[ep])
        assert catalog.create("t") is marker
        assert catalog.create_all() == {"t": marker}

    def test_select_by_domain(self) -> None:
        eps = [
            _FakeEntryPoint("a", _plugin("a", "jobs")),
            _FakeEntryPoint("b", _plugin("b", "jobs")),
            _FakeEntryPoint("c", _plugin("c", "warehouse")),
        ]
        catalog = install_entry_point_tools(entry_points=eps)
        assert sorted(p.name for p in catalog.by_domain("jobs")) == ["a", "b"]
        assert [p.name for p in catalog.by_domain("warehouse")] == ["c"]
        assert catalog.domains() == ["jobs", "warehouse"]

    def test_sample_plugin_object_satisfies_the_contract(self) -> None:
        # The shipped reference scaffold's provider object is a valid ToolPlugin.
        sample = pytest.importorskip("starboard_plugin_sample.plugin")
        assert isinstance(sample.sample_plugin, ToolPlugin)
        catalog = install_entry_point_tools(
            entry_points=[_FakeEntryPoint("sample_jobs_health", sample.sample_plugin)]
        )
        tool = catalog.create("sample_jobs_health")
        assert tool.describe()["domain"] == "jobs"


@pytest.mark.unit
class TestPluginValidation:
    def test_invalid_object_skipped_by_default(self) -> None:
        bad = _FakeEntryPoint("bad", object())  # missing name/domain/create
        assert discover_tool_plugins(entry_points=[bad]) == []

    def test_invalid_object_raises_under_strict(self) -> None:
        bad = _FakeEntryPoint("bad", object())
        with pytest.raises(TypeError):
            discover_tool_plugins(entry_points=[bad], strict=True)

    def test_empty_name_rejected(self) -> None:
        bad = _FakeEntryPoint("bad", _plugin("", "jobs"))
        assert discover_tool_plugins(entry_points=[bad]) == []
        with pytest.raises(ValueError, match="name"):
            discover_tool_plugins(entry_points=[bad], strict=True)

    def test_empty_domain_rejected(self) -> None:
        bad = _FakeEntryPoint("bad", _plugin("t", ""))
        with pytest.raises(ValueError, match="domain"):
            discover_tool_plugins(entry_points=[bad], strict=True)

    def test_failing_load_skipped_but_others_registered(self) -> None:
        broken = _FakeEntryPoint("broken", ImportError("boom"))
        good = _FakeEntryPoint("good", _plugin("good", "jobs"))
        catalog = install_entry_point_tools(entry_points=[broken, good])
        assert catalog.names() == ["good"]


@pytest.mark.unit
class TestDuplicateNameSafety:
    def test_duplicate_name_first_wins_non_strict(self) -> None:
        first = _plugin("dup", "jobs", tool="first")
        second = _plugin("dup", "warehouse", tool="second")
        catalog = register_tool_plugins(ToolCatalog(), [first, second])
        assert len(catalog) == 1
        assert catalog.create("dup") == "first"

    def test_duplicate_name_raises_under_strict(self) -> None:
        first = _plugin("dup", "jobs")
        second = _plugin("dup", "warehouse")
        with pytest.raises(ValueError, match="already registered"):
            register_tool_plugins(ToolCatalog(), [first, second], strict=True)

    def test_register_replace_overrides(self) -> None:
        catalog = ToolCatalog()
        catalog.register(_plugin("dup", "jobs", tool="first"))
        catalog.register(_plugin("dup", "warehouse", tool="second"), replace=True)
        assert catalog.create("dup") == "second"
        assert catalog.get("dup").domain == "warehouse"


@pytest.mark.unit
class TestContractConstants:
    def test_entry_point_group_name_is_stable(self) -> None:
        # The published contract name other packages register under.
        assert ENTRY_POINT_GROUP == "starboard.mcp_tools"
