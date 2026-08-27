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

    def test_gate_closed_selects_public(self) -> None:
        reg = self._registry()
        for port in Port:
            assert reg.select_adapter(port, gate_open=False).startswith("public-")

    def test_gate_open_still_selects_public_when_no_internal_registered(self) -> None:
        # Phase-2: no internal adapter is registered, so opening the gate cannot
        # change the selection — proves the additive/no-leak invariant.
        reg = self._registry()
        for port in Port:
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
