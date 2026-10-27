# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for database_backend validation on EnvConfig.

Tests cover:
- 'memory' and unset (default) both construct without error
- Removed backends (sqlite, postgres, lakebase, uc, databricks) raise a clear,
  actionable ValueError with a migration message
- The error message is raised at construction time (mode="before" validator),
  not buried in Pydantic's generic ValidationError prose
"""

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from starboard.infra.core.config import EnvConfig


class TestDatabaseBackendValid:
    def test_default_is_memory(self):
        cfg = EnvConfig()
        assert cfg.database_backend == "memory"

    def test_explicit_memory(self):
        cfg = EnvConfig(database_backend="memory")
        assert cfg.database_backend == "memory"

    def test_env_memory(self):
        with patch.dict(os.environ, {"DATABASE_BACKEND": "memory"}, clear=False):
            cfg = EnvConfig.from_env()
        assert cfg.database_backend == "memory"

    def test_unset_env_uses_default(self):
        env = {k: v for k, v in os.environ.items() if k != "DATABASE_BACKEND"}
        with patch.dict(os.environ, env, clear=True):
            cfg = EnvConfig.from_env()
        assert cfg.database_backend == "memory"


class TestDatabaseBackendRemovedValues:
    _REMOVED = ["sqlite", "postgres", "lakebase", "uc", "databricks"]
    _ACTIONABLE_FRAGMENT = "no longer supported"
    _MIGRATION_HINT = "JSON-file SessionManager"

    @pytest.mark.parametrize("backend", _REMOVED)
    def test_removed_backend_raises(self, backend: str):
        with pytest.raises(ValidationError) as exc_info:
            EnvConfig(database_backend=backend)
        message = str(exc_info.value)
        assert self._ACTIONABLE_FRAGMENT in message, (
            f"Expected actionable message for {backend!r}, got: {message}"
        )
        assert self._MIGRATION_HINT in message, (
            f"Expected migration hint for {backend!r}, got: {message}"
        )

    @pytest.mark.parametrize("backend", _REMOVED)
    def test_removed_backend_via_env_raises(self, backend: str):
        with (
            patch.dict(os.environ, {"DATABASE_BACKEND": backend}, clear=False),
            pytest.raises(ValidationError) as exc_info,
        ):
            EnvConfig.from_env()
        message = str(exc_info.value)
        assert self._ACTIONABLE_FRAGMENT in message

    @pytest.mark.parametrize("backend", ["SQLITE", "Postgres", "LAKEBASE"])
    def test_removed_backend_case_insensitive(self, backend: str):
        with pytest.raises(ValidationError) as exc_info:
            EnvConfig(database_backend=backend)
        assert self._ACTIONABLE_FRAGMENT in str(exc_info.value)
