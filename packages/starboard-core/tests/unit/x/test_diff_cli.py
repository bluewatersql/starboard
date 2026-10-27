# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""``python -m starboard_x.diff settings|metrics`` (D3-24).

Deterministic diffs of two JSON documents: ``settings`` (JSON-path adds, removes and
changes over two ``job fetch`` outputs) and ``metrics`` (per-key delta and unit over
two ``query fetch`` / ``diagnostic profile`` outputs, ``pp`` for a percentage). A REF
is ``drive:<object id>``, a local file on a public install, or a run-relative path
with ``--run-folder``. There is no ``text`` subcommand.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
from starboard_core.engagement.overlay import OverlaySignal
from starboard_core.engagement.sink import DriveRunSink
from starboard_core.engagement.write_guard import (
    active,
    sandbox_diff,
    sandbox_snapshot,
)
from starboard_x import _cli
from starboard_x.diff import __main__ as dx

from tests.unit.starboard_x._writer_support import (
    RID,
    covered_env,
    drive_run,
    written,
)

GOLDEN = Path(__file__).parent / "golden" / "diff"
STDOUT_BUDGET = 24_000


@pytest.fixture(autouse=True)
def _no_guard_leak() -> Any:
    assert not active()
    yield
    assert not active()


def _pin(monkeypatch: pytest.MonkeyPatch, *, overlay: bool) -> None:
    signal = OverlaySignal(overlay, ("t",) if overlay else ())
    monkeypatch.setattr(_cli, "detect_overlay", lambda **_k: signal)
    monkeypatch.setattr(dx, "detect_overlay", lambda **_k: signal)


