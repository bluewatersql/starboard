# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for Databricks Apps on-behalf-of (OBO) per-user auth (D10, D-3.6).

Verifies that a per-user credentials strategy is injected through the EXISTING
A1 seam (``resolve_workspace_client(credentials_strategy=…)``) and reaches the
``WorkspaceClient``; that ``resolve_user_client`` builds and forwards that
strategy; that ``describe_auth`` stays redacted on an OBO client; and that the
default (no-strategy) path is byte-for-byte unchanged (regression guard).

A stub credentials strategy drives the flow so the tests do not depend on the
installed ``databricks-sdk`` shipping ``ModelServingUserCredentials``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from starboard.infra.auth import resolver as resolver_mod
from starboard.infra.auth.resolver import (
    WorkspaceTarget,
    build_user_credentials_strategy,
    describe_auth,
    resolve_user_client,
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


class _StubStrategy:
    """A stand-in credentials strategy — proves per-user injection flows through
    without depending on the real SDK ``ModelServingUserCredentials``."""

    auth_type = "model-serving-user-credentials"


def _capturing_workspace_client(captured: dict[str, Any]):
    """A fake ``WorkspaceClient`` that records ``config`` and (optional)
    ``credentials_strategy``. Accepts ``credentials_strategy`` only when the
    caller passes it, so the default path is asserted to omit it entirely."""

    def fake_wc(*, config: Any, credentials_strategy: Any = None) -> Any:
        captured["config"] = config
        captured["credentials_strategy"] = credentials_strategy
        captured["strategy_passed"] = "credentials_strategy" in captured
        return SimpleNamespace(config=config)

    return fake_wc


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


class TestPerUserStrategyReachesClient:
    def test_strategy_injected_through_seam(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stub strategy handed to the A1 seam reaches the WorkspaceClient,
        and the (subtractive) config is still built from the target."""
        captured: dict[str, Any] = {}
        stub = _StubStrategy()
        monkeypatch.setattr(resolver_mod, "Config", _FakeConfig)
        monkeypatch.setattr(
            resolver_mod, "WorkspaceClient", _capturing_workspace_client(captured)
        )

        client = resolve_workspace_client(
            WorkspaceTarget.resolve(host="https://h", token="tok"),
            credentials_strategy=stub,
        )

        assert client is not None
        assert captured["credentials_strategy"] is stub
        # build_config still applied subtractively (only set fields reach Config).
        assert captured["config"].kwargs == {"host": "https://h", "token": "tok"}

    def test_resolve_user_client_builds_and_forwards_strategy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``resolve_user_client`` constructs the per-user strategy and forwards
        it through the same seam — no separate auth path."""
        captured: dict[str, Any] = {}
        stub = _StubStrategy()
        monkeypatch.setattr(resolver_mod, "Config", _FakeConfig)
        monkeypatch.setattr(
            resolver_mod, "WorkspaceClient", _capturing_workspace_client(captured)
        )
        # Drive the flow with the stub instead of the real SDK class.
        monkeypatch.setattr(
            resolver_mod, "build_user_credentials_strategy", lambda: stub
        )

        client = resolve_user_client(WorkspaceTarget(host="https://app"))

        assert client is not None
        assert captured["credentials_strategy"] is stub
        assert captured["config"].kwargs == {"host": "https://app"}


class TestBuildUserCredentialsStrategy:
    def test_uses_sdk_model_serving_user_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The strategy is the SDK's ``ModelServingUserCredentials`` — resolved
        from ``databricks.sdk`` (the documented public location)."""
        import databricks.sdk as sdk_mod

        instances: list[Any] = []

        class _FakeMSUC:
            def __init__(self) -> None:
                instances.append(self)

        monkeypatch.setattr(
            sdk_mod, "ModelServingUserCredentials", _FakeMSUC, raising=False
        )

        strategy = build_user_credentials_strategy()

        assert isinstance(strategy, _FakeMSUC)
        assert len(instances) == 1

    def test_raises_clear_error_when_sdk_lacks_obo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the installed SDK predates OBO support, a clear RuntimeError is
        raised (never a bare ImportError leaking through)."""
        import builtins

        real_import = builtins.__import__

        def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "databricks.sdk":
                raise ImportError("no ModelServingUserCredentials")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        with pytest.raises(RuntimeError) as exc:
            build_user_credentials_strategy()
        assert "OBO" in str(exc.value) or "on-behalf-of" in str(exc.value)
        # The secret-free message names the remediation, not any credential.
        assert "databricks-sdk" in str(exc.value)


class TestDescribeAuthStaysRedactedUnderObo:
    def test_obo_client_describe_auth_redacts(self) -> None:
        """describe_auth on an OBO-style client still exposes only host/auth_type/
        profile/user — never token or strategy internals."""
        fake = SimpleNamespace(
            config=SimpleNamespace(
                host="https://h",
                auth_type="model-serving-user-credentials",
                profile=None,
                token="super-secret",  # must not leak
            ),
            current_user=SimpleNamespace(
                me=lambda: SimpleNamespace(user_name="enduser@x.com")
            ),
        )
        info = describe_auth(fake)
        assert info == {
            "host": "https://h",
            "auth_type": "model-serving-user-credentials",
            "profile": None,
            "user": "enduser@x.com",
        }
        assert "token" not in info
        assert "super-secret" not in str(info)


class TestDefaultPathUnchanged:
    def test_no_strategy_omits_credentials_strategy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression guard: with no strategy the resolver calls WorkspaceClient
        with config only — no credentials_strategy is ever passed."""
        captured: dict[str, Any] = {}

        def fake_wc(*, config: Any) -> Any:
            # Keyword-only, no credentials_strategy: fails if the default path
            # ever starts injecting one.
            captured["config"] = config
            return SimpleNamespace(config=config)

        monkeypatch.setattr(resolver_mod, "Config", _FakeConfig)
        monkeypatch.setattr(resolver_mod, "WorkspaceClient", fake_wc)

        client = resolve_workspace_client(
            WorkspaceTarget.resolve(host="https://h", token="tok")
        )

        assert client is not None
        assert captured["config"].kwargs == {"host": "https://h", "token": "tok"}
