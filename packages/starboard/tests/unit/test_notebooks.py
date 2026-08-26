# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the synchronous notebook bootstrap helpers."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from starboard import notebooks


def _wh(
    id: str,
    name: str,
    *,
    serverless: bool = False,
    state: str = "STOPPED",
    warehouse_type: str = "PRO",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        name=name,
        enable_serverless_compute=serverless,
        state=f"State.{state}",
        warehouse_type=warehouse_type,
    )


def _client(warehouses: list[SimpleNamespace]) -> MagicMock:
    client = MagicMock()
    client.warehouses.list.return_value = warehouses
    by_id = {wh.id: wh for wh in warehouses}
    client.warehouses.get.side_effect = lambda wid: by_id[wid]
    return client


# --------------------------------------------------------------------------- #
# state / serverless helpers
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("State.RUNNING", "RUNNING"),
        ("RUNNING", "RUNNING"),
        (None, ""),
    ],
)
def test_state_name_normalizes(value: str | None, expected: str) -> None:
    assert notebooks._state_name(value) == expected


def test_state_name_reads_endpoint_state() -> None:
    assert notebooks._state_name(_wh("w1", "dw", state="STARTING")) == "STARTING"


def test_is_serverless() -> None:
    assert notebooks._is_serverless(_wh("w1", "dw", serverless=True)) is True
    assert notebooks._is_serverless(_wh("w1", "dw", serverless=False)) is False


# --------------------------------------------------------------------------- #
# resolve_warehouse
# --------------------------------------------------------------------------- #


def test_resolve_warehouse_by_id() -> None:
    client = _client([_wh("abc", "Analytics"), _wh("xyz", "Serverless DW")])
    info = notebooks.resolve_warehouse(client, "xyz")
    assert info["warehouse_id"] == "xyz"
    assert info["name"] == "Serverless DW"


def test_resolve_warehouse_by_name_case_insensitive() -> None:
    client = _client([_wh("abc", "Analytics")])
    info = notebooks.resolve_warehouse(client, "analytics")
    assert info["warehouse_id"] == "abc"


def test_resolve_warehouse_serverless_prefers_running() -> None:
    client = _client([
        _wh("s1", "Serverless A", serverless=True, state="STOPPED"),
        _wh("s2", "Serverless B", serverless=True, state="RUNNING"),
        _wh("c1", "Classic", serverless=False, state="RUNNING"),
    ])
    info = notebooks.resolve_warehouse(client, "serverless")
    assert info["warehouse_id"] == "s2"
    assert info["serverless"] is True
    assert info["state"] == "RUNNING"


def test_resolve_warehouse_serverless_none_available() -> None:
    client = _client([_wh("c1", "Classic", serverless=False)])
    with pytest.raises(RuntimeError, match="No serverless-enabled"):
        notebooks.resolve_warehouse(client, "serverless")


def test_resolve_warehouse_unknown_target() -> None:
    client = _client([_wh("abc", "Analytics")])
    with pytest.raises(RuntimeError, match="not a known warehouse id or name"):
        notebooks.resolve_warehouse(client, "does-not-exist")


# --------------------------------------------------------------------------- #
# start_warehouse
# --------------------------------------------------------------------------- #


def test_start_warehouse_already_running_is_noop() -> None:
    client = _client([_wh("w1", "DW", state="RUNNING")])
    info = notebooks.start_warehouse(client, "w1")
    assert info == {
        "warehouse_id": "w1",
        "name": "DW",
        "state": "RUNNING",
        "started": False,
    }
    client.warehouses.start.assert_not_called()


def test_start_warehouse_accepts_resolve_dict() -> None:
    client = _client([_wh("w1", "DW", state="RUNNING")])
    info = notebooks.start_warehouse(client, {"warehouse_id": "w1"})
    assert info["warehouse_id"] == "w1"


