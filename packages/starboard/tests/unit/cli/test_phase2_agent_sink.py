# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Phase 2 (P2-G1/G3/G12): the goal agent on an overlay install / ``--run-folder``.

* ``--run-folder``: results go to ``analysis/agent/<ts>_<goal>.{json,md}`` in the
  run (EvidenceRefs appended), stdout is one bounded compact JSON line, the write
  guard is armed while the agent runs, the sandbox is untouched.
* ``--input-file`` on a run is a run-relative path or ``drive:<id>``.
* Overlay install: ``--log-file`` / ``--session`` / ``--session-db``,
  ``--output-path`` without ``--run-folder`` and a local ``--input-file`` without
  ``--run-folder`` (W30; ``drive:<id>`` is read in memory) are refused (exit 2) before logging or
  the agent start; ``--chat`` keeps sessions in memory; the guard is armed.
* Public install without ``--run-folder``: no guard, local ``--output-path`` as before.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from starboard.cli.cli import main as cli_main
from starboard.cli.cli.exit_codes import AUTH_ERROR, STORAGE_FAILURE, USAGE_ERROR
from starboard_core.engagement import sink as engagement_sink
from starboard_core.engagement.evidence import record_evidence
from starboard_core.engagement.policy import LOCAL_FILE_INTAKE_GUIDANCE, SourceMode
from starboard_core.engagement.write_guard import LocalWriteRefused, active
from starboard_x.cli import RefusedError, StorageFailureError
from starboard_x.contract import AuthError as IntakeAuthError

from tests.unit.cli._engagement_support import (
    STDOUT_BUDGET,
    WS,
    covered_env,
    diff,
    drive_run,
    evidence,
    overlay_on,
    sink_for,
    snapshot,
    written,
)

OUTPUT: dict[str, Any] = {
    "user_goal": "Optimize warehouse spend",
    "steps_taken": 2,
    "tools_used": ["list_warehouses"],
    "tokens_used": 10,
    "cost_usd": 0.0,
    "duration_seconds": 0.1,
}


class _Agent:
    """Records what the fake agent saw (guard state, the user message)."""

    built = 0
    guard_active: bool | None = None
    message: str | None = None


@pytest.fixture(autouse=True)
def _restore_logging() -> Any:
    """The CLI pins structlog/stdlib logging to the (captured) stderr; undo it."""
    import logging

    import structlog

    saved = structlog.get_config()
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    structlog.configure(**saved)
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.fixture(autouse=True)
def _fake_agent(monkeypatch: pytest.MonkeyPatch) -> Any:
    _Agent.built = 0
    _Agent.guard_active = None
    _Agent.message = None
    config = SimpleNamespace(
        offline_mode=False,
        _auth_resolvable=lambda: True,
        llm_api_key="sk-test-0123456789",
        llm_model="test-model",
        llm_max_tokens=1000,
        domain_model_overrides=None,
        redis_url=None,
    )
    monkeypatch.setattr(cli_main, "merge_env_config", lambda *a, **k: config)

    async def create(*_a: object, **_k: object) -> tuple[object, None]:
        _Agent.built += 1
        return object(), None

    async def stream(**kwargs: Any) -> tuple[dict[str, Any], str]:
        _Agent.guard_active = active()
        _Agent.message = kwargs["user_message"]
        return dict(OUTPUT), "# Report"

    monkeypatch.setattr(cli_main, "create_agent_manager", create)
    monkeypatch.setattr(cli_main, "handle_streaming_events", stream)
    assert not active()
    yield config
    assert not active()


