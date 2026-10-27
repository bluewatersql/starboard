# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the unified auth resolver (A1).

Verifies auth-by-subtraction: host/token are optional, precedence follows the
documented order, only set fields reach the SDK Config, secrets are never
exposed by describe_auth, and existing host+token / env paths still resolve.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from starboard.infra.auth import resolver as resolver_mod
from starboard.infra.auth.resolver import (
    WorkspaceTarget,
    apply_cli_target,
    build_config,
    describe_auth,
    resolve_workspace_client,
)


class _FakeConfig:
    """Captures the kwargs the resolver passes to databricks Config."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.host = kwargs.get("host")
        self.token = kwargs.get("token")
        self.profile = kwargs.get("profile")
        self.auth_type = kwargs.get("auth_type", "pat")


@pytest.fixture(autouse=True)
def _clear_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "STARBOARD_WORKSPACE",
        "DATABRICKS_CONFIG_PROFILE",
        "DATABRICKS_CLIENT_ID",
        "DATABRICKS_CLIENT_SECRET",
        "DATABRICKS_AUTH_TYPE",
    ):
        monkeypatch.delenv(var, raising=False)


class TestResolvePrecedence:
    def test_explicit_profile_wins_over_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("STARBOARD_WORKSPACE", "env-ws")
        monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "cfg-profile")
        target = WorkspaceTarget.resolve(profile="explicit")
        assert target.profile == "explicit"

    def test_starboard_workspace_beats_databricks_config_profile(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("STARBOARD_WORKSPACE", "env-ws")
        monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "cfg-profile")
        target = WorkspaceTarget.resolve()
        assert target.profile == "env-ws"

    def test_databricks_config_profile_used_when_no_alias(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "cfg-profile")
        target = WorkspaceTarget.resolve()
        assert target.profile == "cfg-profile"

    def test_inline_host_token_populated(self) -> None:
        target = WorkspaceTarget.resolve(host="https://h", token="tok")
        assert target.host == "https://h"
        assert target.token == "tok"

    def test_cfg_supplies_host_token_when_not_inline(self) -> None:
        cfg = SimpleNamespace(
            databricks_host="https://from-cfg",
            databricks_token="cfg-tok",
            databricks_warehouse_id=None,
        )
        target = WorkspaceTarget.resolve(cfg=cfg)
        assert target.host == "https://from-cfg"
        assert target.token == "cfg-tok"

    def test_no_inputs_yields_empty_target(self) -> None:
        target = WorkspaceTarget.resolve()
        assert target.host is None
        assert target.token is None
        assert target.profile is None


class TestExplicitHostVsAmbientProfile:
    """F8a: an ambient profile must never pair its credentials with another host."""

    @pytest.mark.parametrize(
        "var", ["STARBOARD_WORKSPACE", "DATABRICKS_CONFIG_PROFILE"]
    )
    def test_explicit_host_ignores_ambient_profile(
        self, monkeypatch: pytest.MonkeyPatch, var: str
    ) -> None:
        monkeypatch.setenv(var, "default-profile")
        target = WorkspaceTarget.resolve(host="https://customer.cloud.databricks.com")
        assert target.profile is None
        assert target.host == "https://customer.cloud.databricks.com"
        # build_config must not drop the host in favor of a profile, and the SDK
        # must not re-read the ambient profile env var while the Config is built
        # (it would load that profile's token and pair it with this host).
        kwargs, env_seen = build_config_capture(target)
        assert kwargs.get("host") == target.host
        assert "profile" not in kwargs
        assert env_seen is None
        if var == "DATABRICKS_CONFIG_PROFILE":
            # The env var is restored after construction.
            assert os.environ.get(var) == "default-profile"

    def test_cfg_host_without_profile_env_builds_unmasked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        kwargs, env_seen = build_config_capture(WorkspaceTarget(host="https://h"))
        assert kwargs == {"host": "https://h"}
        assert env_seen is None

    def test_explicit_profile_and_host_keeps_profile(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "default-profile")
        target = WorkspaceTarget.resolve(
            profile="customer", host="https://customer.cloud.databricks.com"
        )
        assert target.profile == "customer"

    def test_no_host_uses_ambient_profile(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "default-profile")
        assert WorkspaceTarget.resolve().profile == "default-profile"

    def test_cfg_host_alone_keeps_ambient_profile(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A cfg-derived host (e.g. DATABRICKS_HOST env) is not an explicit host
        # argument: precedence is unchanged.
        monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "default-profile")
        cfg = SimpleNamespace(
            databricks_host="https://from-env",
            databricks_token=None,
            databricks_warehouse_id=None,
        )
        target = WorkspaceTarget.resolve(cfg=cfg)
        assert target.profile == "default-profile"
        assert target.host == "https://from-env"


def build_config_capture(target: WorkspaceTarget) -> tuple[dict[str, Any], str | None]:
    """Return the SDK ``Config`` kwargs and the ``DATABRICKS_CONFIG_PROFILE`` env
    value visible while ``build_config`` constructs it."""
    captured: dict[str, Any] = {}
    env_seen: list[str | None] = []

    def _capture(**kwargs: Any) -> _FakeConfig:
        captured.update(kwargs)
        env_seen.append(os.environ.get("DATABRICKS_CONFIG_PROFILE"))
        return _FakeConfig(**kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(resolver_mod, "Config", _capture)
        build_config(target)
    return captured, env_seen[0]


class TestBuildConfig:
    def test_omits_unset_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(resolver_mod, "Config", _FakeConfig)
        target = WorkspaceTarget(host="https://h", token="tok")
        cfg = build_config(target)
        assert cfg.kwargs == {"host": "https://h", "token": "tok"}
        # No empty host/token/profile injected.
        assert "profile" not in cfg.kwargs
        assert "client_id" not in cfg.kwargs

    def test_profile_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(resolver_mod, "Config", _FakeConfig)
        cfg = build_config(WorkspaceTarget(profile="prod"))
        assert cfg.kwargs == {"profile": "prod"}

    def test_empty_target_passes_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(resolver_mod, "Config", _FakeConfig)
        cfg = build_config(WorkspaceTarget())
        assert cfg.kwargs == {}

    def test_profile_drops_host_token_and_client_creds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """M1: --profile is the source of truth; conflicting host/token and
        ambient client creds must be dropped so the SDK does not raise
        'more than one authorization method configured'."""
        monkeypatch.setattr(resolver_mod, "Config", _FakeConfig)
        target = WorkspaceTarget(
            profile="prod",
            host="https://env-host",
            token="env-tok",
            client_id="cid",
            client_secret="secret",
        )
        cfg = build_config(target)
        assert cfg.kwargs == {"profile": "prod"}

    def test_explicit_token_beats_ambient_client_creds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """M1: an explicit PAT wins over ambient env client_id/secret."""
        monkeypatch.setattr(resolver_mod, "Config", _FakeConfig)
        target = WorkspaceTarget(
            host="https://h", token="tok", client_id="cid", client_secret="sec"
        )
        cfg = build_config(target)
        assert cfg.kwargs == {"host": "https://h", "token": "tok"}

    def test_m2m_host_plus_client_creds_kept(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OAuth M2M (host + client_id/secret, no token/profile) stays intact."""
        monkeypatch.setattr(resolver_mod, "Config", _FakeConfig)
        target = WorkspaceTarget(
            host="https://h", client_id="cid", client_secret="sec"
        )
        cfg = build_config(target)
        assert cfg.kwargs == {
            "host": "https://h",
            "client_id": "cid",
            "client_secret": "sec",
        }


