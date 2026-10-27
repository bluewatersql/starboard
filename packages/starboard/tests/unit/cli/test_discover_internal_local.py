# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Run-2 fixes on ``starboard --discover``.

* internal_only_local capture: ``--authorization <run-dir>`` with the internal flags
  and no ``--run-folder`` is the local run dir; the descriptor must authorize the
  internal scope and ``--out-dir`` must stay inside the run dir.
* An expired internal sign-in exits ``AUTH_ERROR`` with ``INTERNAL_AUTH_REQUIRED``,
  a re-login hint and no traceback.
* A run where no scheduled query succeeded still writes its layout but reports
  ``status: no_evidence`` / ``ok: false`` and exits non-zero; a partial run exits 0.
* ``--warehouse-id`` sets ``databricks_warehouse_id``.
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
from starboard.cli.cli.exit_codes import AUTH_ERROR, GENERAL_ERROR, USAGE_ERROR
from starboard.discovery.engine import EngineResult
from starboard_core.domain.models.discovery.query import PackResult, QueryResult
from starboard_core.engagement.policy import SourceMode, StoragePolicy
from starboard_core.engagement.records import AccountRef, RunAuthorization
from starboard_core.ports.fleet_sql import FleetSourceAuthRequired

from tests.unit.cli._engagement_support import (
    RID,
    covered_env,
    drive_run,
    overlay_on,
)
from tests.unit.cli.test_phase2_public_golden import GoldenEngine, discover_config


class _Client:
    def __init__(self, *a: object, **k: object) -> None:
        pass

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *a: object) -> bool:
        return False

    async def get_workspace_id(self) -> str:
        return "123"


@pytest.fixture(autouse=True)
def _engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", GoldenEngine)
    monkeypatch.setattr("starboard.bootstrap.AsyncSQLExecutor", lambda _c: object())
    monkeypatch.setattr(cli_main, "AsyncDatabricksClient", _Client)


