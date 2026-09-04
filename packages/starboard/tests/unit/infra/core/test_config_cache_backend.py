# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for cache_backend validation on EnvConfig.

Tests cover:
- 'memory' (default) and 'redis' are accepted
- Removed backends ('postgres') raise a clear, actionable ValueError
- The error is raised at construction time (mode="before" validator)
- Case-insensitive rejection for removed backends
"""

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from starboard.infra.core.config import EnvConfig


class TestCacheBackendValid:
    def test_default_is_memory(self):
        cfg = EnvConfig()
        assert cfg.cache_backend == "memory"

    def test_explicit_memory(self):
        cfg = EnvConfig(cache_backend="memory")
        assert cfg.cache_backend == "memory"

    def test_explicit_redis(self):
        # 'redis' is accepted at the Literal level; cross-field validation
        # (REDIS_URL required) is done separately in validate_config().
        cfg = EnvConfig(cache_backend="redis")
        assert cfg.cache_backend == "redis"

    def test_env_memory(self):
        with patch.dict(os.environ, {"CACHE_BACKEND": "memory"}, clear=False):
            cfg = EnvConfig.from_env()
        assert cfg.cache_backend == "memory"

    def test_unset_env_uses_default(self):
        env = {k: v for k, v in os.environ.items() if k != "CACHE_BACKEND"}
        with patch.dict(os.environ, env, clear=True):
            cfg = EnvConfig.from_env()
        assert cfg.cache_backend == "memory"


class TestCacheBackendRemovedValues:
    _REMOVED = ["postgres"]
    _ACTIONABLE_FRAGMENT = "no longer supported"
    _MIGRATION_HINT = "redis"

    @pytest.mark.parametrize("backend", _REMOVED)
    def test_removed_backend_raises(self, backend: str):
        with pytest.raises(ValidationError) as exc_info:
            EnvConfig(cache_backend=backend)
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
            patch.dict(os.environ, {"CACHE_BACKEND": backend}, clear=False),
            pytest.raises(ValidationError) as exc_info,
        ):
            EnvConfig.from_env()
        message = str(exc_info.value)
        assert self._ACTIONABLE_FRAGMENT in message

    @pytest.mark.parametrize("backend", ["POSTGRES", "Postgres", "postGRES"])
    def test_removed_backend_case_insensitive(self, backend: str):
        with pytest.raises(ValidationError) as exc_info:
            EnvConfig(cache_backend=backend)
        assert self._ACTIONABLE_FRAGMENT in str(exc_info.value)