async def _run(argv: list[str]) -> int:
    try:
        await cli_main.async_main(cli_main.parse_args(argv))
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_folder_writes_results_to_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, folder = drive_run()
    sandbox = covered_env(monkeypatch, tmp_path, store, cli_main)
    before = snapshot(sandbox)

    code = await _run(["--goal", "Optimize warehouse spend", "--run-folder", folder])

    out = capsys.readouterr().out
    assert code == 0, out
    assert _Agent.guard_active is True
    assert len(out.encode()) <= STDOUT_BUDGET
    assert out.count("\n") == 1
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["run_folder_id"] == folder
    json_rel = payload["summary"]["json_path"]
    md_rel = payload["summary"]["markdown_path"]
    assert json_rel.startswith("analysis/agent/")
    assert json_rel.endswith("_Optimize.json")
    assert md_rel == json_rel[: -len(".json")] + ".md"
    sink = sink_for(store, folder)
    assert written(sink) == {json_rel, md_rel, "evidence/index.json"}
    assert json.loads(sink.get_bytes(json_rel))["user_goal"] == OUTPUT["user_goal"]
    assert sink.get_bytes(md_rel)
    refs = evidence(sink)
    assert {r.storage_ref.path for r in refs} == {json_rel, md_rel}
    for ref in refs:
        assert ref.producer == f"agent:{ref.storage_ref.path}"
        assert ref.scope_workspace_ids == (WS,)
        assert ref.source_kind == "customer_workspace"
    assert diff(sandbox, before) == []


