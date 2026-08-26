# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the zero-store default (A3).

Verifies that a default install carries no external-store drivers:
- default backends are memory / inmemory
- the default dev state store is InMemory and needs no driver import
- selecting a driver-backed backend without its extra raises an actionable error
- default config validates without DATABASE_URL / REDIS_URL
- the store drivers are not declared as hard [project.dependencies]
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest
from starboard.adapters.state.inmemory import InMemoryCacheStore, InMemoryStateStore
from starboard.infra.core.config import EnvConfig
from starboard.infra.core.state_factory import (
    create_cache_store,
    create_state_store,
)

PYPROJECT = Path(__file__).parents[4] / "pyproject.toml"

STORE_DRIVERS = ("redis", "asyncpg", "pgvector", "aiosqlite", "sqlite-vec")


@pytest.fixture(autouse=True)
def _clean_store_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear store/backend env vars so field *defaults* are observable.

    The CI/dev shell may export DATABASE_BACKEND / DATABRICKS_* etc.; pydantic
    BaseSettings reads those even with ``_env_file=None``.
    """
    for var in (
        "DATABASE_BACKEND",
        "VECTOR_BACKEND",
        "CACHE_BACKEND",
        "DATABASE_URL",
        "REDIS_URL",
    ):
        monkeypatch.delenv(var, raising=False)


def _default_config(**overrides) -> EnvConfig:
    # Build without reading the .env file so the test is deterministic.
    return EnvConfig(_env_file=None, **overrides)


class TestZeroStoreDefaults:
    def test_default_backends_are_store_free(self) -> None:
        cfg = _default_config()
        assert cfg.database_backend == "memory"
        # Phase 2 C1 (D-2.3): the analytics agent builds context from on-disk
        # reference files by default — no vector store, no embeddings.
        assert cfg.vector_backend == "none"
        assert cfg.cache_backend == "memory"

    def test_default_dev_state_store_is_inmemory(self) -> None:
        cfg = _default_config(environment="dev")
        store = create_state_store(cfg)
        assert isinstance(store, InMemoryStateStore)

    def test_default_cache_store_is_inmemory(self) -> None:
        cfg = _default_config()
        store = create_cache_store(cfg)
        assert isinstance(store, InMemoryCacheStore)

    def test_default_dev_state_store_needs_no_driver(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Simulate a no-extras install: none of the store drivers importable.
        for driver in ("aiosqlite", "asyncpg", "pgvector", "redis"):
            monkeypatch.setitem(sys.modules, driver, None)
        cfg = _default_config(environment="dev")
        # Must not raise: the default path imports no driver.
        store = create_state_store(cfg)
        assert isinstance(store, InMemoryStateStore)


class TestMissingExtraRaises:
    def test_sqlite_without_driver_raises_actionable_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "aiosqlite", None)
        cfg = _default_config(environment="dev", database_backend="sqlite")
        with pytest.raises(RuntimeError) as exc:
            create_state_store(cfg)
        msg = str(exc.value)
        assert "sqlite" in msg
        assert "pip install" in msg
        assert "starboard[sqlite]" in msg

    def test_redis_cache_without_driver_raises_actionable_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "redis", None)
        cfg = _default_config(redis_url="redis://localhost:6379/0")
        with pytest.raises(RuntimeError) as exc:
            create_cache_store(cfg)
        msg = str(exc.value)
        assert "pip install" in msg
        assert "starboard[redis]" in msg


class TestUCNotImplemented:
    def test_uc_backend_raises_phase2_error(self) -> None:
        cfg = _default_config(environment="dev", database_backend="uc")
        with pytest.raises(RuntimeError) as exc:
            create_state_store(cfg)
        assert "Phase 2" in str(exc.value)


class TestValidationNoStoreUrls:
    def test_default_validates_without_database_or_redis_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Provide auth + llm so validation focuses on store URLs.
        monkeypatch.setenv("DATABRICKS_HOST", "https://x.cloud.databricks.com")
        monkeypatch.setenv("DATABRICKS_TOKEN", "dapitoken")
        cfg = _default_config(
            databricks_host="https://x.cloud.databricks.com",
            databricks_token="dapitoken",
            llm_api_key="sk-abcdefghijklmnop",
        )
        assert cfg.database_url is None
        assert cfg.redis_url is None
        # Should not raise about DATABASE_URL / REDIS_URL.
        cfg.validate_config()


class TestPackagingExtras:
    def test_store_drivers_not_in_project_dependencies(self) -> None:
        data = tomllib.loads(PYPROJECT.read_text())
        deps = data["project"]["dependencies"]
        dep_names = {_dep_name(d) for d in deps}
        for driver in STORE_DRIVERS:
            assert driver not in dep_names, (
                f"{driver} must not be a hard dependency (move to an extra)"
            )

    def test_store_extras_declared(self) -> None:
        data = tomllib.loads(PYPROJECT.read_text())
        extras = data["project"]["optional-dependencies"]
        for extra in ("sqlite", "postgres", "redis", "memory", "vectorsearch", "all-stores"):
            assert extra in extras, f"missing extra: {extra}"

    def test_dev_or_all_pulls_in_all_stores(self) -> None:
        # CI/make setup must keep drivers: an aggregate extra references all-stores.
        data = tomllib.loads(PYPROJECT.read_text())
        extras = data["project"]["optional-dependencies"]
        aggregated = " ".join(extras.get("dev", []) + extras.get("all", []))
        assert "all-stores" in aggregated


def _dep_name(spec: str) -> str:
    """Extract the distribution name from a PEP 508 dependency string."""
    for sep in ("[", ">", "<", "=", "!", "~", ";", " "):
        spec = spec.split(sep, 1)[0]
    return spec.strip().lower()
