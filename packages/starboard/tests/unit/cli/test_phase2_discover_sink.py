# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Phase 2 (P2-G1/G3/G12): ``starboard --discover --run-folder`` writes through the sink.

* Covered run (overlay + ``--run-folder``) against ``InMemoryEngagementStorage``:
  canonical relpaths, evidence index, empty sandbox diff, bounded compact stdout.
* Refusal of each local flag on a covered run, before any client is built.
* Redis is forced off on a covered run.
* The internal-only local exemption (``--authorization <run-dir>`` holding a local
  descriptor that authorizes the internal scope).

The public bytes are pinned by ``test_phase2_public_golden.py``.
"""

from __future__ import annotations

import argparse
import contextlib
import json
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console
from starboard.cli.cli import main as cli_main
from starboard.cli.cli.exit_codes import STORAGE_FAILURE, USAGE_ERROR
from starboard_core.engagement.policy import SourceMode
from starboard_core.engagement.write_guard import (
    LocalWriteRefused as _LocalWriteRefused,
)
from starboard_core.engagement.write_guard import active
from starboard_core.ports.engagement_storage import StorageError as _StorageError

from tests.unit.cli._engagement_support import (
    STDOUT_BUDGET,
    WS,
    covered_env,
    diff,
    drive_run,
    evidence,
    local_run_dir,
    overlay_on,
    sink_for,
    snapshot,
    written,
)
from tests.unit.cli.test_phase2_public_golden import GoldenEngine, discover_config

LAYOUT = {
    "raw/billing.json",
    "facts.json",
    "manifest.json",
    "discovery.json",
    "evidence/index.json",
}


class _Client:
    built = 0

    def __init__(self, *a: object, **k: object) -> None:
        _Client.built += 1

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *a: object) -> bool:
        return False

    async def get_workspace_id(self) -> str:
        return WS


@pytest.fixture(autouse=True)
def _engine(monkeypatch: pytest.MonkeyPatch) -> Any:
    _Client.built = 0
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", GoldenEngine)
    monkeypatch.setattr("starboard.bootstrap.AsyncSQLExecutor", lambda _c: object())
    monkeypatch.setattr(cli_main, "AsyncDatabricksClient", _Client)
    assert not active()
    yield
    assert not active()


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
        "include_deep_dive": False,
        "full_stdout": False,
        "stdout_mode": None,
        "authorization": None,
        "output_path": None,
        "out_dir": None,
        "run_folder": None,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


async def _discover(args: argparse.Namespace, config: Any = None) -> int:
    try:
        await cli_main.run_discovery_mode(
            args, config or discover_config(), Console(stderr=True)
        )
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_covered_run_writes_layout_evidence_and_bounded_stdout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, folder = drive_run()
    sandbox = covered_env(monkeypatch, tmp_path, store, cli_main)
    before = snapshot(sandbox)

    code = await _discover(_args(run_folder=folder))

    assert code == 0
    out = capsys.readouterr().out
    assert len(out.encode()) <= STDOUT_BUDGET
    assert out.count("\n") == 1  # compact JSON, no indent
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["run_folder_id"] == folder
    assert payload["summary"]["envelope_path"] == "discovery.json"
    # The digest rides along so a host need not re-read discovery.json.
    assert {"failed", "packs_with_gaps"} <= set(payload["summary"])
    assert diff(sandbox, before) == []
    sink = sink_for(store, folder)
    assert written(sink) == LAYOUT
    refs = evidence(sink)
    assert {r.storage_ref.path for r in refs} == LAYOUT - {"evidence/index.json"}
    for ref in refs:
        assert ref.scope_workspace_ids == (WS,)
        assert ref.source_kind == "customer_workspace"
        assert ref.run_id == sink.run_id
    envelope = json.loads(sink.get_bytes("discovery.json"))
    assert envelope["ok"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_out_dir_and_output_path_are_run_relative(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, folder = drive_run()
    sandbox = covered_env(monkeypatch, tmp_path, store, cli_main)
    before = snapshot(sandbox)

    code = await _discover(
        _args(run_folder=folder, out_dir="disc", output_path="exports/env.json")
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["layout_prefix"] == "disc"
    assert payload["summary"]["envelope_path"] == "exports/env.json"
    assert written(sink_for(store, folder)) == {
        *(f"disc/{p}" for p in LAYOUT - {"evidence/index.json"}),
        "exports/env.json",
        "evidence/index.json",
    }
    assert diff(sandbox, before) == []


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "flag"),
    [
        ({"stdout_mode": "full"}, "--stdout"),
        ({"full_stdout": True}, "--full-stdout"),
        ({"authorization": "/tmp/some-run"}, "--authorization"),
        ({"out_dir": "/tmp/out"}, "--out-dir"),
        ({"out_dir": "../escape"}, "--out-dir"),
        ({"output_path": "/tmp/env.json"}, "--output-path"),
        ({"output_path": "~/env.json"}, "--output-path"),
    ],
)
async def test_covered_run_refuses_local_flags_before_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    overrides: dict[str, object],
    flag: str,
) -> None:
    store, folder = drive_run()
    sandbox = covered_env(monkeypatch, tmp_path, store, cli_main)
    before = snapshot(sandbox)

    code = await _discover(_args(run_folder=folder, **overrides))

    assert code == USAGE_ERROR == 2
    env = json.loads(capsys.readouterr().out)
    assert env["ok"] is False
    assert env["error_type"] == "LOCAL_STORAGE_REFUSED"
    assert env["error"].startswith("LOCAL_STORAGE_REFUSED")
    assert flag in env["error"]
    assert _Client.built == 0
    assert written(sink_for(store, folder)) == set()
    assert diff(sandbox, before) == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_overlay_without_run_folder_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, _ = drive_run()
    covered_env(monkeypatch, tmp_path, store, cli_main)

    code = await _discover(_args(json=True, out_dir=str(tmp_path / "out")))

    assert code == 2
    env = json.loads(capsys.readouterr().out)
    assert env["error_type"] == "LOCAL_STORAGE_REFUSED"
    assert "--run-folder" in env["error"]
    assert not (tmp_path / "out").exists()
    assert _Client.built == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_folder_without_identity_check_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, folder = drive_run(identity=False)
    covered_env(monkeypatch, tmp_path, store, cli_main)

    code = await _discover(_args(run_folder=folder))

    assert code == 2
    env = json.loads(capsys.readouterr().out)
    assert env["ok"] is False
    assert "identity" in env["error"]
    assert _Client.built == 0
    assert written(sink_for(store, folder)) == set()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_covered_run_forces_redis_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, folder = drive_run()
    covered_env(monkeypatch, tmp_path, store, cli_main)
    monkeypatch.setenv("REDIS_URL", "redis://cache:6379/0")
    config = discover_config()
    config.redis_url = "redis://cache:6379/0"

    code = await _discover(_args(run_folder=folder), config)

    assert code == 0
    assert config.redis_url is None
    import os

    assert "REDIS_URL" not in os.environ
    assert "Redis is disabled" in capsys.readouterr().err


@pytest.mark.unit
def test_internal_only_local_run_dir_is_exempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """D-11: an internal-source run on an overlay install may write locally when
    ``--authorization`` names an internal-only local run dir authorizing the scope
    and ``--out-dir`` stays inside it."""
    overlay_on(monkeypatch, cli_main)
    run_dir = local_run_dir(tmp_path)
    with contextlib.ExitStack() as stack:
        ctx, ids = cli_main._discovery_storage(
            _args(authorization=str(run_dir), out_dir=str(run_dir / "discovery")),
            "internal",
            stack,
            internal_account="acme",
        )
    assert ctx is None
    assert ids is None


@pytest.mark.unit
def test_internal_out_dir_holding_a_descriptor_is_no_longer_exempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The old form (``--out-dir <run-dir>`` without ``--authorization``) is refused,
    and the refusal names the documented ``--authorization`` form."""
    overlay_on(monkeypatch, cli_main)
    run_dir = local_run_dir(tmp_path)
    with contextlib.ExitStack() as stack, pytest.raises(SystemExit) as exc:
        cli_main._discovery_storage(
            _args(out_dir=str(run_dir), json=True),
            "internal",
            stack,
            internal_account="acme",
        )
    assert exc.value.code == USAGE_ERROR
    body = json.loads(capsys.readouterr().out)
    assert body["error_type"] == "LOCAL_STORAGE_REFUSED"
    assert "--authorization <run-dir> --out-dir <run-dir>/discovery" in body["error"]