def _agent_kinds(store: Any, folder: str) -> set[tuple[str, str]]:
    return {
        (r.source_kind, r.audience_class)
        for r in evidence(sink_for(store, folder))
        if r.producer.startswith("agent:")
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_hybrid_run_results_are_internal_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """arch H4: the audience comes from the data, not a hard-coded customer label."""
    store, folder = drive_run(source_mode=SourceMode.HYBRID)
    covered_env(monkeypatch, tmp_path, store, cli_main)

    code = await _run(["--goal", "Optimize warehouse spend", "--run-folder", folder])

    assert code == 0, capsys.readouterr().out
    assert _agent_kinds(store, folder) == {("internal_mirror", "internal_only")}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_internal_input_file_makes_results_internal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An --input-file recorded as internal evidence wins over the customer run."""
    store, folder = drive_run()
    covered_env(monkeypatch, tmp_path, store, cli_main)
    sink = sink_for(store, folder)
    ref = sink.put_bytes("raw/w-w01.json", b"[]", "application/json")
    record_evidence(
        sink,
        [(ref, "discovery:w-w01", 0, False)],
        source_kind="internal_mirror",
        scope=(WS,),
        method_version="m1",
    )

    code = await _run(
        ["--goal", "Tune", "--run-folder", folder, "--input-file", "raw/w-w01.json"]
    )

    assert code == 0, capsys.readouterr().out
    assert _agent_kinds(store, folder) == {("internal_mirror", "internal_only")}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_folder_output_path_and_input_file_are_run_relative(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, folder = drive_run()
    sandbox = covered_env(monkeypatch, tmp_path, store, cli_main)
    sink = sink_for(store, folder)
    ref = sink.put_bytes("inputs/query.sql", b"SELECT 1", "text/plain")
    before = snapshot(sandbox)

    code = await _run(
        [
            "--goal",
            "Tune",
            "--run-folder",
            folder,
            "--output-path",
            "analysis/tune",
            "--input-file",
            "inputs/query.sql",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["json_path"].startswith("analysis/tune/")
    assert _Agent.message is not None
    assert "SELECT 1" in _Agent.message

    code = await _run(
        [
            "--goal",
            "Tune",
            "--run-folder",
            folder,
            "--input-file",
            f"drive:{ref.object_id}",
        ]
    )

    assert code == 0
    assert "SELECT 1" in (_Agent.message or "")
    capsys.readouterr()
    assert diff(sandbox, before) == []


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("extra", "flag"),
    [
        (["--log-file", "agent.log"], "--log-file"),
        (["--session", "s1"], "--session"),
        (["--session-db", "s.db"], "--session-db"),
        (["--output-path", "out"], "--output-path"),
        (["--run-folder", "RUN", "--output-path", "/tmp/out"], "--output-path"),
        (["--run-folder", "RUN", "--input-file", "/etc/hosts"], "--input-file"),
    ],
)
async def test_overlay_refuses_local_state_flags(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    extra: list[str],
    flag: str,
) -> None:
    store, folder = drive_run()
    sandbox = covered_env(monkeypatch, tmp_path, store, cli_main)
    extra = [folder if v == "RUN" else v for v in extra]
    before = snapshot(sandbox)

    code = await _run(["--goal", "Tune", "--json", *extra])

    assert code == 2
    env = json.loads(capsys.readouterr().out)
    assert env["error_type"] == "LOCAL_STORAGE_REFUSED"
    assert flag in env["error"]
    assert _Agent.built == 0
    assert written(sink_for(store, folder)) == set()
    assert diff(sandbox, before) == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_overlay_refuses_local_input_file_without_run_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """W30: a local customer file is refused on an overlay install (share via Drive)."""
    store, _folder = drive_run()
    sandbox = covered_env(monkeypatch, tmp_path, store, cli_main)
    local = sandbox["cwd"] / "query.sql"
    local.write_text("SELECT 1")
    before = snapshot(sandbox)

    code = await _run(["--goal", "Tune", "--json", "--input-file", str(local)])

    assert code == 2
    env = json.loads(capsys.readouterr().out)
    assert env["error_type"] == "LOCAL_FILE_INTAKE_REFUSED"
    assert env["error"].startswith("LOCAL_FILE_INTAKE_REFUSED: --input-file ")
    assert LOCAL_FILE_INTAKE_GUIDANCE in env["error"]
    assert _Agent.built == 0
    assert diff(sandbox, before) == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_overlay_reads_drive_input_file_without_run_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """W30: ``--input-file drive:<id>`` is read in memory, nothing written locally."""
    store, _folder = drive_run()
    sandbox = covered_env(monkeypatch, tmp_path, store, cli_main)
    monkeypatch.setattr(engagement_sink, "load_engagement_storage", lambda: store)
    obj = store.put_stream(
        store.root_folder_id(), "query.sql", "text/plain", [b"SELECT 1"], properties={}
    )
    before = snapshot(sandbox)

    code = await _run(["--goal", "Tune", "--input-file", f"drive:{obj.id}"])

    capsys.readouterr()
    assert code == 0
    assert "SELECT 1" in (_Agent.message or "")
    assert diff(sandbox, before) == []

    code = await _run(["--goal", "Tune", "--input-file", "drive:missing"])

    assert code == 3  # CONFIG_ERROR, as for a missing local file
    assert "not found" in capsys.readouterr().err
    assert diff(sandbox, before) == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_overlay_discover_refuses_log_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, folder = drive_run()
    sandbox = covered_env(monkeypatch, tmp_path, store, cli_main)
    before = snapshot(sandbox)

    code = await _run(
        ["--discover", "--run-folder", folder, "--log-file", "discover.log"]
    )

    assert code == 2
    assert "--log-file" in json.loads(capsys.readouterr().out)["error"]
    assert diff(sandbox, before) == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_overlay_without_run_folder_runs_guarded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    _fake_agent: Any,
) -> None:
    store, _ = drive_run()
    sandbox = covered_env(monkeypatch, tmp_path, store, cli_main)
    monkeypatch.setenv("REDIS_URL", "redis://cache:6379/0")
    _fake_agent.redis_url = "redis://cache:6379/0"
    before = snapshot(sandbox)

    code = await _run(["--goal", "Tune", "--json"])

    assert code == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["ok"] is True
    assert _Agent.guard_active is True
    assert _fake_agent.redis_url is None
    assert "Redis is disabled" in captured.err
    assert diff(sandbox, before) == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_overlay_without_run_folder_json_is_compact_and_bounded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, _ = drive_run()
    covered_env(monkeypatch, tmp_path, store, cli_main)

    async def stream(**_kwargs: Any) -> tuple[dict[str, Any], str]:
        return {**OUTPUT, "rows": ["x" * 200] * 5000}, "# Report\n" + "y" * 500_000

    monkeypatch.setattr(cli_main, "handle_streaming_events", stream)

    code = await _run(["--goal", "Tune", "--json"])

    assert code == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    assert len(out.encode()) <= STDOUT_BUDGET + 1
    assert json.loads(out)["ok"] is True


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("as_json", [True, False])
async def test_overlay_swallowed_local_write_fails_the_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    as_json: bool,
) -> None:
    store, _ = drive_run()
    sandbox = covered_env(monkeypatch, tmp_path, store, cli_main)

    async def stream(**_kwargs: Any) -> tuple[dict[str, Any], str]:
        # a tool that treats the refusal as best-effort
        with contextlib.suppress(OSError):
            (sandbox["cwd"] / "leak.json").write_text("{}")
        return dict(OUTPUT), "# Report"

    monkeypatch.setattr(cli_main, "handle_streaming_events", stream)
    before = snapshot(sandbox)

    with pytest.raises(LocalWriteRefused):  # main() maps it to exit 2
        await _run(["--goal", "Tune", *(["--json"] if as_json else [])])

    assert '"ok": true' not in capsys.readouterr().out
    assert not (sandbox["cwd"] / "leak.json").exists()
    assert diff(sandbox, before) == []


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("quiet", [True, False])
async def test_overlay_refusal_is_checked_before_the_markdown_is_printed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    quiet: bool,
) -> None:
    """A run whose local write was refused prints no report to stdout."""
    store, _ = drive_run()
    sandbox = covered_env(monkeypatch, tmp_path, store, cli_main)

    async def stream(**_kwargs: Any) -> tuple[dict[str, Any], str]:
        with contextlib.suppress(OSError):
            (sandbox["cwd"] / "leak.json").write_text("{}")
        return dict(OUTPUT), "# Report SENTINEL"

    monkeypatch.setattr(cli_main, "handle_streaming_events", stream)

    with pytest.raises(LocalWriteRefused):
        await _run(["--goal", "Tune", *(["--quiet"] if quiet else [])])

    captured = capsys.readouterr()
    assert "SENTINEL" not in captured.out
    assert "SENTINEL" not in captured.err


@pytest.mark.unit
@pytest.mark.asyncio
async def test_overlay_chat_sessions_stay_in_memory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store, _ = drive_run()
    sandbox = covered_env(monkeypatch, tmp_path, store, cli_main)
    seen: dict[str, Any] = {}

    async def chat(**kwargs: Any) -> None:
        seen["db_path"] = kwargs["session_mgr"]._db_path
        seen["guard"] = active()

    monkeypatch.setattr("starboard.cli.cli.chat.run_interactive_chat", chat)
    before = snapshot(sandbox)

    code = await _run(["--chat"])

    assert code == 0
    assert seen == {"db_path": ":memory:", "guard": True}
    assert diff(sandbox, before) == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_public_install_keeps_local_output_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_dir = tmp_path / "results"

    code = await _run(["--goal", "Tune", "--output-path", str(out_dir)])

    assert code == 0
    assert _Agent.guard_active is False
    assert "# Report" in capsys.readouterr().out
    names = sorted(p.suffix for p in out_dir.iterdir())
    assert names == [".json", ".md"]


@pytest.mark.unit
def test_main_maps_local_write_refused_to_exit_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def refused(_args: object) -> None:
        raise LocalWriteRefused("open", "/tmp/x")

    overlay_on(monkeypatch, cli_main)
    monkeypatch.setattr(cli_main, "async_main", refused)

    with pytest.raises(SystemExit) as exc:
        cli_main.main(["--goal", "Tune"])

    assert exc.value.code == 2
    assert "LOCAL_STORAGE_REFUSED" in capsys.readouterr().err


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (StorageFailureError("STORAGE_INTEGRITY: md5 mismatch"), STORAGE_FAILURE),
        (RefusedError("LOCAL_FILE_INTAKE_REFUSED: no"), USAGE_ERROR),
        (IntakeAuthError("no credentials"), AUTH_ERROR),
    ],
)
async def test_drive_input_file_failure_exit_codes_do_not_collide(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
    expected: int,
) -> None:
    """A Drive intake storage failure exits STORAGE_FAILURE, never AUTH_ERROR's 4."""

    def fail(*_a: object, **_k: object) -> str:
        raise error

    monkeypatch.setattr(cli_main, "read_intake_text", fail)
    code = await _run(["--goal", "Tune", "--input-file", "drive:abc"])
    assert code == expected, capsys.readouterr()
