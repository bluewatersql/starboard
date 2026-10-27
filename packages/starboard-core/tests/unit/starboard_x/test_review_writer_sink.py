# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Phase-2 (P2-G3/G12): ``python -m starboard_x.review score --run-folder``.

Covered run against ``InMemoryEngagementStorage`` (canonical relpaths, evidence index,
empty sandbox diff, bounded stdout), refusal of local flags, and the public golden.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from starboard_core.engagement.evidence import record_evidence
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
from starboard_core.engagement.overlay import OverlaySignal
from starboard_core.engagement.policy import SourceMode, StoragePolicy
from starboard_core.engagement.publication import audience_gate
from starboard_core.engagement.records import EvidenceRef, ReportRevision
from starboard_core.engagement.sink import DriveRunSink, StorageUnavailableError
from starboard_core.engagement.write_guard import (
    active,
    sandbox_diff,
    sandbox_snapshot,
)
from starboard_x.review import __main__ as rv

from tests.unit.starboard_x._writer_support import (
    GOLDEN,
    RID,
    WS,
    covered_env,
    drive_run,
    local_run_dir,
    written,
)

STDOUT_BUDGET = 24_000
ROWS = json.loads((GOLDEN / "review_public" / "rows.json").read_text())


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
        rv.main(argv)
    except SystemExit as exc:
        code = int(exc.code or 0)
    out = capsys.readouterr().out
    return code, json.loads(out), out


def _sink_for(store: InMemoryEngagementStorage, folder_id: str) -> DriveRunSink:
    return DriveRunSink(
        store,
        folder_id,
        run_id=RID,
        access_fingerprint=store.inspect_access(folder_id).fingerprint,
    )


def _covered(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    store: InMemoryEngagementStorage,
) -> dict[str, Path]:
    sandbox = covered_env(monkeypatch, tmp_path, store)
    monkeypatch.setattr(rv, "detect_overlay", lambda **_kw: OverlaySignal(True, ("t",)))
    monkeypatch.setattr(rv, "load_engagement_storage", lambda: store)
    return sandbox


def _seed_rows(store: InMemoryEngagementStorage, folder: str, rows: Any = None) -> None:
    _sink_for(store, folder).put_json("raw/rows.json", ROWS if rows is None else rows)