def _args(**overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "discover": True,
        "data_only": True,
        "no_cache": True,
        "json": True,
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


def _run_dir(
    root: Path,
    *,
    scope: dict[str, Any],
    source_mode: SourceMode = SourceMode.INTERNAL_ONLY,
    storage_policy: StoragePolicy = StoragePolicy.INTERNAL_ONLY_LOCAL,
) -> Path:
    """A local run dir whose descriptor authorizes ``scope``."""
    run_dir = root / "run"
    (run_dir / "analysis").mkdir(parents=True)
    auth = RunAuthorization(
        engagement_id="internal/workspace/ws-856",
        run_id=RID,
        intent="discovery",
        task="workspace",
        account=AccountRef(id="acme", display_name="Acme", verifier="operator"),
        requested_scope={},
        authorized_scope=scope,
        reporting_interval="P30D",
        timezone="UTC",
        source_mode=source_mode,
        storage_policy=storage_policy,
        audience="internal",
        methodology_version="m1",
    )
    (run_dir / "analysis" / "run-authorization.json").write_text(
        json.dumps(auth.to_dict())
    )
    return run_dir


def _storage(
    args: argparse.Namespace, *, workspace_ids: tuple[str, ...] = ("856",)
) -> tuple[Any, Any]:
    with contextlib.ExitStack() as stack:
        return cli_main._discovery_storage(
            args, "internal", stack, internal_workspace_ids=workspace_ids
        )


def _refused(
    capsys: pytest.CaptureFixture[str], args: argparse.Namespace, **kw: Any
) -> tuple[dict[str, Any], str]:
    with pytest.raises(SystemExit) as exc:
        _storage(args, **kw)
    assert exc.value.code == USAGE_ERROR
    captured = capsys.readouterr()
    return json.loads(captured.out), captured.err


async def _discover(args: argparse.Namespace) -> int:
    try:
        await cli_main.run_discovery_mode(args, discover_config(), Console(stderr=True))
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


# --- internal_only_local capture -------------------------------------------------


@pytest.mark.unit
def test_in_scope_internal_local_run_is_allowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """(a) The descriptor authorizes the workspace and --out-dir is inside the run."""
    overlay_on(monkeypatch, cli_main)
    run_dir = _run_dir(tmp_path, scope={"workspace_ids": ["856"]})
    args = _args(authorization=str(run_dir), out_dir=str(run_dir / "discovery"))
    assert _storage(args) == (None, None)


@pytest.mark.unit
def test_descriptor_file_path_also_names_the_run_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    overlay_on(monkeypatch, cli_main)
    run_dir = _run_dir(tmp_path, scope={"workspace_ids": ["856"]})
    args = _args(
        authorization=str(run_dir / "analysis" / "run-authorization.json"),
        out_dir=str(run_dir / "discovery"),
    )
    assert _storage(args) == (None, None)


@pytest.mark.unit
def test_out_of_scope_workspace_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """(b) A workspace outside authorized_scope.workspace_ids."""
    overlay_on(monkeypatch, cli_main)
    run_dir = _run_dir(tmp_path, scope={"workspace_ids": ["856"]})
    args = _args(authorization=str(run_dir), out_dir=str(run_dir / "discovery"))
    body, _ = _refused(capsys, args, workspace_ids=("999",))
    assert body["error_type"] == "INTERNAL_SCOPE_REFUSED"
    assert "999" in body["error"]


@pytest.mark.unit
def test_out_dir_outside_the_run_dir_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """(c) --out-dir must resolve inside the run dir."""
    overlay_on(monkeypatch, cli_main)
    run_dir = _run_dir(tmp_path, scope={"workspace_ids": ["856"]})
    args = _args(authorization=str(run_dir), out_dir=str(tmp_path / "elsewhere"))
    body, _ = _refused(capsys, args)
    assert body["error_type"] == "LOCAL_STORAGE_REFUSED"
    assert "outside the run directory" in body["error"]


@pytest.mark.unit
def test_sibling_prefix_dir_is_outside_the_run_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    overlay_on(monkeypatch, cli_main)
    run_dir = _run_dir(tmp_path, scope={"workspace_ids": ["856"]})
    args = _args(authorization=str(run_dir), out_dir=f"{run_dir}-other/discovery")
    body, _ = _refused(capsys, args)
    assert body["error_type"] == "LOCAL_STORAGE_REFUSED"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("source_mode", "storage_policy"),
    [
        (SourceMode.INTERNAL_ONLY, StoragePolicy.DRIVE_REQUIRED),
        (SourceMode.INTERNAL_ONLY, StoragePolicy.LOCAL),
        (SourceMode.HYBRID, StoragePolicy.DRIVE_REQUIRED),
    ],
)
def test_descriptor_without_internal_only_local_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    source_mode: SourceMode,
    storage_policy: StoragePolicy,
) -> None:
    """(d) A local internal run needs internal_only + internal_only_local."""
    overlay_on(monkeypatch, cli_main)
    run_dir = _run_dir(
        tmp_path,
        scope={"workspace_ids": ["856"]},
        source_mode=source_mode,
        storage_policy=storage_policy,
    )
    args = _args(authorization=str(run_dir), out_dir=str(run_dir / "discovery"))
    body, _ = _refused(capsys, args)
    assert body["error_type"] in {"LOCAL_STORAGE_REFUSED", "INTERNAL_SCOPE_REFUSED"}


