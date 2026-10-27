"""P2-G14 exit test 3 - the missed-writer canary.

On a covered run a writer that still calls ``open(path, "w")`` (a writer the
migration missed) is stopped by the audit-hook write guard: ``LocalWriteRefused``
is raised, the command exits 2 with ``LOCAL_STORAGE_REFUSED``, nothing lands on
disk, and the run stays resumable at ``capture`` (``capture_pending`` when the
canary fires inside the capture commit).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from starboard_core.engagement.write_guard import (
    LocalWriteRefused,
    refused_events,
    sandbox_diff,
)
from starboard_skills.helpers import charts_render
from starboard_skills.helpers.engagement import _envelope

from ._support import (
    CHART_ROWS,
    FakeEngine,
    discovery,
    eng,
    error_code,
    helper,
    manifest,
    ok,
    routed,
    sink_put,
)


def _leak(target: Path) -> None:
    """The canary: a plain local write a migrated writer must never make."""
    with open(target, "w") as fh:  # noqa: PTH123 - the point of the test
        fh.write("leak")


def _refused(target: Path) -> bool:
    return any(Path(path).name == target.name for _event, path in refused_events())


@pytest.mark.unit
class TestMissedWriterCanary:
    """Spec P2-G14 item 3."""

    def test_canary_inside_the_discovery_writer_is_refused(
        self, capsys, monkeypatch, store, sandbox, seams
    ) -> None:
        from starboard_x.discovery import __main__ as disc

        pre, route = routed(capsys)
        rf = route["run_folder_id"]
        target = sandbox.roots[2] / "missed-writer.json"
        caught: list[BaseException] = []

        class LeakyEngine(FakeEngine):
            async def run(self) -> Any:
                try:
                    _leak(target)
                except LocalWriteRefused as exc:
                    caught.append(exc)
                    raise
                return await super().run()

        monkeypatch.setattr(disc, "build_engine", lambda _a: LeakyEngine(seams.result))
        before, objects = sandbox.snapshot(), store.object_count
        code, env, raw = discovery(capsys, "run", "--data-only", "--run-folder", rf)

        assert caught and isinstance(caught[0], LocalWriteRefused)
        assert code == 2, raw
        assert error_code(env) == "LOCAL_STORAGE_REFUSED", raw
        assert _refused(target)
        assert not target.exists()
        assert sandbox_diff(before, sandbox.snapshot()) == []
        assert store.object_count == objects
        status = ok(capsys, "status", "--run-id", pre["run_id"])
        assert status["run_id"] == pre["run_id"]
        assert status["resume"]["stage"] == "capture"
        assert manifest(store, rf).states["capture"] == "pending"

    def test_canary_inside_the_capture_commit_reports_capture_pending(
        self, capsys, monkeypatch, store, sandbox
    ) -> None:
        pre, route = routed(capsys)
        rf = route["run_folder_id"]
        sink_put(store, rf, {"raw/rows.json": [1, 2]})
        target = sandbox.roots[1] / "missed-writer.json"
        real = _envelope._read_verified

        def leaky(*a: Any, **k: Any) -> bytes:
            _leak(target)
            return real(*a, **k)

        monkeypatch.setattr(_envelope, "_read_verified", leaky)
        before, revision = sandbox.snapshot(), manifest(store, rf).revision
        code, env, raw = eng(capsys, "commit", "--run-folder", rf, "--stage", "capture")

        assert code == 2, raw
        assert error_code(env) == "LOCAL_STORAGE_REFUSED"
        # A usage refusal changed nothing: it echoes the run's status unchanged.
        status = ok(capsys, "status", "--run-folder", rf)
        assert env["data"]["run_status"] == status["run_status"] == "routed"
        assert env["data"]["resume"] == status["resume"]
        assert env["data"]["resume"]["stage"] == "capture"
        assert _refused(target) and not target.exists()
        assert sandbox_diff(before, sandbox.snapshot()) == []
        assert manifest(store, rf).revision == revision

    def test_canary_inside_a_helper_render_is_refused(
        self, capsys, monkeypatch, store, sandbox
    ) -> None:
        _, route = routed(capsys)
        rf = route["run_folder_id"]
        sink_put(store, rf, {"charts/data/spend.json": CHART_ROWS})
        target = sandbox.roots[0] / "chart-cache.png"

        def leaky(_vl: Any) -> bytes:
            _leak(target)
            return b"\x89PNG-fake"

        monkeypatch.setattr(charts_render, "_vegalite_to_png", leaky)
        before, objects = sandbox.snapshot(), store.object_count
        code, env, raw = helper(
            capsys, "charts", "render", "--kind", "spend-by-product", "--data",
            "charts/data/spend.json", "--out", "deliverables/charts/c.png",
            "--run-folder", rf,
        )

        assert code == 2, raw
        assert error_code(env) == "LOCAL_STORAGE_REFUSED", raw
        assert _refused(target) and not target.exists()
        assert sandbox_diff(before, sandbox.snapshot()) == []
        assert store.object_count == objects
