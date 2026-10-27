# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""F8a at the client seam: only a constructor ``host=`` override is an explicit host.

The CLIs map ``--profile`` onto ``DATABRICKS_CONFIG_PROFILE`` and ``--host`` /
``DATABRICKS_HOST`` onto ``cfg.databricks_host``. A cfg-derived host must keep
today's precedence (the profile wins), so ``--profile`` is not silently dropped
when an ambient ``DATABRICKS_HOST`` is set. No network: the SDK client is a fake.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from starboard.adapters.databricks import client as client_mod
from starboard.infra.auth import resolver as resolver_mod
from starboard.infra.auth.resolver import WorkspaceTarget
from starboard.infra.core.config import EnvConfig


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[WorkspaceTarget]:
    targets: list[WorkspaceTarget] = []
    sdk = MagicMock()
    sdk.config.host = "https://resolved.cloud.databricks.com"
    sdk.config.authenticate.return_value = {}

    def _resolve(target: WorkspaceTarget, **_: Any) -> MagicMock:
        targets.append(target)
        return sdk

    monkeypatch.setattr(resolver_mod, "resolve_workspace_client", _resolve)
    monkeypatch.setattr(
        client_mod.AsyncDatabricksClient, "_verify_auth", AsyncMock(return_value=True)
    )
    for var in ("STARBOARD_WORKSPACE", "DATABRICKS_CONFIG_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    return targets


def _cfg() -> EnvConfig:
    return EnvConfig(
        databricks_host="https://from-env.cloud.databricks.com",
        databricks_warehouse_id="wh-1",
        autocreate_dbx_dw=False,
        is_dbx_support=False,
    )


async def _init(client: client_mod.AsyncDatabricksClient) -> None:
    try:
        await client._initialize()
    finally:
        await client.close()


@pytest.mark.unit
class TestClientTargetPrecedence:
    async def test_cfg_host_keeps_ambient_profile(
        self, monkeypatch: pytest.MonkeyPatch, captured: list[WorkspaceTarget]
    ) -> None:
        monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "chosen-profile")
        await _init(client_mod.AsyncDatabricksClient(cfg=_cfg()))
        assert captured[0].profile == "chosen-profile"
        assert captured[0].host == "https://from-env.cloud.databricks.com"

    async def test_constructor_host_override_drops_ambient_profile(
        self, monkeypatch: pytest.MonkeyPatch, captured: list[WorkspaceTarget]
    ) -> None:
        monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "default-profile")
        await _init(
            client_mod.AsyncDatabricksClient(
                cfg=_cfg(), host="https://customer.cloud.databricks.com"
            )
        )
        assert captured[0].profile is None
        assert captured[0].host == "https://customer.cloud.databricks.com"