@pytest.mark.unit
def test_internal_run_without_local_descriptor_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    overlay_on(monkeypatch, cli_main)
    with contextlib.ExitStack() as stack, pytest.raises(SystemExit) as exc:
        cli_main._discovery_storage(
            _args(out_dir=str(tmp_path), internal_workspace_id="856", json=True),
            "internal",
            stack,
        )
    assert exc.value.code == 2
    assert "--run-folder" in json.loads(capsys.readouterr().out)["error"]


# --- internal source on a run folder: the descriptor authorizes it (arch M1) -----------


def _internal_storage(
    folder: str, *, account: str | None = None, workspace_ids: tuple[str, ...] = ()
) -> tuple[Any, Any]:
    with contextlib.ExitStack() as stack:
        return cli_main._discovery_storage(
            _args(run_folder=folder, json=True),
            "internal",
            stack,
            internal_account=account,
            internal_workspace_ids=workspace_ids,
        )


@pytest.mark.unit
@pytest.mark.parametrize("mode", [SourceMode.INTERNAL_ONLY, SourceMode.HYBRID])
def test_internal_run_folder_in_authorized_scope_is_allowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: SourceMode
) -> None:
    store, folder = drive_run(workspace_ids=("856",), source_mode=mode)
    covered_env(monkeypatch, tmp_path, store, cli_main)

    ctx, ids = _internal_storage(folder, workspace_ids=("856",))

    assert ctx is not None
    assert ids is None