class TestResolveWorkspaceClient:
    def test_host_token_backcompat(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def fake_wc(*, config: Any) -> Any:
            captured["config"] = config
            return SimpleNamespace(config=config)

        monkeypatch.setattr(resolver_mod, "Config", _FakeConfig)
        monkeypatch.setattr(resolver_mod, "WorkspaceClient", fake_wc)

        client = resolve_workspace_client(
            WorkspaceTarget.resolve(host="https://h", token="tok")
        )
        assert client is not None
        assert captured["config"].kwargs == {"host": "https://h", "token": "tok"}

    def test_ambient_no_inputs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def fake_wc(*, config: Any) -> Any:
            captured["config"] = config
            return SimpleNamespace(config=config)

        monkeypatch.setattr(resolver_mod, "Config", _FakeConfig)
        monkeypatch.setattr(resolver_mod, "WorkspaceClient", fake_wc)

        client = resolve_workspace_client()
        assert client is not None
        # Ambient: nothing forced onto the SDK chain.
        assert captured["config"].kwargs == {}


class TestDescribeAuth:
    def test_redacts_secrets(self) -> None:
        fake = SimpleNamespace(
            config=SimpleNamespace(
                host="https://h",
                auth_type="pat",
                profile="prod",
                token="super-secret",  # must not leak
            ),
            current_user=SimpleNamespace(
                me=lambda: SimpleNamespace(user_name="me@x.com")
            ),
        )
        info = describe_auth(fake)
        assert info == {
            "host": "https://h",
            "auth_type": "pat",
            "profile": "prod",
            "user": "me@x.com",
        }
        assert "token" not in info
        assert "super-secret" not in str(info)


class TestConfigValidation:
    """Config validation no longer hard-requires host+token (A1)."""

    def _cfg(self, **overrides):
        from starboard.infra.core.config import EnvConfig

        return EnvConfig(_env_file=None, llm_api_key="sk-abcdefghij", **overrides)

    def test_profile_only_resolves(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in ("DATABRICKS_HOST", "DATABRICKS_TOKEN"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "prod")
        cfg = self._cfg()
        # No host/token but a profile is available -> must not raise.
        cfg.validate_config()

    def test_errors_when_nothing_resolves(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for var in (
            "DATABRICKS_HOST",
            "DATABRICKS_TOKEN",
            "DATABRICKS_CONFIG_PROFILE",
            "STARBOARD_WORKSPACE",
            "DATABRICKS_CLIENT_ID",
            "DATABRICKS_CLIENT_SECRET",
            "DATABRICKS_CONFIG_FILE",
            "DATABRICKS_RUNTIME_VERSION",
        ):
            monkeypatch.delenv(var, raising=False)
        # Point config-file discovery at a non-existent path.
        monkeypatch.setenv("HOME", "/nonexistent-home-for-test")
        monkeypatch.setattr(
            "pathlib.Path.exists", lambda self: False
        )
        cfg = self._cfg()
        with pytest.raises(ValueError) as exc:
            cfg.validate_config()
        assert "profile" in str(exc.value).lower()

    def test_host_token_still_resolves(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = self._cfg(
            databricks_host="https://h", databricks_token="dapitok"
        )
        cfg.validate_config()


class TestApplyCliTarget:
    """F8a at the CLI seam: ``--host`` without ``--profile`` drops the ambient profile."""

    @pytest.fixture(autouse=True)
    def _ambient(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "default-profile")
        monkeypatch.setenv("STARBOARD_WORKSPACE", "alias-profile")

    def test_profile_is_exported(self) -> None:
        apply_cli_target(profile="chosen", host=None)
        assert os.environ["DATABRICKS_CONFIG_PROFILE"] == "chosen"

    def test_host_without_profile_drops_ambient_profile(self) -> None:
        apply_cli_target(profile=None, host="https://customer.cloud.databricks.com")
        assert "DATABRICKS_CONFIG_PROFILE" not in os.environ
        assert "STARBOARD_WORKSPACE" not in os.environ
        target = WorkspaceTarget.resolve(
            cfg=MagicMock(databricks_host="https://customer.cloud.databricks.com")
        )
        assert target.profile is None

    def test_profile_and_host_keep_profile(self) -> None:
        apply_cli_target(profile="chosen", host="https://h")
        assert os.environ["DATABRICKS_CONFIG_PROFILE"] == "chosen"

    def test_neither_leaves_environment_alone(self) -> None:
        apply_cli_target(profile=None, host=None)
        assert os.environ["DATABRICKS_CONFIG_PROFILE"] == "default-profile"
        assert os.environ["STARBOARD_WORKSPACE"] == "alias-profile"