def test_start_warehouse_deleting_raises() -> None:
    client = _client([_wh("w1", "DW", state="DELETING")])
    with pytest.raises(RuntimeError, match="cannot start"):
        notebooks.start_warehouse(client, "w1")


def test_start_warehouse_no_wait_starts_and_returns() -> None:
    client = _client([_wh("w1", "DW", state="STOPPED")])
    info = notebooks.start_warehouse(client, "w1", wait=False)
    client.warehouses.start.assert_called_once_with("w1")
    client.warehouses.wait_get_warehouse_running.assert_not_called()
    assert info == {
        "warehouse_id": "w1",
        "name": "DW",
        "state": "STARTING",
        "started": True,
    }


def test_start_warehouse_wait_blocks_until_running() -> None:
    client = _client([_wh("w1", "DW", state="STOPPED")])
    info = notebooks.start_warehouse(client, "w1", wait=True, timeout_s=120)
    client.warehouses.start.assert_called_once_with("w1")
    client.warehouses.wait_get_warehouse_running.assert_called_once_with(
        "w1", timeout=timedelta(seconds=120)
    )
    assert info["state"] == "RUNNING"
    assert info["started"] is True


def test_start_warehouse_already_starting_does_not_restart() -> None:
    client = _client([_wh("w1", "DW", state="STARTING")])
    info = notebooks.start_warehouse(client, "w1", wait=True)
    client.warehouses.start.assert_not_called()
    client.warehouses.wait_get_warehouse_running.assert_called_once()
    assert info["started"] is False


# --------------------------------------------------------------------------- #
# list_serving_endpoints
# --------------------------------------------------------------------------- #


def test_list_serving_endpoints_filters_sorts_dedups() -> None:
    client = MagicMock()
    client.serving_endpoints.list.return_value = [
        SimpleNamespace(name="databricks-claude-opus-4-8"),
        SimpleNamespace(name="my-custom-endpoint"),
        SimpleNamespace(name="databricks-bge-large-en"),
        SimpleNamespace(name="databricks-claude-opus-4-8"),
        SimpleNamespace(name=None),
    ]
    result = notebooks.list_serving_endpoints(client)
    assert result == ["databricks-bge-large-en", "databricks-claude-opus-4-8"]


def test_list_serving_endpoints_custom_prefix() -> None:
    client = MagicMock()
    client.serving_endpoints.list.return_value = [
        SimpleNamespace(name="acme-gpt"),
        SimpleNamespace(name="databricks-claude"),
    ]
    assert notebooks.list_serving_endpoints(client, prefix="acme-") == ["acme-gpt"]


# --------------------------------------------------------------------------- #
# get_workspace
# --------------------------------------------------------------------------- #


def test_get_workspace_authenticates(monkeypatch: pytest.MonkeyPatch) -> None:
    # get_workspace now routes through the unified auth resolver (A1). Host+token
    # still yield a client (back-compat), but the resolver builds the client from
    # a Config that carries only the set fields, so we patch the resolver seam.
    from starboard.infra.auth import resolver as resolver_mod

    captured: dict[str, object] = {}

    class FakeConfig:
        def __init__(self, **kwargs: object) -> None:
            captured["config_kwargs"] = kwargs
            self.host = kwargs.get("host")
            self.auth_type = "pat"
            self.profile = kwargs.get("profile")

    fake_client = MagicMock()
    fake_client.current_user.me.return_value = SimpleNamespace(user_name="me@x.com")

    def fake_wc(*, config: object) -> object:
        fake_client.config = config
        return fake_client

    monkeypatch.setattr(resolver_mod, "Config", FakeConfig)
    monkeypatch.setattr(resolver_mod, "WorkspaceClient", fake_wc)

    result = notebooks.get_workspace("https://x.cloud.databricks.com", "tok")
    # Only the set fields (host, token) reach the SDK Config — nothing empty.
    assert captured["config_kwargs"] == {
        "host": "https://x.cloud.databricks.com",
        "token": "tok",
    }
    assert result is fake_client