@pytest.mark.unit
def test_internal_run_folder_account_matching_the_descriptor_is_allowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store, folder = drive_run(
        workspace_ids=("856",), source_mode=SourceMode.INTERNAL_ONLY
    )
    covered_env(monkeypatch, tmp_path, store, cli_main)
    monkeypatch.setattr(
        cli_main,
        "read_descriptor",
        _account_only_descriptor(cli_main.read_descriptor),
    )

    ctx, _ = _internal_storage(folder, account="acme")

    assert ctx is not None


def _account_only_descriptor(real: Any) -> Any:
    """The run descriptor, with ``authorized_scope`` narrowed to the account."""
    import dataclasses

    def read(storage: Any, folder_id: str) -> Any:
        auth, rest = real(storage, folder_id)
        return dataclasses.replace(auth, authorized_scope={"account_key": "acme"}), rest

    return read


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mode", "kwargs"),
    [
        (SourceMode.CUSTOMER_WORKSPACE, {"workspace_ids": ("856",)}),
        (SourceMode.INTERNAL_ONLY, {"workspace_ids": ("999",)}),
        (SourceMode.INTERNAL_ONLY, {"workspace_ids": ("856", "999")}),
        (SourceMode.INTERNAL_ONLY, {"account": "other"}),
        # An account-wide run is broader than a workspace-scoped descriptor.
        (SourceMode.INTERNAL_ONLY, {"account": "acme"}),
        (SourceMode.INTERNAL_ONLY, {}),
    ],
)
def test_internal_run_folder_outside_the_descriptor_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mode: SourceMode,
    kwargs: dict[str, Any],
) -> None:
    store, folder = drive_run(workspace_ids=("856",), source_mode=mode)
    covered_env(monkeypatch, tmp_path, store, cli_main)

    with pytest.raises(SystemExit) as exc:
        _internal_storage(folder, **kwargs)

    assert exc.value.code == USAGE_ERROR
    env = json.loads(capsys.readouterr().out)
    assert env["error_type"] == "INTERNAL_SCOPE_REFUSED"
    assert env["error"].startswith("INTERNAL_SCOPE_REFUSED")
    assert not active()


# --- refused writes are never swallowed (arch H3) ---------------------------------------


class _StraySQL:
    """A stub data source: every query returns one row; ``stray`` writes locally."""

    def __init__(self, stray: Path | None, *, swallow: bool) -> None:
        self.stray = stray
        self.swallow = swallow
        self.calls = 0

    async def execute_sql(self, sql: str) -> Any:
        import polars as pl

        self.calls += 1
        if self.stray is not None:
            try:
                self.stray.write_text("rows")
            except OSError:
                if not self.swallow:
                    raise
        return pl.DataFrame({"x": [1]})