@pytest.mark.unit
def test_descriptor_policy_is_checked_without_the_overlay(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """(d) Fail closed on a public install too: the descriptor still must match."""
    run_dir = _run_dir(
        tmp_path,
        scope={"workspace_ids": ["856"]},
        storage_policy=StoragePolicy.DRIVE_REQUIRED,
    )
    args = _args(authorization=str(run_dir), out_dir=str(run_dir / "discovery"))
    body, _ = _refused(capsys, args)
    assert body["error_type"] == "INTERNAL_SCOPE_REFUSED"
    assert "internal_only_local" in body["error"]


@pytest.mark.unit
def test_authorization_with_run_folder_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """(e) --authorization never goes with --run-folder."""
    store, folder = drive_run()
    covered_env(monkeypatch, tmp_path, store, cli_main)
    run_dir = _run_dir(tmp_path, scope={"workspace_ids": ["856"]})
    with pytest.raises(SystemExit) as exc:
        _storage(_args(authorization=str(run_dir), run_folder=folder))
    assert exc.value.code == USAGE_ERROR
    assert "--authorization" in json.loads(capsys.readouterr().out)["error"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_old_out_dir_form_is_refused_with_reason_and_code_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """(f)+(g) ``--out-dir <run-dir>`` alone no longer exempts; stderr carries the
    decision reason and the refusal code exactly once."""
    overlay_on(monkeypatch, cli_main)
    run_dir = _run_dir(tmp_path, scope={"workspace_ids": ["856"]})
    code = await _discover(_args(internal_workspace_id="856", out_dir=str(run_dir)))
    assert code == USAGE_ERROR
    err = " ".join(capsys.readouterr().err.split())  # undo rich wrapping
    assert err.count("LOCAL_STORAGE_REFUSED") == 1
    assert "no internal-only local descriptor" in err
    assert "--authorization <run-dir> --out-dir <run-dir>/discovery" in err
    assert not (run_dir / "raw").exists()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_internal_local_run_writes_inside_the_run_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    overlay_on(monkeypatch, cli_main)
    run_dir = _run_dir(tmp_path, scope={"workspace_ids": ["856"]})
    code = await _discover(
        _args(
            internal_workspace_id="856",
            authorization=str(run_dir),
            out_dir=str(run_dir / "discovery"),
        )
    )
    assert code == 0
    assert (run_dir / "discovery" / "manifest.json").is_file()
    assert json.loads(capsys.readouterr().out)["data"]["status"] == "partial"


# --- expired internal sign-in -------------------------------------------------------


class _InternalAuthRequired(FleetSourceAuthRequired):
    code = "INTERNAL_AUTH_REQUIRED"


class _AuthExpiredEngine:
    def __init__(self, *a: Any, **k: Any) -> None:
        raise _InternalAuthRequired(
            "internal source sign-in expired for profile p; run "
            "`databricks auth login --profile p` then resume capture",
            hint="databricks auth login --profile p",
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_internal_auth_expiry_exits_auth_error_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _AuthExpiredEngine)
    code = await _discover(_args(internal_workspace_id="856"))
    assert code == AUTH_ERROR
    captured = capsys.readouterr()
    body = json.loads(captured.out)
    assert body["ok"] is False
    assert body["error_type"] == "INTERNAL_AUTH_REQUIRED"
    assert body["hint"] == "databricks auth login --profile p"
    assert "resume capture" in body["error"]
    assert "Traceback" not in captured.err
    assert "INTERNAL_AUTH_REQUIRED" in captured.err


# --- no_evidence / partial ----------------------------------------------------------


def _failing_engine(errors: list[str]) -> type:
    class _Engine:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        async def run(self, on_progress: Any = None) -> EngineResult:
            results = tuple(
                QueryResult(
                    query_id=f"C-B{i:02d}", domain="billing", data=None, error=e
                )
                for i, e in enumerate(errors)
            )
            pack = PackResult(pack_id="billing", domain="billing", results=results)
            return EngineResult(trace_id="t", pack_results=[pack])

    return _Engine


_DENIED = "PermissionDenied: User does not have USE SCHEMA on system.billing"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_all_permission_failures_is_no_evidence_auth_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "starboard.bootstrap.DiscoveryEngine", _failing_engine([_DENIED] * 21)
    )
    out_dir = tmp_path / "out"
    code = await _discover(_args(internal_workspace_id="856", out_dir=str(out_dir)))
    assert code == AUTH_ERROR
    captured = capsys.readouterr()
    body = json.loads(captured.out)
    assert body["ok"] is False
    assert body["data"]["status"] == "no_evidence"
    assert "none of the 21 scheduled queries succeeded" in body["error"]
    assert "permission" in body["error"]
    assert "NO_EVIDENCE" in captured.err
    # The layout is still written so the host can read what failed.
    assert (out_dir / "manifest.json").is_file()
    assert json.loads((out_dir / "discovery.json").read_text())["ok"] is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mixed_failures_is_no_evidence_general_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "starboard.bootstrap.DiscoveryEngine",
        _failing_engine([_DENIED, "PARSE_SYNTAX_ERROR"]),
    )
    code = await _discover(_args(internal_workspace_id="856"))
    assert code == GENERAL_ERROR
    body = json.loads(capsys.readouterr().out)
    assert body["data"]["status"] == "no_evidence"
    assert body["ok"] is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_partial_run_exits_zero_with_status_partial(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = await _discover(_args(internal_workspace_id="856"))
    assert code == 0
    body = json.loads(capsys.readouterr().out)
    assert body["ok"] is True
    assert body["data"]["status"] == "partial"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_summary_stdout_carries_no_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "starboard.bootstrap.DiscoveryEngine", _failing_engine([_DENIED] * 3)
    )
    code = await _discover(
        _args(
            internal_workspace_id="856",
            out_dir=str(tmp_path / "out"),
            stdout_mode="summary",
        )
    )
    assert code == AUTH_ERROR
    body = json.loads(capsys.readouterr().out)
    assert body["ok"] is False
    assert body["data"]["status"] == "no_evidence"
    assert "error" in body


