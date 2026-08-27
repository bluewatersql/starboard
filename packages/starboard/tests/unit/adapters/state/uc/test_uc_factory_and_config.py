# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Factory wiring, databricks->lakebase rename, and container dispatch (C2)."""

from __future__ import annotations

import sys
import warnings

import pytest
import starboard.infra.auth.resolver as resolver
from starboard.adapters.state.uc import (
    UCFeedbackRepository,
    UCMemoryStore,
    UCStateStore,
    UCUserStore,
)
from starboard.infra.core.config import EnvConfig
from starboard.infra.core.state_factory import (
    create_memory_store,
    create_state_store,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("DATABASE_BACKEND", "DATABASE_URL", "STARBOARD_WAREHOUSE_ID"):
        monkeypatch.delenv(var, raising=False)


def _cfg(**overrides) -> EnvConfig:
    return EnvConfig(_env_file=None, **overrides)


class TestUCFactoryWiring:
    def test_state_backend_uc_builds_uc_state_store_via_resolver(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"resolve": 0}

        def _fake_resolve(*_a, **_k):
            calls["resolve"] += 1
            return object()

        monkeypatch.setattr(resolver, "resolve_workspace_client", _fake_resolve)
        store = create_state_store(_cfg(database_backend="uc"))
        assert isinstance(store, UCStateStore)
        # Reuses the resolver's client rather than a bare WorkspaceClient.
        assert calls["resolve"] == 1

    def test_memory_backend_uc_builds_uc_memory_store(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(resolver, "resolve_workspace_client", lambda *a, **k: object())
        store = create_memory_store(_cfg(database_backend="uc"))
        assert isinstance(store, UCMemoryStore)

    def test_uc_path_imports_no_asyncpg_or_aiosqlite(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for driver in ("aiosqlite", "asyncpg"):
            monkeypatch.setitem(sys.modules, driver, None)
        monkeypatch.setattr(resolver, "resolve_workspace_client", lambda *a, **k: object())
        # Neither path may pull a SQL driver.
        create_state_store(_cfg(database_backend="uc"))
        create_memory_store(_cfg(database_backend="uc"))

    def test_warehouse_id_falls_back_to_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = {}

        def _fake_resolve(*_a, **_k):
            return object()

        monkeypatch.setattr(resolver, "resolve_workspace_client", _fake_resolve)
        store = create_state_store(
            _cfg(database_backend="uc", databricks_warehouse_id="wh-123")
        )
        # Adapter picked up the warehouse id from config.
        assert store._adapter.config.warehouse_id == "wh-123"
        assert captured == {}


class TestDefaultNeverAutoSelectsUC:
    def test_default_backend_is_memory(self) -> None:
        assert _cfg().database_backend == "memory"

    def test_default_dev_state_store_is_not_uc(self) -> None:
        store = create_state_store(_cfg(environment="dev"))
        assert not isinstance(store, UCStateStore)


class TestDatabricksLakebaseRename:
    def test_databricks_maps_to_lakebase_with_warning(self) -> None:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            cfg = _cfg(database_backend="databricks")
        assert cfg.database_backend == "lakebase"
        assert any(issubclass(w.category, DeprecationWarning) for w in caught)

    def test_lakebase_value_accepted_directly(self) -> None:
        assert _cfg(database_backend="lakebase").database_backend == "lakebase"

    def test_lakebase_state_store_requires_asyncpg(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The renamed backend still lazy-guards its driver (actionable error).
        monkeypatch.setitem(sys.modules, "asyncpg", None)
        cfg = _cfg(
            environment="production",
            database_backend="databricks",  # deprecated alias -> lakebase
            database_url="postgresql://x",
        )
        with pytest.raises(RuntimeError) as exc:
            create_state_store(cfg)
        assert "starboard[postgres]" in str(exc.value)


class TestContainerCapabilityDispatch:
    def test_uc_state_store_supplies_own_user_and_feedback_stores(self) -> None:
        from starboard.infra.core.container import Container
        from tests.unit.adapters.state.uc.conftest import FakeUCAdapter

        container = Container(_cfg(database_backend="uc"))
        container._state_store = UCStateStore(FakeUCAdapter())

        # Capability dispatch: no isinstance-ladder fallthrough to Postgres.
        assert isinstance(container.user_store, UCUserStore)
        assert isinstance(container.feedback_repo, UCFeedbackRepository)
