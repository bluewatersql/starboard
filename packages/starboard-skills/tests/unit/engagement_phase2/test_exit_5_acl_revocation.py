"""P2-G14 exit test 5 - ACL revocation.

Two shapes of revocation on a covered run:

* the run folder's sharing is broadened after ``route`` (the access recheck no
  longer matches the recorded fingerprint, D-24);
* write access is revoked mid-writer (``revoke_access_after_writes``).

Either way the run is ``blocked_access`` with no resume, and no Drive write
happens after the revocation.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from starboard_core.engagement.write_guard import sandbox_diff

from ._support import (
    CHART_ROWS,
    REVIEW_ROWS,
    WIDE,
    discovery,
    eng,
    error_code,
    helper,
    manifest,
    ok,
    review,
    routed,
    sink_put,
)

WRITERS: list[tuple[str, Callable[..., Any], Callable[[str], list[str]]]] = [
    ("engagement commit", eng, lambda rf: ["commit", "--run-folder", rf, "--stage", "capture"]),
    ("engagement put", eng, lambda rf: ["put", "--run-folder", rf, "--path", "README.md"]),
    ("engagement history", eng, lambda rf: [
        "history", "--run-folder", rf, "--interval-start", "2026-10-01",
        "--interval-end", "2026-10-31"]),
    ("starboard_x.discovery", discovery, lambda rf: ["run", "--data-only", "--run-folder", rf]),
    ("starboard_x.review", review, lambda rf: [
        "score", "--run-folder", rf, "--rows", "raw/rows.json", "--workspace", "acme"]),
    ("helper charts", helper, lambda rf: [
        "charts", "render", "--kind", "spend-by-product", "--data", "charts/data/spend.json",
        "--out", "deliverables/charts/c.png", "--run-folder", rf]),
]


@pytest.mark.unit
class TestBroadenedSharing:
    """Spec P2-G14 item 5: sharing broadened after route."""

    @pytest.mark.parametrize(("name", "fn", "argv"), WRITERS, ids=[w[0] for w in WRITERS])
    def test_every_writer_is_refused_and_writes_nothing(
        self, name, fn, argv, capsys, monkeypatch, store, sandbox
    ) -> None:
        _, route = routed(capsys)
        rf = route["run_folder_id"]
        sink_put(store, rf, {"raw/rows.json": REVIEW_ROWS, "charts/data/spend.json": CHART_ROWS})
        store.set_access(rf, grants=WIDE)
        monkeypatch.setattr("sys.stdin", SimpleNamespace(buffer=io.BytesIO(b"# Readme\n")))
        before, objects = sandbox.snapshot(), store.object_count

        code, env, raw = fn(capsys, *argv(rf))

        # Storage/integrity/access exits 4 on the engagement helper, 7 on every other
        # writer surface (4 is arg-error there), on BLOCKED_ACCESS.
        assert code == (4 if fn is eng else 7) and env.get("ok") is False, raw
        assert "blocked_access" in raw
        assert store.object_count == objects
        assert sandbox_diff(before, sandbox.snapshot()) == []
        assert "README.md" not in {c.name for c in store.list_children(rf)}
        status = ok(capsys, "status", "--run-folder", rf)
        assert status["run_status"] == "blocked_access" and status["resume"] is None

    def test_engagement_commands_name_blocked_access_with_no_resume(self, capsys, store) -> None:
        _, route = routed(capsys)
        rf = route["run_folder_id"]
        store.set_access(rf, grants=WIDE)
        code, env, _ = eng(capsys, "commit", "--run-folder", rf, "--stage", "capture")
        assert code == 4 and error_code(env) == "BLOCKED_ACCESS"
        assert env["data"]["run_status"] == "blocked_access" and env["data"]["resume"] is None
        status = ok(capsys, "status", "--run-folder", rf)
        assert status["run_status"] == "blocked_access" and status["resume"] is None
        assert manifest(store, rf).revision == 1


@pytest.mark.unit
class TestMidRunRevocation:
    """Spec P2-G14 item 5: write access revoked while a writer runs."""

    def test_revocation_mid_discovery_stops_every_later_write(self, capsys, store, sandbox) -> None:
        pre, route = routed(capsys)
        rf = route["run_folder_id"]
        before = sandbox.snapshot()

        writes_before = store.object_count
        store.revoke_access_after_writes = 1
        code, env, raw = discovery(capsys, "run", "--data-only", "--run-folder", rf)
        assert code != 0 and env.get("ok") is False, raw
        after_revocation = store.object_count
        assert after_revocation <= writes_before + 1  # only the one allowed write landed

        status = ok(capsys, "status", "--run-id", pre["run_id"])
        assert status["run_status"] == "blocked_access", status
        assert status["resume"] is None

        for argv in (
            ["commit", "--run-folder", rf, "--stage", "capture"],
            ["history", "--run-folder", rf, "--interval-start", "2026-10-01",
             "--interval-end", "2026-10-31"],
        ):
            code, env, _ = eng(capsys, *argv)
            assert code == 4 and error_code(env) == "BLOCKED_ACCESS"
        code, _, _ = discovery(capsys, "run", "--data-only", "--run-folder", rf)
        assert code != 0
        assert store.object_count == after_revocation
        assert manifest(store, rf).revision == 1
        assert sandbox_diff(before, sandbox.snapshot()) == []
