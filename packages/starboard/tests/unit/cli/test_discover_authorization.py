# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``starboard --discover --authorization <run-dir|file>`` (engagement spec G3).

Same contract as ``python -m starboard_x.discovery run --authorization``:

1. The run descriptor's ``authorized_scope.workspace_ids`` threads into
   ``EngineConfig.authorized_workspace_ids`` and the connected client's
   ``get_workspace_id`` becomes the engine's workspace-ID probe.
2. A missing / invalid descriptor is a usage error before any client is built.
3. Combining it with the internal source is a usage error (never ignored).
4. A connected workspace outside the scope is an auth error before any SQL.
5. Phase 2: on an internal-overlay install, customer discovery needs
   ``--run-folder`` (the scope is the Drive run descriptor); a local
   ``--authorization`` is refused (exit 2, ``LOCAL_STORAGE_REFUSED``) before any
   client is built. The local ``--authorization`` path stays the public-install
   form.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import polars as pl
import pytest
from rich.console import Console
from starboard.cli.cli import main as cli_main
from starboard.cli.cli.exit_codes import AUTH_ERROR, USAGE_ERROR
from starboard.discovery.engine import EngineResult
from starboard_core.engagement.overlay import OverlaySignal

RUN_ID = "20261008_3f2b8c1e-9d4a-4e6b-8a2f-1c3d5e7f9a0b"


def _write_authorization(run_dir: Path, workspace_ids: object) -> Path:
    """Write the run descriptor plus a verified identity check for the same run."""
    analysis = run_dir / "analysis"
    analysis.mkdir(parents=True, exist_ok=True)
    verified = (
        workspace_ids[0] if isinstance(workspace_ids, list) and workspace_ids else "123"
    )
    (analysis / "identity-check.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": RUN_ID,
                "provisional_account_key": "acme",
                "provisional_account_name": "Acme Corp",
                "provisional_source": "operator",
                "expected_workspace_id": str(verified),
                "expected_host": None,
                "observed_workspace_id": str(verified),
                "observed_host": "https://acme.cloud.databricks.com",
                "principal_id": "7781234",
                "principal_kind": "user",
                "checked_at": "2026-10-08T09:00:00+00:00",
                "status": "verified",
                "reasons": [],
            }
        )
    )
    path = analysis / "run-authorization.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": RUN_ID,
                "authorized_scope": {
                    "account_key": "acme",
                    "workspace_ids": workspace_ids,
                },
            }
        )
    )
    return path


def _overlay(monkeypatch: pytest.MonkeyPatch, *, enabled: bool) -> None:
    monkeypatch.setattr(
        cli_main,
        "detect_overlay",
        lambda **_kw: OverlaySignal(
            enabled=enabled, reasons=("test",) if enabled else ()
        ),
    )


def _args(**overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "discover": True,
        "data_only": True,
        "no_cache": True,
        "json": False,
        "lookback_days": 30,
        "discovery_domains": None,
        "internal_account": None,
        "internal_workspace_id": None,
        "authorization": None,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _config() -> MagicMock:
    config = MagicMock()
    config.discovery_max_parallelism = 4
    config.discovery_output_dir = "/tmp/starboard-test-discovery"
    config.discovery_llm_model = None
    config.discovery_llm_temperature = 0.3
    config.discovery_internal_source_account = None
    config.discovery_internal_source_workspace_id = None
    return config


class _FakeClient:
    built = 0

    def __init__(self, *a: object, **k: object) -> None:
        _FakeClient.built += 1
        self.workspace_id = "123"

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *a: object) -> bool:
        return False

    async def get_workspace_id(self) -> str:
        return self.workspace_id


class _FakeEngine:
    captured: dict[str, Any] = {}

    def __init__(self, sql_executor, llm_client, config, **kwargs) -> None:  # noqa: ANN001
        _FakeEngine.captured = {"config": config, **kwargs}

    async def run(self, on_progress=None):  # noqa: ANN001, ANN201
        return EngineResult(trace_id="t")


class _Exec:
    def __init__(self, *a: object) -> None:
        self.sql: list[str] = []

    async def execute_sql(self, sql: str) -> pl.DataFrame:
        self.sql.append(sql)
        return pl.DataFrame({"n": [1]})


@pytest.fixture(autouse=True)
def _reset() -> None:
    _FakeClient.built = 0
    _FakeEngine.captured = {}


