# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""W10: ``--profile`` must be authoritative over ambient DATABRICKS_HOST/TOKEN.

When ``build_config`` is called with a profile, ambient auth env vars must be
masked during SDK ``Config`` construction so the profile's credentials win.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any

import pytest
from starboard.infra.auth.resolver import (
    _AMBIENT_AUTH_ENV_VARS,
    WorkspaceTarget,
    _mask_ambient_auth,
    build_config,
)


class _CapturingConfig:
    """Records kwargs AND env snapshot at construction time."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.host = kwargs.get("host")
        self.token = kwargs.get("token")
        self.profile = kwargs.get("profile")
        self.auth_type = kwargs.get("auth_type", "pat")
        # Capture the ambient env at the moment Config() is called.
        self.env_snapshot = dict(os.environ)


class TestProfileMasksAmbientEnv:
    """build_config must clear ambient auth env vars when profile is set."""

    @pytest.fixture(autouse=True)
    def _inject_ambient_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABRICKS_HOST", "https://ambient-host.cloud.databricks.com")
        monkeypatch.setenv("DATABRICKS_TOKEN", "ambient-secret-token")

    def test_ambient_host_absent_during_config_construction(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DATABRICKS_HOST must not be visible when Config() is called for a profile."""
        import starboard.infra.auth.resolver as resolver_mod

        captured: list[_CapturingConfig] = []

        def capturing_config(**kw: Any) -> _CapturingConfig:
            cfg = _CapturingConfig(**kw)
            captured.append(cfg)
            return cfg

        monkeypatch.setattr(resolver_mod, "Config", capturing_config)

        target = WorkspaceTarget(profile="lm-arena")
        build_config(target)

        assert captured, "Config was never called"
        snap = captured[0].env_snapshot
        assert "DATABRICKS_HOST" not in snap, (
            "DATABRICKS_HOST must be masked when profile is active"
        )
        assert "DATABRICKS_TOKEN" not in snap, (
            "DATABRICKS_TOKEN must be masked when profile is active"
        )

    def test_ambient_env_restored_after_config_construction(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Env vars must be restored after build_config returns."""
        import starboard.infra.auth.resolver as resolver_mod

        monkeypatch.setattr(resolver_mod, "Config", lambda **kw: SimpleNamespace(**kw))

        target = WorkspaceTarget(profile="lm-arena")
        build_config(target)

        assert os.environ.get("DATABRICKS_HOST") == "https://ambient-host.cloud.databricks.com"
        assert os.environ.get("DATABRICKS_TOKEN") == "ambient-secret-token"

    def test_no_masking_without_profile(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When no profile is set the env is NOT masked (normal inline path)."""
        import starboard.infra.auth.resolver as resolver_mod

        captured: list[_CapturingConfig] = []

        def capturing_config(**kw: Any) -> _CapturingConfig:
            cfg = _CapturingConfig(**kw)
            captured.append(cfg)
            return cfg

        monkeypatch.setattr(resolver_mod, "Config", capturing_config)

        target = WorkspaceTarget(
            host="https://ambient-host.cloud.databricks.com",
            token="ambient-secret-token",
        )
        build_config(target)

        assert captured
        snap = captured[0].env_snapshot
        # Env vars must still be present (not masked) on the non-profile path.
        assert snap.get("DATABRICKS_HOST") == "https://ambient-host.cloud.databricks.com"


class TestMaskAmbientAuthContextManager:
    def test_vars_restored_on_normal_exit(self) -> None:
        prev = os.environ.get("DATABRICKS_HOST")
        try:
            os.environ["DATABRICKS_HOST"] = "https://test.cloud.databricks.com"
            with _mask_ambient_auth():
                assert "DATABRICKS_HOST" not in os.environ
            assert os.environ.get("DATABRICKS_HOST") == "https://test.cloud.databricks.com"
        finally:
            if prev is None:
                os.environ.pop("DATABRICKS_HOST", None)
            else:
                os.environ["DATABRICKS_HOST"] = prev

    def test_vars_restored_on_exception(self) -> None:
        prev = os.environ.get("DATABRICKS_TOKEN")
        try:
            os.environ["DATABRICKS_TOKEN"] = "tok-xyz"
            with pytest.raises(ValueError), _mask_ambient_auth():
                raise ValueError("simulated failure")
            assert os.environ.get("DATABRICKS_TOKEN") == "tok-xyz"
        finally:
            if prev is None:
                os.environ.pop("DATABRICKS_TOKEN", None)
            else:
                os.environ["DATABRICKS_TOKEN"] = prev

    def test_all_ambient_vars_masked(self) -> None:
        prev = {k: os.environ.pop(k, None) for k in _AMBIENT_AUTH_ENV_VARS}
        try:
            for k in _AMBIENT_AUTH_ENV_VARS:
                os.environ[k] = f"value-{k}"
            with _mask_ambient_auth():
                for k in _AMBIENT_AUTH_ENV_VARS:
                    assert k not in os.environ, f"{k} should be masked"
            for k in _AMBIENT_AUTH_ENV_VARS:
                assert os.environ.get(k) == f"value-{k}", f"{k} should be restored"
        finally:
            for k, v in prev.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
