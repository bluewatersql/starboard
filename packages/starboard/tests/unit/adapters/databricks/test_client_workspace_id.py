# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``AsyncDatabricksClient.get_workspace_id`` — server-reported workspace ID.

The authorized-row-scope gate (engagement spec G3) proves the connected
workspace is authorized from this value, so it must come from the server's
``X-Databricks-Org-Id`` response header — never from local config (the SDK's own
``get_workspace_id`` returns ``Config.workspace_id`` without a round-trip when a
profile, env var or ``?o=`` sets it).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from starboard.adapters.databricks.client import AsyncDatabricksClient


def _client(
    header: object, config_workspace_id: str | None = None
) -> tuple[AsyncDatabricksClient, MagicMock]:
    client = AsyncDatabricksClient.__new__(AsyncDatabricksClient)
    sdk = MagicMock()
    sdk.config.workspace_id = config_workspace_id
    sdk.api_client.do.return_value = {"X-Databricks-Org-Id": header}
    client._sdk_client = sdk
    return client, sdk


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_workspace_id_returns_server_header_as_string() -> None:
    client, sdk = _client("1234567890")

    assert await client.get_workspace_id() == "1234567890"
    sdk.api_client.do.assert_called_once_with(
        "GET", "/api/2.0/preview/scim/v2/Me", response_headers=["X-Databricks-Org-Id"]
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_workspace_id_ignores_config_workspace_id() -> None:
    client, sdk = _client("1234567890", config_workspace_id="999")

    assert await client.get_workspace_id() == "1234567890"
    sdk.get_workspace_id.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("header", [None, "", "abc", "12a", "\u0661\u0662\u0663"])
async def test_get_workspace_id_rejects_missing_or_non_numeric_header(
    header: object,
) -> None:
    client, _ = _client(header)

    with pytest.raises(RuntimeError, match="workspace ID"):
        await client.get_workspace_id()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_workspace_id_requires_initialized_client() -> None:
    client = AsyncDatabricksClient.__new__(AsyncDatabricksClient)
    client._sdk_client = None

    with pytest.raises(RuntimeError, match="not initialized"):
        await client.get_workspace_id()
