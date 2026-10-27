# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Discovery's read-only warehouse check (``require_warehouse_access``).

A denied or missing warehouse raises :class:`WarehouseAccessError` naming the ID
and the warehouses this identity can see. The check never picks or creates a
warehouse. No network: the SDK workspace client is a fake.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.errors import NotFound, PermissionDenied
from starboard.adapters.databricks.client import AsyncDatabricksClient
from starboard.exceptions import WarehouseAccessError
from starboard.infra.core.config import EnvConfig


def _client(
    *, configured: str | None = None, require: bool = True
) -> tuple[AsyncDatabricksClient, MagicMock]:
    cfg = EnvConfig(
        databricks_host="https://example.cloud.databricks.com",
        databricks_warehouse_id=configured,
        autocreate_dbx_dw=False,
        offline_mode=False,
    )
    sdk = MagicMock()
    sdk.settings.default_warehouse_id.get.return_value = SimpleNamespace(
        string_val=SimpleNamespace(value="wh-default")
    )
    sdk.warehouses.list.return_value = [
        SimpleNamespace(id="wh-a"),
        SimpleNamespace(id="wh-b"),
    ]
    client = AsyncDatabricksClient(cfg=cfg, require_warehouse_access=require)
    client._sdk_client = sdk
    return client, sdk


@pytest.mark.unit
class TestWarehouseAccess:
    async def test_denied_default_warehouse_names_id_and_candidates(self) -> None:
        client, sdk = _client()
        sdk.warehouses.get.side_effect = PermissionDenied("no CAN_USE")

        with pytest.raises(WarehouseAccessError) as exc:
            await client._resolve_warehouse_id()

        err = exc.value
        assert err.code == "WAREHOUSE_PERMISSION_DENIED"
        assert err.warehouse_id == "wh-default"
        assert err.candidates == ("wh-a", "wh-b")
        assert "wh-default" in str(err)
        assert "workspace default" in str(err)
        assert "--warehouse-id" in err.hint
        sdk.warehouses.get.assert_called_once_with("wh-default")
        sdk.warehouses.create.assert_not_called()

    async def test_missing_configured_warehouse_is_refused(self) -> None:
        client, sdk = _client(configured="wh-gone")
        sdk.warehouses.get.side_effect = NotFound("no such warehouse")

        with pytest.raises(WarehouseAccessError) as exc:
            await client._resolve_warehouse_id()

        assert exc.value.warehouse_id == "wh-gone"
        assert "not found" in str(exc.value)
        sdk.settings.default_warehouse_id.get.assert_not_called()

    async def test_candidates_are_best_effort(self) -> None:
        client, sdk = _client()
        sdk.warehouses.get.side_effect = PermissionDenied("no CAN_USE")
        sdk.warehouses.list.side_effect = PermissionDenied("cannot list")

        with pytest.raises(WarehouseAccessError) as exc:
            await client._resolve_warehouse_id()

        assert exc.value.candidates == ()
        assert "none visible" in str(exc.value)

    async def test_usable_warehouse_resolves(self) -> None:
        client, sdk = _client(configured="wh-ok")
        assert await client._resolve_warehouse_id() == "wh-ok"
        sdk.warehouses.get.assert_called_once_with("wh-ok")

    async def test_check_is_off_by_default(self) -> None:
        client, sdk = _client(require=False)
        sdk.warehouses.get.side_effect = PermissionDenied("no CAN_USE")
        assert await client._resolve_warehouse_id() == "wh-default"
        sdk.warehouses.get.assert_not_called()