@pytest.mark.unit
@pytest.mark.asyncio
async def test_covered_run_payload_carries_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, folder = drive_run()
    covered_env(monkeypatch, tmp_path, store, cli_main)
    monkeypatch.setattr(
        "starboard.bootstrap.DiscoveryEngine", _failing_engine([_DENIED] * 2)
    )
    code = await _discover(_args(run_folder=folder, json=False))
    assert code == AUTH_ERROR
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["status"] == "no_evidence"


@pytest.mark.unit
def test_discovery_status_buckets() -> None:
    assert cli_main._discovery_status({"total": 3, "succeeded": 3}) == "ok"
    assert (
        cli_main._discovery_status({"total": 3, "succeeded": 1, "failed": 2})
        == "partial"
    )
    assert (
        cli_main._discovery_status({"total": 3, "succeeded": 0, "failed": 3})
        == "no_evidence"
    )
    assert cli_main._discovery_status({"total": 0, "succeeded": 0}) == "ok"


# --- --warehouse-id ---------------------------------------------------------------


@pytest.mark.unit
def test_warehouse_id_flag_sets_databricks_warehouse_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli_main, "apply_cli_target", lambda *a, **k: None)
    args = cli_main.parse_args(["--discover", "--warehouse-id", "abc123"])
    assert args.warehouse_id == "abc123"
    cfg = cli_main.merge_env_config({}, args)
    assert cfg.databricks_warehouse_id == "abc123"


@pytest.mark.unit
def test_warehouse_access_error_exits_auth_with_candidates(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from starboard.exceptions import WarehouseAccessError

    class _DeniedClient(_Client):
        async def __aenter__(self) -> _Client:
            raise WarehouseAccessError(
                "wh-1",
                source="workspace default",
                reason="permission denied",
                candidates=("wh-2", "wh-3"),
            )

    monkeypatch.setattr(cli_main, "AsyncDatabricksClient", _DeniedClient)
    import asyncio

    code = asyncio.run(_discover(_args()))
    assert code == AUTH_ERROR
    captured = capsys.readouterr()
    body = json.loads(captured.out)
    assert body["error_type"] == "WAREHOUSE_PERMISSION_DENIED"
    assert body["warehouse_id"] == "wh-1"
    assert body["candidates"] == ["wh-2", "wh-3"]
    assert "--warehouse-id" in body["hint"]
    assert "Traceback" not in captured.err
