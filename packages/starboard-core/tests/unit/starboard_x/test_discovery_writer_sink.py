# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Phase-2 (P2-G1/G3/G12, E6): ``starboard_x.discovery`` writes through an ArtifactSink.

* Public golden: the pre-change local bytes are unchanged (fixtures captured before
  the sink conversion).
* Covered run (overlay + ``--run-folder``) against ``InMemoryEngagementStorage``:
  canonical relpaths, evidence index, empty sandbox diff, bounded stdout.
* Refusal of every local flag on a covered run.
* The Drive form of the authorization loader.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
from starboard_core.engagement.overlay import OverlaySignal
from starboard_core.engagement.records import EvidenceRef
from starboard_core.engagement.sink import DriveRunSink, MemorySink
from starboard_core.engagement.write_guard import (
    active,
    sandbox_diff,
    sandbox_snapshot,
)
from starboard_x.contract import ArgError
from starboard_x.discovery import __main__ as disc
from starboard_x.discovery._authorization import (
    StorageRefusedError,
    load_authorized_workspace_ids_from_run_folder,
    resolve_run_folder_profile,
)
from starboard_x.discovery._serialize import write_result_files

from tests.unit.starboard_x._writer_support import (
    GOLDEN,
    OTHER_RID,
    RID,
    WS,
    Df,
    FakeEngine,
    _qr,
    covered_env,
    drive_run,
    fake_result,
    identity_record,
    written,
)

STDOUT_BUDGET = 24_000


@pytest.fixture(autouse=True)
def _no_guard_leak() -> Any:
    assert not active()
    yield
    assert not active()