@pytest.mark.unit
class TestPublicGolden:
    def test_score_stdout_unchanged(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(rv, "detect_overlay", lambda **_kw: OverlaySignal(False))
        rows = tmp_path / "rows.json"
        rows.write_text(json.dumps(ROWS))
        code, _, raw = _run_main(
            ["score", "--rows", str(rows), "--workspace", "acme"], capsys
        )
        assert code == 0
        assert raw == (GOLDEN / "review_public" / "score.stdout.json").read_text()

    @pytest.mark.parametrize("flag", ["--out", "--manifest-out"])
    def test_run_relative_outputs_need_a_run_folder(
        self, flag: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rows = tmp_path / "rows.json"
        rows.write_text(json.dumps(ROWS))
        code, env, _ = _run_main(["score", "--rows", str(rows), flag, "x.json"], capsys)
        assert code == 4
        assert "needs --run-folder" in env["error"]


@pytest.mark.unit
class TestOverlayGate:
    """On an overlay install ``score`` is a gated writer (D-11): no local run, no score."""

    def _rows_file(self, tmp_path: Path) -> Path:
        rows = tmp_path / "rows.json"
        rows.write_text(json.dumps(ROWS))
        return rows

    def test_overlay_without_run_folder_refused(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(rv, "detect_overlay", lambda **_kw: OverlaySignal(True, ("t",)))
        monkeypatch.setattr(
            rv, "_score", lambda *_a, **_k: pytest.fail("scored before the gate")
        )
        code, env, _ = _run_main(
            ["score", "--rows", str(self._rows_file(tmp_path))], capsys
        )
        assert code == 2, env
        assert env["error"].startswith("LOCAL_STORAGE_REFUSED"), env["error"]
        assert "--run-folder" in env["error"]
        assert env["data"] is None

    def test_internal_only_local_run_may_score_locally(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(rv, "detect_overlay", lambda **_kw: OverlaySignal(True, ("t",)))
        code, env, raw = _run_main(
            [
                "score", "--rows", str(self._rows_file(tmp_path)), "--workspace", "acme",
                "--run-dir", str(local_run_dir(tmp_path)),
            ],
            capsys,
        )
        assert code == 0, env
        assert raw == (GOLDEN / "review_public" / "score.stdout.json").read_text()

    @pytest.mark.parametrize(
        ("source_mode", "policy"),
        [
            (SourceMode.CUSTOMER_WORKSPACE, StoragePolicy.DRIVE_REQUIRED),
            (SourceMode.HYBRID, StoragePolicy.INTERNAL_ONLY_LOCAL),
            (SourceMode.INTERNAL_ONLY, StoragePolicy.DRIVE_DEFAULT),
        ],
    )
    def test_a_run_dir_that_is_not_internal_only_local_is_refused(
        self,
        source_mode: SourceMode,
        policy: StoragePolicy,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(rv, "detect_overlay", lambda **_kw: OverlaySignal(True, ("t",)))
        run_dir = local_run_dir(tmp_path, source_mode=source_mode, storage_policy=policy)
        code, env, _ = _run_main(
            ["score", "--rows", str(self._rows_file(tmp_path)), "--run-dir", str(run_dir)],
            capsys,
        )
        assert code == 2, env
        assert env["error"].startswith("LOCAL_STORAGE_REFUSED")

    def test_run_dir_without_a_descriptor_is_refused(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(rv, "detect_overlay", lambda **_kw: OverlaySignal(True, ("t",)))
        empty = tmp_path / "empty"
        empty.mkdir()
        code, env, _ = _run_main(
            ["score", "--rows", str(self._rows_file(tmp_path)), "--run-dir", str(empty)],
            capsys,
        )
        assert code == 2, env
        assert env["error"].startswith("LOCAL_STORAGE_REFUSED")

    def test_run_dir_with_run_folder_is_refused_when_covered(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run()
        _covered(monkeypatch, tmp_path, store)
        _seed_rows(store, folder)
        code, env, _ = _run_main(
            [
                "score", "--run-folder", folder, "--rows", "raw/rows.json",
                "--run-dir", str(tmp_path),
            ],
            capsys,
        )
        assert code == 2, env
        assert "--run-dir" in env["error"]
        assert "analysis/review.json" not in _sink_for(store, folder).list()


@pytest.mark.unit
class TestCoveredRun:
    def test_canonical_relpaths_evidence_empty_sandbox_diff_bounded_stdout(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run()
        sandbox = _covered(monkeypatch, tmp_path, store)
        _seed_rows(store, folder)
        before = sandbox_snapshot(list(sandbox.values()))

        code, env, raw = _run_main(
            ["score", "--run-folder", folder, "--rows", "raw/rows.json", "--workspace", "acme"],
            capsys,
        )

        assert code == 0, env["error"]
        assert sandbox_diff(before, sandbox_snapshot(list(sandbox.values()))) == []
        assert len(raw.encode()) <= STDOUT_BUDGET
        assert raw.count("\n") == 1  # compact JSON: covered runs print no indent
        sink = _sink_for(store, folder)
        assert written(sink) == {
            "raw/rows.json",
            "analysis/review.json",
            "analysis/review.md",
            "findings-manifest.json",
            "evidence/index.json",
        }
        # Same review as the public path, now in Drive.
        public = json.loads((GOLDEN / "review_public" / "score.stdout.json").read_text())
        assert json.loads(sink.get_bytes("analysis/review.json")) == public["data"]
        manifest = json.loads(sink.get_bytes("findings-manifest.json"))
        assert manifest["snapshot_version"] == "2.0"
        assert manifest["finding_count"] == public["data"]["finding_count"]
        md = sink.get_bytes("analysis/review.md").decode()
        assert md.startswith("# Workload Review")
        assert "warehouse_auto_stop_disabled::wh-idle" not in md  # summaries, not ids
        assert "W-W02[0]" in md

        data = env["data"]
        assert data["run_id"] == RID
        assert data["run_folder_id"] == folder
        assert {r["path"] for r in data["refs"]} == {
            "analysis/review.json",
            "analysis/review.md",
            "findings-manifest.json",
            "evidence/index.json",
        }
        assert data["counts"]["findings"] == public["data"]["finding_count"]
        assert "idle_running_hours" not in raw  # evidence rows stay in Drive

        evidence = [
            EvidenceRef.from_dict(d)
            for d in json.loads(sink.get_bytes("evidence/index.json"))
        ]
        assert {e.storage_ref.path for e in evidence} == {
            "analysis/review.json",
            "analysis/review.md",
            "findings-manifest.json",
        }
        assert all(e.run_id == RID and e.scope_workspace_ids == (WS,) for e in evidence)
        assert all(e.source_kind == "customer_workspace" for e in evidence)

    def test_out_and_manifest_out_are_run_relative(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run()
        _covered(monkeypatch, tmp_path, store)
        _seed_rows(store, folder)
        code, env, _ = _run_main(
            [
                "score", "--run-folder", folder, "--rows", "raw/rows.json",
                "--out", "analysis/review-jobs.json",
                "--manifest-out", "manifests/findings.json",
            ],
            capsys,
        )
        assert code == 0, env["error"]
        listed = written(_sink_for(store, folder))
        assert "analysis/review-jobs.json" in listed
        assert "analysis/review-jobs.md" in listed
        assert "manifests/findings.json" in listed

    def test_rows_from_a_drive_object_outside_the_run(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run()
        _covered(monkeypatch, tmp_path, store)
        other = store.create_folder(store.root_folder_id(), "other", {})
        obj = store.put_stream(
            other.id, "rows.json", "application/json", [json.dumps(ROWS).encode()],
            properties={},
        )
        code, env, _ = _run_main(
            ["score", "--run-folder", folder, "--rows", f"drive:{obj.id}"], capsys
        )
        assert code == 0, env["error"]
        assert _sink_for(store, folder).exists("analysis/review.json")

    def test_many_findings_stay_within_budget(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run()
        _covered(monkeypatch, tmp_path, store)
        rows = {
            "W-W02": [
                {
                    "warehouse_id": f"wh-{i}-" + "x" * 80,
                    "idle_running_hours": 12.0 + i,
                    "auto_stop_waste_pct": 80.0,
                }
                for i in range(400)
            ]
        }
        _seed_rows(store, folder, rows)
        code, env, raw = _run_main(
            ["score", "--run-folder", folder, "--rows", "raw/rows.json"], capsys
        )
        assert code == 0, env["error"]
        assert len(raw.encode()) <= STDOUT_BUDGET
        assert env["data"]["counts"]["findings"] > 0

    def test_missing_rows_is_an_arg_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run()
        _covered(monkeypatch, tmp_path, store)
        code, env, _ = _run_main(
            ["score", "--run-folder", folder, "--rows", "raw/nope.json"], capsys
        )
        assert code == 4
        assert "not in the run folder" in env["error"]
        assert "analysis/review.json" not in _sink_for(store, folder).list()

    def test_rows_relpath_over_the_cap_is_refused_before_download(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run()
        _covered(monkeypatch, tmp_path, store)
        _seed_rows(store, folder)
        target = _sink_for(store, folder)._lookup("raw/rows.json")
        assert target is not None
        monkeypatch.setattr(rv, "_MAX_ROWS_BYTES", 16)
        real_stream = store.get_stream
        monkeypatch.setattr(
            store,
            "get_stream",
            lambda oid, *a, **k: (
                pytest.fail("downloaded") if oid == target.id else real_stream(oid, *a, **k)
            ),
        )
        code, env, _ = _run_main(
            ["score", "--run-folder", folder, "--rows", "raw/rows.json"], capsys
        )
        assert code == 4
        assert "--rows" in env["error"] and "larger than 16 bytes" in env["error"]

    def test_public_install_with_run_folder_writes_drive_without_guard(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run()
        monkeypatch.setattr(rv, "detect_overlay", lambda **_kw: OverlaySignal(False))
        monkeypatch.setattr(rv, "load_engagement_storage", lambda: store)
        _seed_rows(store, folder)
        code, env, _ = _run_main(
            ["score", "--run-folder", folder, "--rows", "raw/rows.json"], capsys
        )
        assert code == 0, env["error"]
        assert _sink_for(store, folder).exists("analysis/review.json")


@pytest.mark.unit
class TestCoveredRefusals:
    @pytest.mark.parametrize(
        ("extra", "flag"),
        [
            (["--rows", "/tmp/rows.json"], "--rows"),
            (["--rows", "../rows.json"], "--rows"),
            (["--rows", "raw/rows.json", "--out", "/tmp/review.json"], "--out"),
            (["--rows", "raw/rows.json", "--manifest-out", "../m.json"], "--manifest-out"),
        ],
    )
    def test_local_paths_refused_with_nothing_written(
        self,
        extra: list[str],
        flag: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run()
        sandbox = _covered(monkeypatch, tmp_path, store)
        _seed_rows(store, folder)
        before = sandbox_snapshot(list(sandbox.values()))
        code, env, _ = _run_main(["score", "--run-folder", folder, *extra], capsys)
        assert code == 2, env
        assert env["error"].startswith("LOCAL_STORAGE_REFUSED"), env["error"]
        assert flag in env["error"]
        assert "analysis/review.json" not in _sink_for(store, folder).list()
        assert sandbox_diff(before, sandbox_snapshot(list(sandbox.values()))) == []

    def test_missing_storage_adapter_fails_closed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run()
        _covered(monkeypatch, tmp_path, store)

        def missing() -> Any:
            raise StorageUnavailableError("no adapter installed")

        monkeypatch.setattr(rv, "load_engagement_storage", missing)
        code, env, _ = _run_main(
            ["score", "--run-folder", folder, "--rows", "raw/rows.json"], capsys
        )
        assert code == 2, env
        assert env["error"].startswith("STORAGE_UNAVAILABLE")

    def test_invalid_run_folder_is_an_arg_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store = InMemoryEngagementStorage()
        empty = store.create_folder(store.root_folder_id(), "empty", {})
        _covered(monkeypatch, tmp_path, store)
        code, env, _ = _run_main(
            ["score", "--run-folder", empty.id, "--rows", "raw/rows.json"], capsys
        )
        assert code == 4, env
        assert "--run-folder" in env["error"]


def _review_evidence(store: InMemoryEngagementStorage, folder: str) -> list[EvidenceRef]:
    sink = _sink_for(store, folder)
    return [
        e
        for e in (
            EvidenceRef.from_dict(d)
            for d in json.loads(sink.get_bytes("evidence/index.json"))
        )
        if e.producer.startswith("review:")
    ]


@pytest.mark.unit
class TestReviewAudience:
    """arch H4: the review's audience comes from its rows, the most restrictive winning."""

    def _seed_indexed(
        self, store: InMemoryEngagementStorage, folder: str, source_kind: str
    ) -> None:
        sink = _sink_for(store, folder)
        ref = sink.put_json("raw/rows.json", ROWS)
        record_evidence(
            sink, [(ref, "discovery:rows", None, False)], source_kind=source_kind,
            scope=(WS,), method_version="m1",
        )

    def _score(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        store: InMemoryEngagementStorage,
        folder: str,
    ) -> list[EvidenceRef]:
        _covered(monkeypatch, tmp_path, store)
        code, env, _ = _run_main(
            ["score", "--run-folder", folder, "--rows", "raw/rows.json"], capsys
        )
        assert code == 0, env["error"]
        evidence = _review_evidence(store, folder)
        assert len(evidence) == 3
        return evidence

    def test_hybrid_run_over_internal_mirror_rows_is_internal_only(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run(source_mode=SourceMode.HYBRID)
        self._seed_indexed(store, folder, "internal_mirror")
        evidence = self._score(tmp_path, monkeypatch, capsys, store, folder)
        assert {(e.source_kind, e.audience_class) for e in evidence} == {
            ("internal_mirror", "internal_only")
        }
        report = ReportRevision(
            report_id="rpt_1",
            revision=1,
            audience="customer",
            object_ref=evidence[0].storage_ref,
            cited_evidence_ids=tuple(e.evidence_id for e in evidence),
            cited_observation_ids=(),
            derived_from=None,
            state="draft",
            blocked_reasons=(),
            created_at="2026-10-08T09:00:00+00:00",
        )
        state, _ = audience_gate(
            report,
            {e.evidence_id: e for e in evidence},
            {},
            source_mode=SourceMode.CUSTOMER_WORKSPACE,
            source_revision=None,
        )
        assert state == "blocked_audience"

    def test_hybrid_run_over_pure_customer_rows_is_customer_workspace(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run(source_mode=SourceMode.HYBRID)
        self._seed_indexed(store, folder, "customer_workspace")
        evidence = self._score(tmp_path, monkeypatch, capsys, store, folder)
        assert {(e.source_kind, e.audience_class) for e in evidence} == {
            ("customer_workspace", "customer_shareable")
        }

    def test_hybrid_run_over_unindexed_rows_is_internal(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run(source_mode=SourceMode.HYBRID)
        _seed_rows(store, folder)
        evidence = self._score(tmp_path, monkeypatch, capsys, store, folder)
        assert {e.audience_class for e in evidence} == {"internal_only"}

    def test_internal_rows_payload_on_a_customer_run_is_internal(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run()
        _seed_rows(store, folder, {"source": "internal", "rows_by_query_id": ROWS})
        evidence = self._score(tmp_path, monkeypatch, capsys, store, folder)
        assert {e.source_kind for e in evidence} == {"internal_mirror"}

    def test_render_markdown_is_public(self) -> None:
        assert rv.render_markdown({"findings": []}).startswith("# Workload Review")
