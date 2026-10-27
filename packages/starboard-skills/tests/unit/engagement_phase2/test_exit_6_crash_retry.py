"""P2-G14 exit test 6 - crash and retry.

A writer that dies part-way (the provider fails after N content writes, standing
in for a crashed process) is simply re-run: the run ID is kept, the objects that
did land are reused in place (same Drive object ID per relpath, no twins), and the
next commit advances the manifest by exactly one revision. A second crash during
the commit itself still advances by exactly one on the retry.
"""

from __future__ import annotations

from typing import Any

import pytest
from starboard_core.engagement.sink import ARTIFACT_PROPERTY

from ._support import discovery, eng, manifest, ok, routed


def _object_ids(store: Any, rf: str) -> dict[str, list[str]]:
    """``relpath -> [object id, ...]`` for every run artifact under ``rf``."""
    found: dict[str, list[str]] = {}
    pending = [rf]
    while pending:
        for child in store.list_children(pending.pop()):
            if child.is_folder:
                pending.append(child.id)
            elif child.properties.get(ARTIFACT_PROPERTY):
                found.setdefault(child.properties[ARTIFACT_PROPERTY], []).append(child.id)
    return found


@pytest.mark.unit
class TestCrashRetry:
    """Spec P2-G14 item 6."""

    def test_rerun_after_a_crash_reuses_objects_and_keeps_the_run_id(
        self, capsys, store
    ) -> None:
        pre, route = routed(capsys)
        rf = route["run_folder_id"]
        start = manifest(store, rf).revision

        store.fail_put_after = 2  # two artifacts land, then the "process" dies
        code, _, raw = discovery(capsys, "run", "--data-only", "--run-folder", rf)
        store.fail_put_after = None
        assert code != 0, raw
        landed = _object_ids(store, rf)
        assert landed, "the crash should leave the first artifacts behind"

        code, env, raw = discovery(capsys, "run", "--data-only", "--run-folder", rf)
        assert code == 0, raw
        after = _object_ids(store, rf)
        assert all(len(ids) == 1 for ids in after.values()), after
        for rel, ids in landed.items():
            assert after[rel] == ids, rel  # reused in place, not re-created

        committed = ok(capsys, "commit", "--run-folder", rf, "--stage", "capture")
        assert committed["run_id"] == pre["run_id"]
        assert committed["revision"] == start + 1
        assert manifest(store, rf).revision == start + 1
        status = ok(capsys, "status", "--run-id", pre["run_id"])
        assert status["run_id"] == pre["run_id"] and status["run_folder_id"] == rf

    def test_crash_during_commit_then_retry_advances_exactly_one_revision(
        self, capsys, store
    ) -> None:
        pre, route = routed(capsys)
        rf = route["run_folder_id"]
        assert discovery(capsys, "run", "--data-only", "--run-folder", rf)[0] == 0
        ok(capsys, "commit", "--run-folder", rf, "--stage", "capture")
        start = manifest(store, rf).revision
        ids = _object_ids(store, rf)

        store.fail_put_after = 0
        code, env, raw = eng(capsys, "commit", "--run-folder", rf, "--stage", "analysis")
        store.fail_put_after = None
        assert code == 4, raw
        assert env["data"]["run_status"] == "analysis_pending"
        assert env["data"]["resume"]["run_id"] == pre["run_id"]
        assert manifest(store, rf).revision == start

        again = ok(capsys, "commit", "--run-folder", rf, "--stage", "analysis")
        assert again["revision"] == start + 1 and again["run_id"] == pre["run_id"]
        assert _object_ids(store, rf) == ids  # the retry wrote only the manifest
        replay = ok(capsys, "commit", "--run-folder", rf, "--stage", "analysis")
        assert replay["unchanged"] is True and replay["revision"] == start + 1