def _run_main(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> tuple[int, dict[str, Any], str]:
    code = 0
    try:
        dx.main(argv)
    except SystemExit as exc:
        code = int(exc.code or 0)
    out = capsys.readouterr().out
    return code, json.loads(out), out


def _local(tmp_path: Path, *names: str) -> list[str]:
    """Copy golden inputs to ``tmp_path`` so the printed refs are stable names."""
    refs = []
    for name in names:
        shutil.copy(GOLDEN / name, tmp_path / name)
        refs.append(name)
    return refs


def _sink_for(store: InMemoryEngagementStorage, folder_id: str) -> DriveRunSink:
    return DriveRunSink(
        store,
        folder_id,
        run_id=RID,
        access_fingerprint=store.inspect_access(folder_id).fingerprint,
    )


@pytest.mark.unit
class TestSettings:
    def test_golden(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _pin(monkeypatch, overlay=False)
        monkeypatch.chdir(tmp_path)
        a, b = _local(tmp_path, "settings_a.json", "settings_b.json")
        code, _env, raw = _run_main(["settings", "--a", a, "--b", b], capsys)
        assert code == 0, raw
        assert raw == (GOLDEN / "settings.stdout.json").read_text()

    def test_paths_added_removed_changed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _pin(monkeypatch, overlay=False)
        monkeypatch.chdir(tmp_path)
        a, b = _local(tmp_path, "settings_a.json", "settings_b.json")
        code, env, _ = _run_main(["settings", "--a", a, "--b", b], capsys)
        assert code == 0
        data = env["data"]
        # The envelope's ``data`` is diffed, not the envelope.
        assert [c["path"] for c in data["changed"]] == [
            "$.settings.schedule.quartz_cron_expression",
            '$.settings.tasks[0].new_cluster.spark_conf["spark.sql.shuffle.partitions"]',
            "$.settings.tasks[0].new_cluster.spark_version",
        ]
        assert data["changed"][2] == {
            "path": "$.settings.tasks[0].new_cluster.spark_version",
            "a": "14.3.x-scala2.12",
            "b": "15.4.x-scala2.12",
        }
        assert [c["path"] for c in data["added"]] == [
            "$.settings.tags.team",
            "$.settings.tasks[0].new_cluster.autoscale.max_workers",
            "$.settings.tasks[0].new_cluster.autoscale.min_workers",
        ]
        assert data["removed"] == [
            {"path": "$.settings.tasks[0].new_cluster.num_workers", "a": 4},
            {"path": "$.settings.timeout_seconds", "a": 3600},
        ]
        assert data["counts"] == {
            "added": 3,
            "removed": 2,
            "changed": 3,
            "unchanged": 7,
        }

    def test_identical_documents(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _pin(monkeypatch, overlay=False)
        monkeypatch.chdir(tmp_path)
        (a,) = _local(tmp_path, "settings_a.json")
        code, env, _ = _run_main(["settings", "--a", a, "--b", a], capsys)
        assert code == 0
        assert env["data"]["counts"]["changed"] == 0
        assert env["data"]["added"] == env["data"]["removed"] == []

    def test_type_change_and_empty_container_are_leaves(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _pin(monkeypatch, overlay=False)
        (tmp_path / "a.json").write_text(json.dumps({"x": {}, "y": [1], "z": None}))
        (tmp_path / "b.json").write_text(json.dumps({"x": {"k": 1}, "y": "1"}))
        code, env, _ = _run_main(
            [
                "settings",
                "--a",
                str(tmp_path / "a.json"),
                "--b",
                str(tmp_path / "b.json"),
            ],
            capsys,
        )
        assert code == 0
        data = env["data"]
        assert data["added"] == [{"path": "$.x.k", "b": 1}, {"path": "$.y", "b": "1"}]
        assert data["removed"] == [
            {"path": "$.x", "a": {}},
            {"path": "$.y[0]", "a": 1},
            {"path": "$.z", "a": None},
        ]


@pytest.mark.unit
class TestMetrics:
    def test_golden(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _pin(monkeypatch, overlay=False)
        monkeypatch.chdir(tmp_path)
        a, b = _local(tmp_path, "metrics_a.json", "metrics_b.json")
        code, _env, raw = _run_main(["metrics", "--a", a, "--b", b], capsys)
        assert code == 0, raw
        assert raw == (GOLDEN / "metrics.stdout.json").read_text()

    def test_delta_and_unit_per_key(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _pin(monkeypatch, overlay=False)
        monkeypatch.chdir(tmp_path)
        a, b = _local(tmp_path, "metrics_a.json", "metrics_b.json")
        code, env, _ = _run_main(["metrics", "--a", a, "--b", b], capsys)
        assert code == 0
        rows = {m["key"]: m for m in env["data"]["metrics"]}
        assert rows["$.metrics.bytes_read_from_cache_pct"] == {
            "key": "$.metrics.bytes_read_from_cache_pct",
            "a": 12.5,
            "b": 40.0,
            "delta": 27.5,
            "unit": "pp",
        }
        assert rows["$.metrics.total_duration_ms"]["delta"] == -3000
        assert rows["$.metrics.total_duration_ms"]["unit"] == "ms"
        assert rows["$.metrics.compilationTimeMs"]["unit"] == "ms"
        assert rows["$.metrics.read_bytes"]["unit"] == "bytes"
        assert rows["$.metrics.rows_produced_count"]["unit"] == "count"
        assert rows["$.metrics.rows_produced_count"]["delta"] == 0
        # An unknown unit is omitted, not guessed.
        assert "unit" not in rows["$.metrics.pruned_files"]
        # One side only: no delta.
        assert rows["$.metrics.spill_to_disk_bytes"]["b"] is None
        assert rows["$.metrics.spill_to_disk_bytes"]["delta"] is None
        assert rows["$.metrics.queue_wait_ms"]["a"] is None
        # Booleans are not metrics; list elements have no stable key.
        assert "$.metrics.photon_used" not in rows
        assert not any(k.startswith("$.operators") for k in rows)
        assert env["data"]["counts"] == {
            "keys": 9,
            "changed": 6,
            "only_a": 1,
            "only_b": 1,
        }


@pytest.mark.unit
class TestContract:
    def test_output_is_deterministic_over_key_order(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _pin(monkeypatch, overlay=False)
        monkeypatch.chdir(tmp_path)
        a, b = _local(tmp_path, "metrics_a.json", "metrics_b.json")
        doc = json.loads((tmp_path / a).read_text())
        doc["metrics"] = dict(reversed(list(doc["metrics"].items())))
        (tmp_path / "reordered.json").write_text(json.dumps(doc))
        for verb in ("settings", "metrics"):
            _, first, _ = _run_main([verb, "--a", a, "--b", b], capsys)
            _, again, _ = _run_main([verb, "--a", "reordered.json", "--b", b], capsys)
            first["data"].pop("a")
            again["data"].pop("a")
            assert first == again

    def test_text_is_not_a_subcommand(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, env, _ = _run_main(["text", "--a", "x", "--b", "y"], capsys)
        assert code == 4
        assert "invalid choice: 'text'" in env["error"]

    @pytest.mark.parametrize("verb", ["settings", "metrics"])
    def test_both_refs_are_required(
        self, verb: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, _env, _ = _run_main([verb, "--a", "x.json"], capsys)
        assert code == 4

    def test_missing_file_is_arg_error(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _pin(monkeypatch, overlay=False)
        code, env, _ = _run_main(
            ["settings", "--a", "/no/such/a.json", "--b", "/no/such/b.json"], capsys
        )
        assert code == 4
        assert "--a file not found" in env["error"]

    def test_invalid_json_is_arg_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _pin(monkeypatch, overlay=False)
        (tmp_path / "bad.json").write_text("{not json")
        code, env, _ = _run_main(
            [
                "metrics",
                "--a",
                str(tmp_path / "bad.json"),
                "--b",
                str(tmp_path / "bad.json"),
            ],
            capsys,
        )
        assert code == 4
        assert "--a is not valid JSON" in env["error"]

    def test_overlay_local_file_is_refused_exit_2(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _pin(monkeypatch, overlay=True)
        a, b = _local(tmp_path, "settings_a.json", "settings_b.json")
        code, env, _ = _run_main(
            ["settings", "--a", str(tmp_path / a), "--b", str(tmp_path / b)], capsys
        )
        assert code == 2
        assert env["error"].startswith("LOCAL_FILE_INTAKE_REFUSED: --a ")

    def test_drive_objects_without_a_run_folder(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from types import SimpleNamespace

        from starboard_core.engagement import sink

        store = InMemoryEngagementStorage(owner_domain="databricks.com")
        entry = SimpleNamespace(value="tests:InMemory", load=lambda: lambda: store)
        monkeypatch.setattr(
            sink, "metadata", SimpleNamespace(entry_points=lambda **_kw: [entry])
        )
        _pin(monkeypatch, overlay=True)
        refs = []
        for name in ("settings_a.json", "settings_b.json"):
            obj = store.put_stream(
                store.root_folder_id(),
                name,
                "application/json",
                [(GOLDEN / name).read_bytes()],
                properties={},
            )
            refs.append(f"drive:{obj.id}")
        code, env, raw = _run_main(["settings", "--a", refs[0], "--b", refs[1]], capsys)
        assert code == 0, env
        assert env["data"]["counts"]["changed"] == 3
        assert raw.count("\n") == 1  # bounded (compact) on an overlay install


@pytest.mark.unit
class TestRunFolder:
    def _covered(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        store: InMemoryEngagementStorage,
    ) -> dict[str, Path]:
        sandbox = covered_env(monkeypatch, tmp_path, store)
        _pin(monkeypatch, overlay=True)
        monkeypatch.setattr(dx, "load_engagement_storage", lambda: store)
        return sandbox

    def _seed(self, store: InMemoryEngagementStorage, folder: str) -> None:
        sink = _sink_for(store, folder)
        for name in ("metrics_a.json", "metrics_b.json"):
            sink.put_json(f"raw/{name}", json.loads((GOLDEN / name).read_text()))

    def test_run_relative_refs_are_read_through_the_sink(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run()
        sandbox = self._covered(monkeypatch, tmp_path, store)
        self._seed(store, folder)
        before_run = written(_sink_for(store, folder))
        before = sandbox_snapshot(list(sandbox.values()))

        code, env, raw = _run_main(
            [
                "metrics",
                "--run-folder",
                folder,
                "--a",
                "raw/metrics_a.json",
                "--b",
                "raw/metrics_b.json",
            ],
            capsys,
        )

        assert code == 0, env["error"]
        assert env["data"]["counts"]["changed"] == 6
        assert sandbox_diff(before, sandbox_snapshot(list(sandbox.values()))) == []
        # Read-only: the verb writes nothing to the run.
        assert written(_sink_for(store, folder)) == before_run
        assert raw.count("\n") == 1
        assert len(raw.encode()) <= STDOUT_BUDGET

    def test_drive_object_ref_with_a_run_folder(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run()
        self._covered(monkeypatch, tmp_path, store)
        self._seed(store, folder)
        obj = store.put_stream(
            store.root_folder_id(),
            "other.json",
            "application/json",
            [(GOLDEN / "metrics_b.json").read_bytes()],
            properties={},
        )
        code, env, _ = _run_main(
            [
                "metrics",
                "--run-folder",
                folder,
                "--a",
                "raw/metrics_a.json",
                "--b",
                f"drive:{obj.id}",
            ],
            capsys,
        )
        assert code == 0, env["error"]
        assert env["data"]["b"] == f"drive:{obj.id}"

    def test_local_path_on_a_covered_run_is_refused(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run()
        self._covered(monkeypatch, tmp_path, store)
        self._seed(store, folder)
        local = tmp_path / "metrics_a.json"
        shutil.copy(GOLDEN / "metrics_a.json", local)
        code, env, _ = _run_main(
            [
                "metrics",
                "--run-folder",
                folder,
                "--a",
                str(local),
                "--b",
                "raw/metrics_b.json",
            ],
            capsys,
        )
        assert code == 2, env
        assert env["error"].startswith("LOCAL_STORAGE_REFUSED"), env["error"]
        assert "--a" in env["error"]

    def test_missing_run_relpath_is_arg_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run()
        self._covered(monkeypatch, tmp_path, store)
        self._seed(store, folder)
        code, env, _ = _run_main(
            [
                "metrics",
                "--run-folder",
                folder,
                "--a",
                "raw/metrics_a.json",
                "--b",
                "raw/nope.json",
            ],
            capsys,
        )
        assert code == 4, env
        assert "--b: raw/nope.json is not in the run folder" in env["error"]

    def test_oversize_run_object_is_arg_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        store, folder = drive_run()
        self._covered(monkeypatch, tmp_path, store)
        self._seed(store, folder)
        monkeypatch.setattr(_cli, "MAX_INTAKE_BYTES", 8)
        code, env, _ = _run_main(
            [
                "metrics",
                "--run-folder",
                folder,
                "--a",
                "raw/metrics_a.json",
                "--b",
                "raw/metrics_b.json",
            ],
            capsys,
        )
        assert code == 4, env
        assert "--a" in env["error"]
