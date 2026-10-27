# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the employee-context gate hook + port registry (Phase-2 C5).

Proves the two governance-critical properties (UNIFIED_PLAN §3.5):

1. The gate is **closed by default** — empty allowlist + no signals => every
   port resolves to its PUBLIC adapter.
2. The **additive invariant** — even when an internal context is detected
   (allowlisted host + a signal), with no internal adapter registered the
   registry still returns the public adapter. A wrong signal cannot leak data.
"""

from __future__ import annotations

import pytest
from starboard.infra.auth.resolver import (
    EmployeeContext,
    detect_employee_context,
    detect_employee_context_for_client,
    detect_gate_open,
)
from starboard.ports.registry import Port, PortRegistry


@pytest.mark.unit
class TestEmployeeContextDetector:
    def test_default_closed_empty_allowlist_no_signals(self) -> None:
        ctx = detect_employee_context(
            host="https://acme-corp.cloud.databricks.com",
            user="customer@acme.com",
            allowlist=[],
            env={},
        )
        assert ctx.is_internal_context is False
        assert ctx.gate_open is False
        assert ctx.signals == ()

    def test_allowlisted_host_is_internal_signal(self) -> None:
        ctx = detect_employee_context(
            host="https://e2-demo-field-eng.cloud.databricks.com",
            user="employee@databricks.com",
            allowlist=["e2-demo-field-eng"],
            env={},
        )
        assert ctx.is_internal_context is True
        assert any("host_allowlist" in s for s in ctx.signals)
        # authorized defaults True => gate opens once a context signal matches
        assert ctx.gate_open is True

    def test_isaac_identity_env_signal(self) -> None:
        ctx = detect_employee_context(
            host="https://anything.databricks.com",
            user="e@databricks.com",
            allowlist=[],
            env={"ISAAC_MANAGED_IDENTITY": "1"},
        )
        assert ctx.is_internal_context is True
        assert "isaac_identity" in ctx.signals

    def test_internal_mcp_env_signal(self) -> None:
        ctx = detect_employee_context(
            host="https://anything.databricks.com",
            allowlist=[],
            env={"STARBOARD_INTERNAL_MCP": "logs-summariser"},
        )
        assert ctx.is_internal_context is True
        assert any("internal_mcp" in s for s in ctx.signals)

    def test_context_signal_but_unauthorized_keeps_gate_closed(self) -> None:
        ctx = detect_employee_context(
            host="https://e2-demo-field-eng.cloud.databricks.com",
            allowlist=["e2-demo-field-eng"],
            authorized=False,
            env={},
        )
        assert ctx.is_internal_context is True
        assert ctx.gate_open is False

    def test_no_customer_host_hardcoded_default_allowlist(self) -> None:
        # A caller passing None/omitting the allowlist must stay closed.
        ctx = detect_employee_context(host="https://e2-demo-field-eng.databricks.com")
        assert ctx.is_internal_context is False
        assert ctx.gate_open is False

    def test_for_client_reuses_describe_auth_and_never_exposes_token(self) -> None:
        class _Cfg:
            host = "https://e2-demo-field-eng.cloud.databricks.com"
            auth_type = "pat"
            profile = None
            token = "SECRET-TOKEN"  # noqa: S105 - test fixture

        class _Me:
            user_name = "employee@databricks.com"

        class _CurrentUser:
            def me(self):
                return _Me()

        class _Client:
            config = _Cfg()
            current_user = _CurrentUser()

        ctx = detect_employee_context_for_client(
            _Client(), allowlist=["e2-demo-field-eng"], env={}
        )
        assert ctx.is_internal_context is True
        # redaction preserved: no token anywhere in the detected signals
        assert all("SECRET-TOKEN" not in s for s in ctx.signals)


@pytest.mark.unit
class TestPortRegistryAdditiveInvariant:
    def _registry(self) -> PortRegistry:
        reg = PortRegistry()
        reg.register_public(Port.LOG_RETRIEVAL, "public-log")
        reg.register_public(Port.DIAGNOSTIC_BACKEND, "public-diag")
        reg.register_public(Port.NL_QUERY, "public-nlq")
        reg.register_public(Port.FLEET_SQL, "public-fleet")
        return reg

    #: The C5 data-enablement ports — each ships a PUBLIC adapter. DISCOVERY_SOURCE
    #: deliberately has no public adapter (external discovery uses the executor's
    #: default SystemTablesSource directly), so it is excluded from this invariant.
    _DATA_ENABLEMENT_PORTS = (
        Port.LOG_RETRIEVAL,
        Port.DIAGNOSTIC_BACKEND,
        Port.NL_QUERY,
        Port.FLEET_SQL,
    )

    def test_gate_closed_selects_public(self) -> None:
        reg = self._registry()
        for port in self._DATA_ENABLEMENT_PORTS:
            assert reg.select_adapter(port, gate_open=False).startswith("public-")

    def test_gate_open_still_selects_public_when_no_internal_registered(self) -> None:
        # Phase-2: no internal adapter is registered, so opening the gate cannot
        # change the selection — proves the additive/no-leak invariant.
        reg = self._registry()
        for port in self._DATA_ENABLEMENT_PORTS:
            assert reg.select_adapter(port, gate_open=True).startswith("public-")
            assert reg.has_internal(port) is False

    def test_internal_selected_only_when_registered_and_gate_open(self) -> None:
        # Forward-looking (Phase 3): registering an internal adapter only takes
        # effect with the gate open; closed stays public.
        reg = self._registry()
        reg.register_internal(Port.FLEET_SQL, "internal-fleet")
        assert reg.select_adapter(Port.FLEET_SQL, gate_open=False) == "public-fleet"
        assert reg.select_adapter(Port.FLEET_SQL, gate_open=True) == "internal-fleet"

    def test_select_via_employee_context_gate_open_flag(self) -> None:
        reg = self._registry()
        ctx = EmployeeContext(is_internal_context=True, authorized=True, signals=("x",))
        # Even with an open context, public is returned (no internal registered).
        assert reg.select_adapter(
            Port.NL_QUERY, gate_open=ctx.gate_open
        ) == "public-nlq"


@pytest.mark.unit
class TestGateConfigDefaults:
    def test_allowlist_empty_and_internal_adapters_off_by_default(self) -> None:
        from starboard.infra.core.config import EnvConfig

        cfg = EnvConfig()
        assert cfg.internal_context_host_allowlist == []
        assert cfg.enable_internal_adapters is False

    def test_allowlist_parses_comma_separated_env(self) -> None:
        from starboard.infra.core.config import EnvConfig

        cfg = EnvConfig(internal_context_host_allowlist="e2-demo-field-eng, other-internal")
        assert cfg.internal_context_host_allowlist == [
            "e2-demo-field-eng",
            "other-internal",
        ]

    def test_internal_mode_defaults_false_and_inactive(self) -> None:
        from starboard.infra.core.config import EnvConfig

        cfg = EnvConfig()
        assert cfg.internal_mode is False
        # Even where the internal package happens to be installed, the flag being
        # off keeps internal mode inactive (public path).
        assert cfg.internal_mode_active is False

    def test_internal_mode_active_requires_flag_adapters_and_package(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from starboard.infra.core import config as config_mod
        from starboard.infra.core.config import EnvConfig

        # Package present: active requires BOTH the flag and enable_internal_adapters.
        monkeypatch.setattr(config_mod, "_starboard_internal_installed", lambda: True)
        assert (
            EnvConfig(internal_mode=True, enable_internal_adapters=True).internal_mode_active
            is True
        )
        assert (
            EnvConfig(internal_mode=True, enable_internal_adapters=False).internal_mode_active
            is False
        )
        assert (
            EnvConfig(internal_mode=False, enable_internal_adapters=True).internal_mode_active
            is False
        )

    def test_internal_mode_inactive_when_package_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # R2 fail-closed: even with the flag + adapters enabled, an uninstalled
        # internal package keeps internal mode inactive (safe no-op in the public
        # wheel).
        from starboard.infra.core import config as config_mod
        from starboard.infra.core.config import EnvConfig

        monkeypatch.setattr(config_mod, "_starboard_internal_installed", lambda: False)
        cfg = EnvConfig(internal_mode=True, enable_internal_adapters=True)
        assert cfg.internal_mode_active is False


@pytest.mark.unit
class TestDetectGateOpen:
    """The no-workspace-capable gate resolver (plan §1 item 2)."""

    def _cfg(self, monkeypatch: pytest.MonkeyPatch, *, installed: bool, **kwargs):
        from starboard.infra.core import config as config_mod
        from starboard.infra.core.config import EnvConfig

        monkeypatch.setattr(
            config_mod, "_starboard_internal_installed", lambda: installed
        )
        return EnvConfig(**kwargs)

    def _client(self, host: str):
        class _Cfg:
            auth_type = "pat"
            profile = None

        class _Me:
            user_name = "employee@databricks.com"

        class _CurrentUser:
            def me(self):
                return _Me()

        class _Client:
            config = _Cfg()
            current_user = _CurrentUser()

        _Cfg.host = host
        return _Client()

    def test_closed_by_default_no_client_no_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = self._cfg(monkeypatch, installed=True)
        ctx = detect_gate_open(cfg, env={})
        assert ctx.is_internal_context is False
        assert ctx.gate_open is False

    def test_force_internal_opens_gate_without_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = self._cfg(
            monkeypatch,
            installed=True,
            internal_mode=True,
            enable_internal_adapters=True,
        )
        ctx = detect_gate_open(
            cfg, env={"STARBOARD_INTERNAL_FLEET_WAREHOUSE_ID": "w-123"}
        )
        assert ctx.gate_open is True
        assert "force_internal_flag" in ctx.signals

    def test_force_internal_closed_when_package_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Fail-closed: no internal package => force path cannot fire, and the
        # deployment env var is not an MCP signal, so the gate stays closed.
        cfg = self._cfg(
            monkeypatch,
            installed=False,
            internal_mode=True,
            enable_internal_adapters=True,
        )
        ctx = detect_gate_open(
            cfg, env={"STARBOARD_INTERNAL_FLEET_WAREHOUSE_ID": "w-123"}
        )
        assert ctx.gate_open is False

    def test_force_internal_closed_when_adapters_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = self._cfg(
            monkeypatch,
            installed=True,
            internal_mode=True,
            enable_internal_adapters=False,
        )
        ctx = detect_gate_open(
            cfg, env={"STARBOARD_INTERNAL_FLEET_WAREHOUSE_ID": "w-123"}
        )
        assert ctx.gate_open is False

    def test_force_internal_closed_when_no_deployment_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = self._cfg(
            monkeypatch,
            installed=True,
            internal_mode=True,
            enable_internal_adapters=True,
        )
        ctx = detect_gate_open(cfg, env={})
        assert ctx.gate_open is False

    def test_force_internal_unauthorized_keeps_gate_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = self._cfg(
            monkeypatch,
            installed=True,
            internal_mode=True,
            enable_internal_adapters=True,
        )
        ctx = detect_gate_open(
            cfg,
            authorized=False,
            env={"STARBOARD_INTERNAL_FLEET_WAREHOUSE_ID": "w-123"},
        )
        assert ctx.is_internal_context is True
        assert ctx.gate_open is False

    def test_fallback_isaac_identity_without_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The existing three-signal path stays intact even with no live client.
        cfg = self._cfg(monkeypatch, installed=True)
        ctx = detect_gate_open(cfg, env={"ISAAC_MANAGED_IDENTITY": "1"})
        assert ctx.is_internal_context is True
        assert "isaac_identity" in ctx.signals
        assert ctx.gate_open is True

    def test_fallback_host_allowlist_requires_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = self._cfg(
            monkeypatch,
            installed=True,
            internal_context_host_allowlist="e2-demo-field-eng",
        )
        # With a live client whose host is allowlisted => host signal matches.
        client = self._client("https://e2-demo-field-eng.cloud.databricks.com")
        opened = detect_gate_open(cfg, client=client, env={})
        assert opened.gate_open is True
        assert any("host_allowlist" in s for s in opened.signals)
        # Without a client the host signal is absent => closed (wrong/absent
        # signal must not open the gate).
        closed = detect_gate_open(cfg, env={})
        assert closed.gate_open is False


@pytest.mark.unit
class TestInternalModeConfigValidation:
    """internal_mode skips workspace auth but never the LLM key check."""

    def test_active_internal_mode_skips_auth_keeps_llm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from starboard.infra.core import config as config_mod
        from starboard.infra.core.config import EnvConfig

        monkeypatch.setattr(config_mod, "_starboard_internal_installed", lambda: True)
        cfg = EnvConfig(
            internal_mode=True,
            enable_internal_adapters=True,
            llm_api_key="sk-test-key",  # noqa: S106 - test fixture
        )
        # No workspace auth resolvable, but internal mode is active => no raise.
        monkeypatch.setattr(cfg, "_auth_resolvable", lambda: False)
        cfg.validate_config()  # must not raise

    def test_active_internal_mode_still_requires_llm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from starboard.infra.core import config as config_mod
        from starboard.infra.core.config import EnvConfig

        monkeypatch.setattr(config_mod, "_starboard_internal_installed", lambda: True)
        cfg = EnvConfig(
            internal_mode=True, enable_internal_adapters=True, llm_api_key=None
        )
        monkeypatch.setattr(cfg, "_auth_resolvable", lambda: False)
        with pytest.raises(ValueError, match="LLM_API_KEY"):
            cfg.validate_config()

    def test_inactive_internal_mode_still_requires_auth(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Flag set but adapters disabled => inactive => auth is still required
        # (proves the flag is a no-op without its preconditions).
        from starboard.infra.core import config as config_mod
        from starboard.infra.core.config import EnvConfig

        monkeypatch.setattr(config_mod, "_starboard_internal_installed", lambda: True)
        cfg = EnvConfig(
            internal_mode=True,
            enable_internal_adapters=False,
            llm_api_key="sk-test-key",  # noqa: S106 - test fixture
        )
        monkeypatch.setattr(cfg, "_auth_resolvable", lambda: False)
        with pytest.raises(ValueError, match="No Databricks auth resolved"):
            cfg.validate_config()
