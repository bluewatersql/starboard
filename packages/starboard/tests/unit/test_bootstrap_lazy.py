# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests that starboard.bootstrap defers store-driver imports until first access.

Spec: changes/2026_26_27_agents/plans/PHASE_0.md §4 (DOC-1).

Three acceptance criteria:
  (a) ``import starboard.bootstrap`` pulls none of the optional store drivers
      (aiosqlite / sqlite_vec / asyncpg / redis / pgvector) into sys.modules.
  (b) ``bootstrap.SQLiteStateStore`` still resolves to the real class on explicit
      access — back-compat for the sqlite backend is preserved.
  (c) When aiosqlite is absent (monkeypatched out), importing bootstrap succeeds;
      accessing ``SQLiteStateStore`` raises an actionable error with a hint to
      ``pip install starboard[sqlite]``.
"""

from __future__ import annotations

import importlib
import sys
from types import ModuleType
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Optional store-driver module prefixes that must NOT be touched at import time
# ---------------------------------------------------------------------------
_STORE_PREFIXES = ("aiosqlite", "sqlite_vec", "asyncpg", "redis", "pgvector")


def _loaded_store_modules() -> set[str]:
    """Return names of store-driver modules currently in sys.modules."""
    return {
        m
        for m in sys.modules
        if any(m == prefix or m.startswith(prefix + ".") for prefix in _STORE_PREFIXES)
    }


def _evict_bootstrap() -> list[str]:
    """Remove bootstrap and sqlite adapter modules from sys.modules; return evicted keys."""
    to_evict = [
        k
        for k in sys.modules
        if k in ("starboard.bootstrap",)
        or k.startswith("starboard.adapters.state.sqlite")
    ]
    for key in to_evict:
        sys.modules.pop(key, None)
    return to_evict


def _fresh_bootstrap() -> ModuleType:
    """Evict and re-import starboard.bootstrap so each test gets a clean load."""
    _evict_bootstrap()
    return importlib.import_module("starboard.bootstrap")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBootstrapLazyStoreImport:
    """bootstrap.py must not touch store drivers at import time."""

    def test_no_store_modules_on_import(self) -> None:
        """(a) Importing starboard.bootstrap loads none of the optional store drivers."""
        before = _loaded_store_modules()

        _fresh_bootstrap()

        after = _loaded_store_modules()
        newly_loaded = after - before
        assert not newly_loaded, (
            f"bootstrap import pulled optional store module(s) into sys.modules: "
            f"{sorted(newly_loaded)!r}"
        )

    def test_sqlite_state_store_resolves_on_access(self) -> None:
        """(b) bootstrap.SQLiteStateStore resolves to the real class on explicit access."""
        bootstrap = _fresh_bootstrap()

        cls = bootstrap.SQLiteStateStore

        assert cls.__name__ == "SQLiteStateStore"
        assert hasattr(cls, "connect"), "expected async connect() method"
        assert hasattr(cls, "close"), "expected async close() method"

    def test_sqlite_state_store_absent_from_all(self) -> None:
        """SQLiteStateStore must NOT be in __all__ so ``import *`` stays store-safe.

        It resolves lazily via __getattr__; listing it in __all__ would make
        ``from starboard.bootstrap import *`` force the eager driver import.
        """
        bootstrap = _fresh_bootstrap()
        assert "SQLiteStateStore" not in bootstrap.__all__

    def test_star_import_touches_no_store_modules(self) -> None:
        """Resolving every __all__ name (as ``import *`` does) loads no store driver."""
        bootstrap = _fresh_bootstrap()
        before = _loaded_store_modules()

        for name in bootstrap.__all__:
            getattr(bootstrap, name)

        newly_loaded = _loaded_store_modules() - before
        assert not newly_loaded, (
            f"star-import of bootstrap pulled optional store module(s): "
            f"{sorted(newly_loaded)!r}"
        )

    def test_missing_aiosqlite_import_succeeds(self) -> None:
        """(c) bootstrap imports cleanly even when aiosqlite is absent."""
        _evict_bootstrap()
        saved_aiosqlite = sys.modules.pop("aiosqlite", ...)

        try:
            # Block aiosqlite via the sys.modules sentinel (None → ImportError)
            with patch.dict(sys.modules, {"aiosqlite": None}):
                # The import itself must succeed without touching aiosqlite
                bootstrap = importlib.import_module("starboard.bootstrap")
                assert bootstrap is not None
        finally:
            # Restore aiosqlite if it was installed
            if saved_aiosqlite is not ...:
                sys.modules["aiosqlite"] = saved_aiosqlite  # type: ignore[assignment]
            sys.modules.pop("starboard.bootstrap", None)
            sys.modules.pop("starboard.adapters.state.sqlite.state_store", None)

    def test_missing_aiosqlite_sqlite_store_access_raises_actionable_error(self) -> None:
        """(c) Accessing SQLiteStateStore without aiosqlite raises a helpful error."""
        _evict_bootstrap()
        saved_aiosqlite = sys.modules.pop("aiosqlite", ...)
        saved_state_store = sys.modules.pop(
            "starboard.adapters.state.sqlite.state_store", ...
        )

        try:
            with patch.dict(sys.modules, {"aiosqlite": None}):
                bootstrap = importlib.import_module("starboard.bootstrap")

                with pytest.raises((ImportError, ModuleNotFoundError)) as exc_info:
                    _ = bootstrap.SQLiteStateStore

                msg = str(exc_info.value).lower()
                # Must mention sqlite (the install hint) OR aiosqlite (the missing dep)
                assert "sqlite" in msg or "aiosqlite" in msg, (
                    f"Expected an actionable error mentioning 'sqlite' or 'aiosqlite', got: "
                    f"{exc_info.value!r}"
                )
        finally:
            if saved_aiosqlite is not ...:
                sys.modules["aiosqlite"] = saved_aiosqlite  # type: ignore[assignment]
            if saved_state_store is not ...:
                sys.modules["starboard.adapters.state.sqlite.state_store"] = saved_state_store  # type: ignore[assignment]
            sys.modules.pop("starboard.bootstrap", None)
            sys.modules.pop("starboard.adapters.state.sqlite.state_store", None)