@pytest.mark.unit
def test_parser_accepts_authorization() -> None:
    ns = cli_main.parse_args(["--discover", "--authorization", "runs/r1"])
    assert ns.authorization == "runs/r1"
    assert cli_main.parse_args(["--discover"]).authorization is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_authorization_threads_scope_and_probe(monkeypatch, tmp_path) -> None:
    _write_authorization(tmp_path, ["123"])
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _FakeEngine)
    monkeypatch.setattr("starboard.bootstrap.AsyncSQLExecutor", MagicMock())
    monkeypatch.setattr(cli_main, "AsyncDatabricksClient", _FakeClient)

    await cli_main.run_discovery_mode(
        _args(authorization=str(tmp_path)), _config(), Console()
    )

    cfg = _FakeEngine.captured["config"]
    assert cfg.source == "external"
    assert cfg.authorized_workspace_ids == ("123",)
    probe = _FakeEngine.captured["workspace_id_probe"]
    assert await probe() == "123"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_descriptor_file_path_is_accepted(monkeypatch, tmp_path) -> None:
    path = _write_authorization(tmp_path, ["123"])
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _FakeEngine)
    monkeypatch.setattr("starboard.bootstrap.AsyncSQLExecutor", MagicMock())
    monkeypatch.setattr(cli_main, "AsyncDatabricksClient", _FakeClient)

    await cli_main.run_discovery_mode(
        _args(authorization=str(path)), _config(), Console()
    )

    assert _FakeEngine.captured["config"].authorized_workspace_ids == ("123",)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_authorization_leaves_scope_unset(monkeypatch) -> None:
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _FakeEngine)
    monkeypatch.setattr("starboard.bootstrap.AsyncSQLExecutor", MagicMock())
    monkeypatch.setattr(cli_main, "AsyncDatabricksClient", _FakeClient)

    await cli_main.run_discovery_mode(_args(), _config(), Console())

    assert _FakeEngine.captured["config"].authorized_workspace_ids is None
    assert "workspace_id_probe" not in _FakeEngine.captured


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("workspace_ids", [None, [], ["12a"], [123], ["123", "456"]])
async def test_invalid_descriptor_is_usage_error_before_client(
    monkeypatch, tmp_path, capsys, workspace_ids
) -> None:
    if workspace_ids is not None:
        _write_authorization(tmp_path, workspace_ids)
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _FakeEngine)
    monkeypatch.setattr(cli_main, "AsyncDatabricksClient", _FakeClient)

    with pytest.raises(SystemExit) as exc:
        await cli_main.run_discovery_mode(
            _args(authorization=str(tmp_path), json=True), _config(), Console()
        )

    assert exc.value.code == USAGE_ERROR
    assert _FakeClient.built == 0
    assert _FakeEngine.captured == {}
    env = json.loads(capsys.readouterr().out)
    assert env["ok"] is False
    assert "--authorization" in env["error"]


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "internal",
    [{"internal_workspace_id": "1444828305810485"}, {"internal_account": "a"}],
)
async def test_authorization_with_internal_source_is_usage_error(
    monkeypatch, tmp_path, internal
) -> None:
    _write_authorization(tmp_path, ["123"])
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _FakeEngine)
    monkeypatch.setattr(cli_main, "AsyncDatabricksClient", _FakeClient)

    with pytest.raises(SystemExit) as exc:
        await cli_main.run_discovery_mode(
            _args(authorization=str(tmp_path), **internal), _config(), Console()
        )

    assert exc.value.code == USAGE_ERROR
    assert _FakeEngine.captured == {}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unauthorized_workspace_is_auth_error_before_any_sql(
    monkeypatch, tmp_path, capsys
) -> None:
    """Real engine: the connected workspace (999) is outside the scope (123)."""
    _write_authorization(tmp_path, ["123"])
    executor = _Exec()

    class _Client(_FakeClient):
        def __init__(self, *a: object, **k: object) -> None:
            super().__init__()
            self.workspace_id = "999"

    monkeypatch.setattr(cli_main, "AsyncDatabricksClient", _Client)
    monkeypatch.setattr("starboard.bootstrap.AsyncSQLExecutor", lambda _c: executor)

    with pytest.raises(SystemExit) as exc:
        await cli_main.run_discovery_mode(
            _args(authorization=str(tmp_path), json=True), _config(), Console()
        )

    assert exc.value.code == AUTH_ERROR
    assert executor.sql == []
    env = json.loads(capsys.readouterr().out)
    assert env["ok"] is False
    assert "999" in env["error"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_authorized_workspace_runs_scoped_sql(monkeypatch, tmp_path) -> None:
    """Real engine: every statement is limited to the authorized workspace."""
    _write_authorization(tmp_path, ["123"])
    executor = _Exec()
    monkeypatch.setattr(cli_main, "AsyncDatabricksClient", _FakeClient)
    monkeypatch.setattr("starboard.bootstrap.AsyncSQLExecutor", lambda _c: executor)

    await cli_main.run_discovery_mode(
        _args(authorization=str(tmp_path), discovery_domains=["billing"]),
        _config(),
        Console(),
    )

    assert executor.sql, "expected discovery SQL to run"
    system_sql = [s for s in executor.sql if "system." in s and "information_schema" not in s]
    assert system_sql, "expected discovery to read system tables"
    for sql in system_sql:
        assert "workspace_id IN ('123')" in sql


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unverified_identity_is_usage_error_before_client(
    monkeypatch, tmp_path, capsys
) -> None:
    _write_authorization(tmp_path, ["123"])
    (tmp_path / "analysis" / "identity-check.json").unlink()
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _FakeEngine)
    monkeypatch.setattr(cli_main, "AsyncDatabricksClient", _FakeClient)

    with pytest.raises(SystemExit) as exc:
        await cli_main.run_discovery_mode(
            _args(authorization=str(tmp_path), json=True), _config(), Console()
        )

    assert exc.value.code == USAGE_ERROR
    assert _FakeClient.built == 0
    assert "identity check" in json.loads(capsys.readouterr().out)["error"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_overlay_without_run_folder_is_refused_before_client(
    monkeypatch, capsys
) -> None:
    """Phase 2: an overlay customer discovery needs --run-folder (exit 2, no client)."""
    _overlay(monkeypatch, enabled=True)
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _FakeEngine)
    monkeypatch.setattr(cli_main, "AsyncDatabricksClient", _FakeClient)

    with pytest.raises(SystemExit) as exc:
        await cli_main.run_discovery_mode(_args(json=True), _config(), Console())

    assert exc.value.code == USAGE_ERROR
    assert _FakeClient.built == 0
    assert _FakeEngine.captured == {}
    env = json.loads(capsys.readouterr().out)
    assert env == {
        "ok": False,
        "error": env["error"],
        "error_type": "LOCAL_STORAGE_REFUSED",
    }
    assert env["error"].startswith("LOCAL_STORAGE_REFUSED")
    assert "--run-folder" in env["error"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_overlay_local_authorization_is_refused_before_client(
    monkeypatch, tmp_path, capsys
) -> None:
    """Phase 2: a local --authorization on a covered run is refused (exit 2)."""
    _overlay(monkeypatch, enabled=True)
    _write_authorization(tmp_path, ["123"])
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _FakeEngine)
    monkeypatch.setattr(cli_main, "AsyncDatabricksClient", _FakeClient)

    with pytest.raises(SystemExit) as exc:
        await cli_main.run_discovery_mode(
            _args(authorization=str(tmp_path), json=True), _config(), Console()
        )

    assert exc.value.code == USAGE_ERROR
    assert _FakeClient.built == 0
    assert _FakeEngine.captured == {}
    env = json.loads(capsys.readouterr().out)
    assert env["error_type"] == "LOCAL_STORAGE_REFUSED"
    assert "--authorization" in env["error"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_overlay_run_folder_runs_scoped_sql(
    monkeypatch, tmp_path, capsys
) -> None:
    """Phase 2: the covered run's scope comes from the Drive descriptor; every
    statement is limited to the authorized workspace."""
    from tests.unit.cli._engagement_support import covered_env, drive_run

    store, folder = drive_run()
    covered_env(monkeypatch, tmp_path, store, cli_main)
    executor = _Exec()
    monkeypatch.setattr(cli_main, "AsyncDatabricksClient", _FakeClient)
    monkeypatch.setattr("starboard.bootstrap.AsyncSQLExecutor", lambda _c: executor)

    await cli_main.run_discovery_mode(
        _args(run_folder=folder, discovery_domains=["billing"]), _config(), Console()
    )

    out = capsys.readouterr().out
    assert json.loads(out)["ok"] is True
    system_sql = [s for s in executor.sql if "system." in s and "information_schema" not in s]
    assert system_sql, "expected discovery to read system tables"
    for sql in system_sql:
        assert "workspace_id IN ('123')" in sql


@pytest.mark.unit
@pytest.mark.asyncio
async def test_public_install_without_authorization_runs_unscoped(monkeypatch) -> None:
    _overlay(monkeypatch, enabled=False)
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _FakeEngine)
    monkeypatch.setattr("starboard.bootstrap.AsyncSQLExecutor", MagicMock())
    monkeypatch.setattr(cli_main, "AsyncDatabricksClient", _FakeClient)

    await cli_main.run_discovery_mode(_args(), _config(), Console())

    assert _FakeEngine.captured["config"].authorized_workspace_ids is None