def _real_engine(monkeypatch: pytest.MonkeyPatch, sql: _StraySQL) -> None:
    from starboard.discovery.engine import DiscoveryEngine

    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", DiscoveryEngine)
    monkeypatch.setattr("starboard.bootstrap.AsyncSQLExecutor", lambda _c: sql)
    monkeypatch.setattr(
        "starboard.check_connectivity",
        lambda *_a, **_k: argparse.Namespace(ok=True, kind=None, message=""),
    )


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("swallow", [True, False])
async def test_real_engine_canary_stray_local_write_fails_the_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    swallow: bool,
) -> None:
    """The real DiscoveryEngine on a covered run: a stray local write inside query
    execution (swallowed by the data source or not) exits non-zero, never ok:true."""
    store, folder = drive_run()
    sandbox = covered_env(monkeypatch, tmp_path, store, cli_main)
    stray = sandbox["cwd"] / "stray.csv"
    sql = _StraySQL(stray, swallow=swallow)
    _real_engine(monkeypatch, sql)
    before = snapshot(sandbox)

    code = await _discover(_args(run_folder=folder, discovery_domains=["billing"]))

    out = capsys.readouterr().out
    assert sql.calls > 0
    assert code == USAGE_ERROR, out
    lines = [json.loads(line) for line in out.splitlines() if line.strip()]
    assert all(line.get("ok") is not True for line in lines)
    assert lines[-1]["error_type"] == "LOCAL_STORAGE_REFUSED"
    assert not stray.exists()
    assert diff(sandbox, before) == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_real_engine_canary_clean_run_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, folder = drive_run()
    sandbox = covered_env(monkeypatch, tmp_path, store, cli_main)
    sql = _StraySQL(None, swallow=False)
    _real_engine(monkeypatch, sql)
    before = snapshot(sandbox)

    code = await _discover(_args(run_folder=folder, discovery_domains=["billing"]))

    out = capsys.readouterr().out
    assert code == 0, out
    assert json.loads(out)["ok"] is True
    assert sql.calls > 0
    assert diff(sandbox, before) == []


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        lambda: _LocalWriteRefused("open", "/tmp/x"),
        lambda: _StorageError("drive write failed"),
    ],
)
async def test_incremental_pack_write_refusal_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    error: Any,
) -> None:
    store, folder = drive_run()
    covered_env(monkeypatch, tmp_path, store, cli_main)

    class _PackDoneEngine(GoldenEngine):
        async def run(self, on_progress: Any = None) -> Any:
            result = await super().run()
            on_progress("pack_done", {"pack_result": result.pack_results[0]})
            return result

    def refuse(*_a: object, **_k: object) -> None:
        raise error()

    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _PackDoneEngine)
    monkeypatch.setattr("starboard_x.discovery.serialize.write_pack_file", refuse)

    code = await _discover(_args(run_folder=folder))

    out = capsys.readouterr().out
    assert code in (USAGE_ERROR, STORAGE_FAILURE), out
    assert json.loads(out.splitlines()[-1])["ok"] is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_incremental_drive_pack_write_does_not_block_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import threading

    from starboard_x.discovery import serialize

    store, folder = drive_run()
    covered_env(monkeypatch, tmp_path, store, cli_main)
    release = threading.Event()
    calls: list[str] = []
    real = serialize.write_pack_file

    class _PackDoneEngine(GoldenEngine):
        async def run(self, on_progress: Any = None) -> Any:
            result = await super().run()
            # Returns while the upload is still blocked: it runs off the loop.
            on_progress("pack_done", {"pack_result": result.pack_results[0]})
            calls.append("progress returned")
            release.set()
            return result

    def slow_write(*args: Any, **kwargs: Any) -> Any:
        assert release.wait(5)
        calls.append(threading.current_thread().name)
        return real(*args, **kwargs)

    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _PackDoneEngine)
    monkeypatch.setattr(serialize, "write_pack_file", slow_write)

    code = await _discover(_args(run_folder=folder))

    assert code == 0, capsys.readouterr().out
    assert calls[0] == "progress returned"
    assert calls[1].startswith("discovery-upload")
    assert written(sink_for(store, folder)) == LAYOUT
