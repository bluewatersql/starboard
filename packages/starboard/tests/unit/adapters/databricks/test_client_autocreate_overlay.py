# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""F8c: never auto-create a SQL warehouse on an internal-overlay install.

The overlay signal is injected (monkeypatched) so these tests do not depend on
whether the developer machine has the overlay installed. No network, no SDK
calls: the workspace client and the provisioner are fakes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard.adapters.databricks import client as client_mod
from starboard.adapters.databricks import warehouse_provisioner as wp_mod
from starboard.infra.auth import resolver as resolver_mod
from starboard.infra.core.config import EnvConfig
from starboard_core.engagement import overlay as overlay_mod
from starboard_core.engagement.overlay import OverlaySignal


def _set_overlay(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    signal = OverlaySignal(enabled=enabled, reasons=("test",) if enabled else ())
    monkeypatch.setattr(overlay_mod, "detect_overlay", lambda **_: signal)


def _cfg() -> EnvConfig:
    return EnvConfig(
        databricks_host="https://example.cloud.databricks.com",
        databricks_warehouse_id=None,
        autocreate_dbx_dw=True,
        offline_mode=False,
        is_dbx_support=False,
    )


@pytest.fixture
def provisioner(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    sdk = MagicMock()
    sdk.config.host = "https://example.cloud.databricks.com"
    sdk.config.authenticate.return_value = {}
    monkeypatch.setattr(resolver_mod, "resolve_workspace_client", lambda target: sdk)
    monkeypatch.setattr(
        client_mod.AsyncDatabricksClient, "_verify_auth", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        client_mod.AsyncDatabricksClient,
        "_resolve_warehouse_id",
        AsyncMock(return_value=None),
    )
    # Keep the process env clean if the provisioner path ever runs.
    monkeypatch.delenv("DATABRICKS_WAREHOUSE_ID", raising=False)
    instance = MagicMock()
    instance.provision = AsyncMock(return_value="wh-new")
    factory = MagicMock(return_value=instance)
    monkeypatch.setattr(wp_mod, "WarehouseProvisioner", factory)
    return factory


@pytest.mark.unit
class TestOverlayEnabledProperty:
    def test_true_when_signal_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_overlay(monkeypatch, True)
        assert EnvConfig().overlay_enabled is True

    def test_false_when_signal_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_overlay(monkeypatch, False)
        assert EnvConfig().overlay_enabled is False


@pytest.mark.unit
class TestWarehouseAutocreateOverlay:
    async def test_overlay_suppresses_autocreate(
        self, monkeypatch: pytest.MonkeyPatch, provisioner: MagicMock
    ) -> None:
        _set_overlay(monkeypatch, True)
        log = MagicMock()
        monkeypatch.setattr(client_mod, "logger", log)

        client = client_mod.AsyncDatabricksClient(cfg=_cfg())
        try:
            await client._initialize()
        finally:
            await client.close()

        provisioner.assert_not_called()
        assert client.config.databricks_warehouse_id is None
        events = [c.args[0] for c in log.warning.call_args_list]
        assert "warehouse_autocreate_suppressed_overlay" in events
        call = log.warning.call_args_list[
            events.index("warehouse_autocreate_suppressed_overlay")
        ]
        assert "DATABRICKS_WAREHOUSE_ID" in str(call.kwargs.get("extra", {}))

    async def test_public_path_still_autocreates(
        self, monkeypatch: pytest.MonkeyPatch, provisioner: MagicMock
    ) -> None:
        _set_overlay(monkeypatch, False)

        client = client_mod.AsyncDatabricksClient(cfg=_cfg())
        try:
            await client._initialize()
        finally:
            await client.close()

        provisioner.assert_called_once()
        assert client.config.databricks_warehouse_id == "wh-new"

    async def test_configured_warehouse_skips_overlay_probe(
        self, monkeypatch: pytest.MonkeyPatch, provisioner: MagicMock
    ) -> None:
        # With DATABRICKS_WAREHOUSE_ID set nothing is provisioned and no
        # suppression warning is logged, overlay or not.
        _set_overlay(monkeypatch, True)
        log = MagicMock()
        monkeypatch.setattr(client_mod, "logger", log)
        cfg = _cfg().model_copy(update={"databricks_warehouse_id": "wh-1"})

        client = client_mod.AsyncDatabricksClient(cfg=cfg)
        try:
            await client._initialize()
        finally:
            await client.close()

        provisioner.assert_not_called()
        events = [c.args[0] for c in log.warning.call_args_list]
        assert "warehouse_autocreate_suppressed_overlay" not in events
