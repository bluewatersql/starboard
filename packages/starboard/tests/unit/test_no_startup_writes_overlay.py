# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Exit test: an overlay install issues no customer-workspace writes at startup.

With the overlay enabled and a recording fake SDK client, the client is started
the way the CLI does (``AsyncDatabricksClient._initialize`` with the worst-case
config: auto-create on, support mode on, no warehouse configured). The only
calls allowed are reads; no warehouse create, no GRANT statement, no permission
or ACL write may be issued. No network, no real SDK.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard.adapters.databricks import client as client_mod
from starboard.adapters.databricks import support_mode as support_mod
from starboard.adapters.databricks.services.sql import SQLService
from starboard.infra.auth import resolver as resolver_mod
from starboard.infra.core.config import EnvConfig
from starboard_core.engagement import overlay as overlay_mod
from starboard_core.engagement.overlay import OverlaySignal

_WRITE_VERBS = (
    "create",
    "edit",
    "delete",
    "start",
    "stop",
    "set",
    "update",
    "grant",
    "execute",
    "post",
    "put",
    "patch",
)


class _RecordingSdk:
    """Fake SDK client that records every attribute-call path."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.config = MagicMock()
        self.config.host = "https://customer.cloud.databricks.com"
        self.config.authenticate.return_value = {"Authorization": "Bearer t"}

    def __getattr__(self, name: str) -> Any:
        return _Recorder(self.calls, name)


class _Recorder:
    def __init__(self, calls: list[str], path: str) -> None:
        self._calls = calls
        self._path = path

    def __getattr__(self, name: str) -> Any:
        return _Recorder(self._calls, f"{self._path}.{name}")

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self._calls.append(self._path)
        return MagicMock()


def _writes(calls: list[str]) -> list[str]:
    return [
        c
        for c in calls
        if any(part.startswith(_WRITE_VERBS) for part in c.split(".")[1:])
    ]


def _worst_case_cfg() -> EnvConfig:
    return EnvConfig(
        databricks_host="https://customer.cloud.databricks.com",
        databricks_warehouse_id=None,
        autocreate_dbx_dw=True,
        is_dbx_support=True,
        offline_mode=False,
    )


@pytest.fixture
def overlay_install(monkeypatch: pytest.MonkeyPatch) -> _RecordingSdk:
    signal = OverlaySignal(enabled=True, reasons=("test",))
    monkeypatch.setattr(overlay_mod, "detect_overlay", lambda **_: signal)
    sdk = _RecordingSdk()
    monkeypatch.setattr(resolver_mod, "resolve_workspace_client", lambda target: sdk)
    monkeypatch.setattr(
        client_mod.AsyncDatabricksClient, "_verify_auth", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        client_mod.AsyncDatabricksClient,
        "_resolve_warehouse_id",
        # A warehouse IS resolvable, so support mode would run its GRANTs.
        AsyncMock(return_value="wh-existing"),
    )
    monkeypatch.delenv("DATABRICKS_WAREHOUSE_ID", raising=False)
    monkeypatch.delenv("STARBOARD_DBX_SUPPORT", raising=False)
    return sdk


@pytest.fixture
def sql_statements(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every SQL statement any SQLService would execute."""
    statements: list[str] = []

    async def _record(self: Any, sql: str, *args: Any, **kwargs: Any) -> None:
        statements.append(sql)

    monkeypatch.setattr(SQLService, "execute_polars", _record)
    return statements


@pytest.mark.unit
class TestNoStartupWritesOnOverlay:
    async def test_startup_issues_no_warehouse_create_or_permission_write(
        self, overlay_install: _RecordingSdk, sql_statements: list[str]
    ) -> None:
        client = client_mod.AsyncDatabricksClient(cfg=_worst_case_cfg())
        try:
            await client._initialize()
        finally:
            await client.close()

        assert _writes(overlay_install.calls) == []
        assert not any("warehouses.create" in c for c in overlay_install.calls)
        assert not any("permissions" in c for c in overlay_install.calls)
        assert client.config.databricks_warehouse_id is None

    async def test_support_mode_grants_never_executed(
        self, overlay_install: _RecordingSdk, sql_statements: list[str]
    ) -> None:
        client = client_mod.AsyncDatabricksClient(cfg=_worst_case_cfg())
        try:
            await client._initialize()
        finally:
            await client.close()

        assert [s for s in sql_statements if "GRANT" in s.upper()] == []
        assert os.environ.get(support_mod._SUPPORT_ENV_KEY) != "TRUE"

    async def test_public_install_still_runs_support_grants(
        self,
        overlay_install: _RecordingSdk,
        sql_statements: list[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Control: the gate is overlay-specific, the public path is unchanged."""
        signal = OverlaySignal(enabled=False, reasons=())
        monkeypatch.setattr(overlay_mod, "detect_overlay", lambda **_: signal)
        client = client_mod.AsyncDatabricksClient(
            cfg=_worst_case_cfg().model_copy(
                update={"databricks_warehouse_id": "wh-existing"}
            )
        )
        try:
            await client._initialize()
        finally:
            await client.close()
            os.environ.pop(support_mod._SUPPORT_ENV_KEY, None)

        assert len([s for s in sql_statements if "GRANT" in s.upper()]) == 3