def _run_main(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> tuple[int, dict[str, Any], str]:
    code = 0
    try:
        disc.main(argv)
    except SystemExit as exc:
        code = int(exc.code or 0)
    out = capsys.readouterr().out
    return code, json.loads(out), out


def _public(monkeypatch: pytest.MonkeyPatch, result: Any | None = None) -> None:
    monkeypatch.setattr(
        disc, "detect_overlay", lambda **_kw: OverlaySignal(enabled=False)
    )
    res = fake_result() if result is None else result
    monkeypatch.setattr(disc, "build_engine", lambda _args: FakeEngine(res))


def _covered(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    store: InMemoryEngagementStorage,
    result: Any | None = None,
) -> tuple[dict[str, Path], list[Any]]:
    sandbox = covered_env(monkeypatch, tmp_path, store)
    monkeypatch.setattr(disc, "detect_overlay", lambda **_kw: OverlaySignal(True, ("t",)))
    monkeypatch.setattr(disc, "load_engagement_storage", lambda: store)
    res = fake_result() if result is None else result
    seen: list[Any] = []

    def build(args: Any) -> FakeEngine:
        seen.append(args)
        return FakeEngine(res)

    monkeypatch.setattr(disc, "build_engine", build)
    return sandbox, seen


def _sink_for(store: InMemoryEngagementStorage, folder_id: str) -> DriveRunSink:
    return DriveRunSink(
        store,
        folder_id,
        run_id=RID,
        access_fingerprint=store.inspect_access(folder_id).fingerprint,
    )


def _evidence(sink: DriveRunSink) -> list[EvidenceRef]:
    return [EvidenceRef.from_dict(d) for d in json.loads(sink.get_bytes("evidence/index.json"))]


# --- public golden (bytes captured before the sink conversion) ------------------------


def _tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.unit
class TestPublicGolden:
    def test_write_result_files_local_bytes_unchanged(self, tmp_path: Path) -> None:
        out = tmp_path / "direct"
        ret = write_result_files(fake_result(), str(out))
        assert _tree(out) == _tree(GOLDEN / "discovery_public" / "direct")
        got = json.dumps(ret, indent=2, default=str).replace(str(out), "<OUT>")
        assert got == (GOLDEN / "discovery_public" / "direct.return.json").read_text()

    def test_cli_out_dir_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _public(monkeypatch)
        out = tmp_path / "outdir"
        code, _, raw = _run_main(["run", "--data-only", "--out-dir", str(out)], capsys)
        assert code == 0
        assert _tree(out) == _tree(GOLDEN / "discovery_public" / "out_dir")
        assert raw.replace(str(out), "<OUT>") == (
            GOLDEN / "discovery_public" / "out_dir.stdout.json"
        ).read_text()

    def test_cli_output_path_json_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _public(monkeypatch)
        target = tmp_path / "env" / "discovery.json"
        code, _, raw = _run_main(["run", "--data-only", "--output-path", str(target)], capsys)
        assert code == 0
        assert target.read_bytes() == (GOLDEN / "discovery_public" / "output_path.json").read_bytes()
        assert raw.replace(str(target), "<OUT>") == (
            GOLDEN / "discovery_public" / "output_path.stdout.json"
        ).read_text()

    def test_cli_default_stdout_envelope_unchanged(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _public(monkeypatch)
        code, _, raw = _run_main(["run", "--data-only"], capsys)
        assert code == 0
        assert raw == (GOLDEN / "discovery_public" / "no_flags.stdout.json").read_text()

    def test_public_stdout_flag_is_the_default(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _public(monkeypatch)
        code, _, raw = _run_main(["run", "--data-only", "--stdout"], capsys)
        assert code == 0
        assert raw == (GOLDEN / "discovery_public" / "no_flags.stdout.json").read_text()


# --- covered run -----------------------------------------------------------------------


@pytest.mark.unit
class TestCoveredRun:
    def test_canonical_relpaths_evidence_empty_sandbox_diff_bounded_stdout(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run()
        sandbox, seen = _covered(monkeypatch, tmp_path, store)
        before = sandbox_snapshot(list(sandbox.values()))

        code, env, raw = _run_main(["run", "--data-only", "--run-folder", folder], capsys)

        assert code == 0, env
        assert sandbox_diff(before, sandbox_snapshot(list(sandbox.values()))) == []
        assert len(raw.encode()) <= STDOUT_BUDGET
        assert raw.count("\n") == 1  # compact JSON: covered runs print no indent
        # The scope came from the Drive descriptor, not a local file.
        assert tuple(seen[0].authorized_workspace_ids) == (WS,)
        sink = _sink_for(store, folder)
        assert written(sink) == {
            "raw/billing.json",
            "raw/governance_uc.json",
            "facts.json",
            "manifest.json",
            "discovery.json",
            "evidence/index.json",
        }
        data = env["data"]
        assert data["run_id"] == RID
        assert data["run_folder_id"] == folder
        assert {r["path"] for r in data["refs"]} >= {"raw/billing.json", "discovery.json"}
        assert data["counts"] == {"packs": 2, "queries": 3, "succeeded": 2}
        assert "rows" not in raw.replace('"rows_total"', "")  # no row arrays on stdout
        # Bytes equal the public layout (same encoder, Drive instead of disk).
        golden = GOLDEN / "discovery_public" / "out_dir"
        for rel in ("raw/billing.json", "raw/governance_uc.json", "facts.json"):
            assert sink.get_bytes(rel) == (golden / rel).read_bytes()
        manifest = json.loads(sink.get_bytes("manifest.json"))
        assert "out_dir" not in manifest
        assert json.loads(sink.get_bytes("discovery.json"))["pack_count"] == 2

        evidence = _evidence(sink)
        assert {e.storage_ref.path for e in evidence} == {
            "raw/billing.json",
            "raw/governance_uc.json",
            "facts.json",
            "manifest.json",
            "discovery.json",
        }
        for e in evidence:
            assert e.run_id == RID
            assert e.scope_workspace_ids == (WS,)
            assert e.source_kind == "customer_workspace"
            assert e.audience_class == "customer_shareable"
            assert e.producer.startswith("discovery:")
        by_path = {e.storage_ref.path: e for e in evidence}
        assert by_path["raw/billing.json"].row_count == 1
        assert by_path["raw/governance_uc.json"].row_count == 2
        # The index is the one object that covers every other write (read-back identity;
        # stdout refs are compact: path, object_id, size).
        stdout_ref = next(r for r in data["refs"] if r["path"] == "raw/billing.json")
        assert by_path["raw/billing.json"].storage_ref.object_id == stdout_ref["object_id"]
        assert by_path["raw/billing.json"].storage_ref.size == stdout_ref["size"]

    def test_oversized_envelope_stays_within_budget(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        packs = []
        for i in range(120):
            qr = SimpleNamespace(
                query_id=f"Q-{i}",
                domain="d",
                data=Df([{"x": n, "y": "v" * 40} for n in range(30)]),
                error=None,
                row_count=30,
                succeeded=True,
                skipped=False,
                result_limit=None,
            )
            packs.append(SimpleNamespace(pack_id=f"pack-{i}", domain="d", results=[qr]))
        big = SimpleNamespace(
            trace_id="t", elapsed_ms=1.0, errors=["e" * 300] * 80, audit_result=None,
            pack_results=packs, domain_analyses=[],
        )
        store, folder = drive_run()
        _covered(monkeypatch, tmp_path, store, big)

        code, env, raw = _run_main(["run", "--run-folder", folder], capsys)

        assert code == 0, env
        assert len(raw.encode()) <= STDOUT_BUDGET
        assert env["data"]["run_folder_id"] == folder
        assert env["data"]["truncated"] is True
        # Everything is still in Drive.
        assert len(_sink_for(store, folder).list("raw/")) == 120

    def test_out_dir_and_output_path_are_run_relative(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run()
        _covered(monkeypatch, tmp_path, store)
        code, env, _ = _run_main(
            ["run", "--run-folder", folder, "--out-dir", "discovery/2026-10"], capsys
        )
        assert code == 0, env
        listed = written(_sink_for(store, folder))
        assert "discovery/2026-10/raw/billing.json" in listed
        assert "discovery/2026-10/facts.json" in listed
        assert "discovery/2026-10/manifest.json" in listed

        code, env, _ = _run_main(
            ["run", "--run-folder", folder, "--output-path", "env/discovery-acme.json"], capsys
        )
        assert code == 0, env
        sink = _sink_for(store, folder)
        assert sink.exists("env/discovery-acme.json")
        assert env["data"]["summary"]["envelope_path"] == "env/discovery-acme.json"
        assert any(
            e.storage_ref.path == "env/discovery-acme.json" for e in _evidence(sink)
        )

    def test_plan_is_gated_and_bounded(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run()
        _covered(monkeypatch, tmp_path, store)

        class PlanEngine:
            async def plan(self) -> Any:
                return SimpleNamespace(
                    selection=SimpleNamespace(
                        recommended=[], always_recommended=["a"], contextual=[]
                    ),
                    products={"JOBS": 5.0},
                    audit_succeeded=True,
                    trace_id="t",
                )

        monkeypatch.setattr(disc, "build_engine", lambda _a: PlanEngine())
        code, env, raw = _run_main(["plan", "--run-folder", folder], capsys)
        assert code == 0, env
        assert len(raw.encode()) <= STDOUT_BUDGET
        assert env["data"]["run_folder_id"] == folder
        assert env["data"]["summary"]["audit_succeeded"] is True

    def test_guard_is_armed_while_the_engine_runs(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run()
        sandbox, _ = _covered(monkeypatch, tmp_path, store)
        leak = sandbox["cwd"] / "leak.txt"

        class LeakyEngine:
            async def run(self) -> Any:
                assert active()
                leak.write_text("customer rows")
                return fake_result()

        monkeypatch.setattr(disc, "build_engine", lambda _a: LeakyEngine())
        code, env, _ = _run_main(["run", "--run-folder", folder], capsys)
        # The guard refuses the write and the run fails closed with the refusal code.
        _assert_refused(env, code, "LOCAL_STORAGE_REFUSED")
        assert not leak.exists()

    def test_public_install_with_run_folder_writes_drive_unbounded(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        store, folder = drive_run()
        _public(monkeypatch)
        monkeypatch.setattr(disc, "load_engagement_storage", lambda: store)
        code, env, _ = _run_main(["run", "--run-folder", folder], capsys)
        assert code == 0, env
        assert "raw/billing.json" in _sink_for(store, folder).list()
        assert env["data"]["run_folder_id"] == folder


# --- refusals --------------------------------------------------------------------------


def _assert_refused(env: dict[str, Any], code: int, text: str, flag: str | None = None) -> None:
    assert code == 2, env
    assert env["ok"] is False
    assert env["error"].startswith(text), env["error"]
    if flag:
        assert flag in env["error"], env["error"]


@pytest.mark.unit
class TestCoveredRefusals:
    @pytest.mark.parametrize(
        ("extra", "flag"),
        [
            (["--authorization", "/tmp/some-run"], "--authorization"),
            (["--stdout"], "--stdout"),
        ],
    )
    def test_local_flags_refused(
        self,
        extra: list[str],
        flag: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run()
        sandbox, seen = _covered(monkeypatch, tmp_path, store)
        before = sandbox_snapshot(list(sandbox.values()))
        code, env, _ = _run_main(["run", "--run-folder", folder, *extra], capsys)
        _assert_refused(env, code, "LOCAL_STORAGE_REFUSED", flag)
        assert seen == []  # refused before any engine was built
        assert written(_sink_for(store, folder)) == set()
        assert sandbox_diff(before, sandbox_snapshot(list(sandbox.values()))) == []

    @pytest.mark.parametrize(
        ("flag", "value"),
        [
            ("--out-dir", "/tmp/out"),
            ("--out-dir", "../escape"),
            ("--output-path", "/tmp/discovery.json"),
            ("--output-path", "~/discovery.json"),
        ],
    )
    def test_absolute_or_escaping_output_paths_refused(
        self,
        flag: str,
        value: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run()
        sandbox, _ = _covered(monkeypatch, tmp_path, store)
        code, env, _ = _run_main(["run", "--run-folder", folder, flag, value], capsys)
        _assert_refused(env, code, "LOCAL_STORAGE_REFUSED", flag)
        assert sandbox_diff({}, sandbox_snapshot(list(sandbox.values()))) == []

    @pytest.mark.parametrize("verb", ["run", "plan"])
    def test_overlay_without_run_folder_refused(
        self,
        verb: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, _ = drive_run()
        _, seen = _covered(monkeypatch, tmp_path, store)
        code, env, _ = _run_main([verb], capsys)
        _assert_refused(env, code, "LOCAL_STORAGE_REFUSED", "--run-folder")
        assert seen == []

    def test_local_authorization_dir_without_run_folder_refused(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, _ = drive_run()
        _, seen = _covered(monkeypatch, tmp_path, store)
        code, env, _ = _run_main(["run", "--authorization", str(tmp_path)], capsys)
        _assert_refused(env, code, "LOCAL_STORAGE_REFUSED", "--authorization")
        assert seen == []

    def test_missing_storage_adapter_fails_closed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from starboard_core.engagement.sink import StorageUnavailableError

        store, folder = drive_run()
        _, seen = _covered(monkeypatch, tmp_path, store)

        def missing() -> Any:
            raise StorageUnavailableError("no adapter installed")

        monkeypatch.setattr(disc, "load_engagement_storage", missing)
        code, env, _ = _run_main(["run", "--run-folder", folder], capsys)
        _assert_refused(env, code, "STORAGE_UNAVAILABLE")
        assert seen == []

    def test_unverified_identity_is_an_arg_error_not_a_run(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run(
            identity=identity_record(status="mismatch", reasons=["host differs"])
        )
        _, seen = _covered(monkeypatch, tmp_path, store)
        code, env, _ = _run_main(["run", "--run-folder", folder], capsys)
        assert code == 4, env
        assert "not 'verified'" in env["error"]
        assert seen == []
        assert written(_sink_for(store, folder)) == set()

    def test_overlay_install_no_longer_prints_the_local_authorization_hint(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, _ = drive_run()
        _covered(monkeypatch, tmp_path, store)
        _, env, _ = _run_main(["run"], capsys)
        assert "pass --run-folder" in env["error"]


# --- Drive authorization loader (defect E6) --------------------------------------------


@pytest.mark.unit
class TestRunFolderAuthorization:
    def test_verified_identity_in_the_run_folder(self) -> None:
        store, folder = drive_run()
        assert load_authorized_workspace_ids_from_run_folder(store, folder) == (WS,)

    def test_verified_identity_in_the_staging_folder(self) -> None:
        store, folder = drive_run(identity_in="staging")
        assert load_authorized_workspace_ids_from_run_folder(store, folder) == (WS,)

    def test_no_identity_check(self) -> None:
        store, folder = drive_run(identity=False)
        with pytest.raises(ArgError, match="identity check not found"):
            load_authorized_workspace_ids_from_run_folder(store, folder)

    def test_no_descriptor(self) -> None:
        store = InMemoryEngagementStorage()
        folder = store.create_folder(store.root_folder_id(), "empty", {})
        with pytest.raises(ArgError, match="run descriptor"):
            load_authorized_workspace_ids_from_run_folder(store, folder.id)

    def test_identity_not_verified(self) -> None:
        store, folder = drive_run(
            identity=identity_record(status="mismatch", reasons=["workspace differs"])
        )
        with pytest.raises(ArgError, match="not 'verified'.*workspace differs"):
            load_authorized_workspace_ids_from_run_folder(store, folder)

    def test_identity_for_another_run(self) -> None:
        store, folder = drive_run(identity=identity_record(run_id=OTHER_RID))
        with pytest.raises(ArgError, match="identity check is for run"):
            load_authorized_workspace_ids_from_run_folder(store, folder)

    def test_scope_is_not_the_verified_workspace(self) -> None:
        store, folder = drive_run(
            workspace_ids=("123", "456"),
            identity=identity_record(),
        )
        with pytest.raises(ArgError, match="exactly the verified workspace"):
            load_authorized_workspace_ids_from_run_folder(store, folder)

    def test_scope_for_another_workspace(self) -> None:
        store, folder = drive_run(
            workspace_ids=("999",),
            identity=identity_record(),
        )
        with pytest.raises(ArgError, match="exactly the verified workspace"):
            load_authorized_workspace_ids_from_run_folder(store, folder)

    def test_non_digit_scope(self) -> None:
        store, folder = drive_run(workspace_ids=("ws-1",))
        with pytest.raises(ArgError, match="digit strings"):
            load_authorized_workspace_ids_from_run_folder(store, folder)

    def test_corrupt_identity_check(self) -> None:
        store, folder = drive_run()
        analysis = store.list_children(folder, name="analysis")[0]
        ident = store.list_children(analysis.id, name="identity-check.json")[0]
        store.update_stream(ident.id, "application/json", [b"{not json"])
        with pytest.raises(ArgError, match="invalid identity check"):
            load_authorized_workspace_ids_from_run_folder(store, folder)

    def test_duplicate_identity_checks_are_a_conflict(self) -> None:
        store, folder = drive_run()
        analysis = store.list_children(folder, name="analysis")[0]
        store.put_stream(
            analysis.id, "identity-check.json", "application/json", [b"{}"], properties={}
        )
        with pytest.raises(ArgError, match="reconcile in Drive"):
            load_authorized_workspace_ids_from_run_folder(store, folder)

    def test_nothing_is_read_from_local_disk(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store, folder = drive_run()
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path))
        snap = sandbox_snapshot([tmp_path])
        assert load_authorized_workspace_ids_from_run_folder(store, folder) == (WS,)
        assert sandbox_diff(snap, sandbox_snapshot([tmp_path])) == []

    def test_exported(self) -> None:
        from starboard_x.discovery import _authorization

        assert "load_authorized_workspace_ids_from_run_folder" in _authorization.__all__


@pytest.mark.unit
def test_sink_dest_without_drive_writes_layout_but_no_evidence_index() -> None:
    sink = MemorySink(run_id=RID)
    out = write_result_files(fake_result(), sink, scope_workspace_ids=(WS,))
    assert not sink.exists("evidence/index.json")
    assert sink.exists("manifest.json") and sink.exists("discovery.json")
    assert {r["path"] for r in out["refs"]} == set(sink.list())


@pytest.mark.unit
def test_build_engine_without_a_scope_on_overlay_is_still_an_arg_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import argparse

    monkeypatch.setattr(disc, "detect_overlay", lambda **_kw: OverlaySignal(True, ("t",)))
    with pytest.raises(ArgError, match="--authorization is required"):
        disc.build_engine(argparse.Namespace(lookback_days=30, max_parallelism=4, packs=None))


# --- the run's verified profile ----------------------------------------------------------


@pytest.mark.unit
class TestRunFolderProfile:
    def test_resolve_defaults_to_the_verified_profile(self) -> None:
        store, folder = drive_run(basis="verified", workspace_profile="acme-ws")
        assert resolve_run_folder_profile(store, folder, None) == "acme-ws"
        assert resolve_run_folder_profile(store, folder, "acme-ws") == "acme-ws"

    def test_resolve_refuses_another_profile(self) -> None:
        store, folder = drive_run(basis="verified", workspace_profile="acme-ws")
        with pytest.raises(StorageRefusedError, match=r"^PROFILE_MISMATCH: .*'other'"):
            resolve_run_folder_profile(store, folder, "other")

    def test_resolve_refuses_host_on_a_profile_verified_run(self) -> None:
        store, folder = drive_run(basis="verified", workspace_profile="acme-ws")
        with pytest.raises(StorageRefusedError, match=r"^PROFILE_MISMATCH: .*drop --host"):
            resolve_run_folder_profile(store, folder, None, "https://x.example.com")

    def test_resolve_host_verified_run(self) -> None:
        store, folder = drive_run(basis="verified")
        assert resolve_run_folder_profile(store, folder, None, "https://x.example.com") is None
        with pytest.raises(StorageRefusedError, match="PROFILE_MISMATCH"):
            resolve_run_folder_profile(store, folder, "acme-ws")

    def test_resolve_unverified_scope_passes_through(self) -> None:
        store, folder = drive_run()
        assert resolve_run_folder_profile(store, folder, "any") == "any"
        assert resolve_run_folder_profile(store, folder, None) is None

    def test_cli_run_reads_as_the_verified_profile(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run(basis="verified", workspace_profile="acme-ws")
        _, seen = _covered(monkeypatch, tmp_path, store)
        code, env, _ = _run_main(["run", "--data-only", "--run-folder", folder], capsys)
        assert code == 0, env
        assert seen[0].profile == "acme-ws"

    def test_cli_run_refuses_another_profile_before_the_engine(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run(basis="verified", workspace_profile="acme-ws")
        _, seen = _covered(monkeypatch, tmp_path, store)
        code, env, _ = _run_main(
            ["run", "--data-only", "--run-folder", folder, "--profile", "other"], capsys
        )
        assert code == 2
        assert env["error"].startswith("PROFILE_MISMATCH")
        assert seen == []



# --- concurrent pack uploads (A4) ------------------------------------------------------


def _many_packs(n: int = 12) -> SimpleNamespace:
    """``fake_result()`` plus ``n`` extra one-query packs (enough to fill the pool)."""
    base = fake_result()
    extra = [
        SimpleNamespace(
            pack_id=f"pack-{i:02d}",
            domain="compute",
            results=[_qr(f"C-{i:02d}", "compute", [{"cluster_id": f"c{i}", "n": i}])],
        )
        for i in range(n)
    ]
    base.pack_results = [*base.pack_results, *extra]
    return base


def _layout(
    store: InMemoryEngagementStorage, folder: str, monkeypatch: pytest.MonkeyPatch, workers: int
) -> tuple[Any, ...]:
    from starboard_x.discovery import _serialize

    monkeypatch.setattr(_serialize, "_UPLOAD_WORKERS", workers)
    sink = _sink_for(store, folder)
    out = write_result_files(_many_packs(), sink, scope_workspace_ids=(WS,))
    index = [(e.storage_ref.path, e.storage_ref.md5, e.producer) for e in _evidence(sink)]
    # The index records provider object ids, which follow upload order: compare
    # its entries (above), not its bytes.
    refs = [(r["path"], r["md5"] if r["path"] != "evidence/index.json" else None)
            for r in out["refs"]]
    return out["manifest"], out["facts"], refs, index


@pytest.mark.unit
def test_concurrent_pack_uploads_match_the_serial_layout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    store, folder = drive_run()
    in_flight, peak, lock = 0, 0, threading.Lock()
    gate = threading.Barrier(2, timeout=5)
    real_put = store.put_stream

    def slow_put(*args: Any, **kwargs: Any) -> Any:
        nonlocal in_flight, peak
        with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        try:
            if args[1].startswith("pack-0"):
                gate.wait()  # two pack uploads must be in flight at once
            return real_put(*args, **kwargs)
        finally:
            with lock:
                in_flight -= 1

    monkeypatch.setattr(store, "put_stream", slow_put)
    parallel = _layout(store, folder, monkeypatch, workers=6)
    assert peak >= 2

    serial_store, serial_folder = drive_run()
    serial = _layout(serial_store, serial_folder, monkeypatch, workers=1)

    # Manifest, facts, refs and the evidence index are in pack order either way.
    assert parallel == serial
    paths = [p for p, _ in parallel[2]]
    assert paths.index("raw/billing.json") < paths.index("raw/pack-00.json")
    assert [p for p in paths if p.startswith("raw/pack-")] == [
        f"raw/pack-{i:02d}.json" for i in range(12)
    ]


@pytest.mark.unit
def test_a_failed_pack_upload_fails_the_write_with_its_own_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from starboard_core.ports.engagement_storage import StorageTransientError

    store, folder = drive_run()
    real_put = store.put_stream

    def failing_put(*args: Any, **kwargs: Any) -> Any:
        if args[1] == "pack-03.json":
            raise StorageTransientError("Drive upload failed: HTTP 503")
        return real_put(*args, **kwargs)

    monkeypatch.setattr(store, "put_stream", failing_put)
    with pytest.raises(StorageTransientError, match="HTTP 503"):
        _layout(store, folder, monkeypatch, workers=6)
    sink = _sink_for(store, folder)
    # The final layout is never written over a partial pack set.
    assert not sink.exists("manifest.json") and not sink.exists("evidence/index.json")
