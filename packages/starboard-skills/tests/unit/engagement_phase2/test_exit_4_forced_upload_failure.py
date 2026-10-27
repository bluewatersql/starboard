"""P2-G14 exit test 4 - a forced Drive upload failure.

``InMemoryEngagementStorage.fail_put_after`` makes the provider fail a content
write after the adapter's retries are exhausted. The run stays pending and
resumable under the same run ID; the retry makes no duplicate objects, writes no
local artifact (nothing is spooled, D-23), and ``publication`` stays ``pending``.
"""

from __future__ import annotations

import io
from collections import Counter
from types import SimpleNamespace
from typing import Any

import pytest
from starboard_core.engagement.write_guard import sandbox_diff

from ._support import (
    discovery,
    drive_tree,
    eng,
    manifest,
    ok,
    put,
    routed,
)
from ._support import run_sink as _run_sink


def _artifact_counts(store: Any, rf: str) -> Counter[str]:
    """How many Drive objects carry each run relpath (duplicates show as > 1)."""
    from starboard_core.engagement.sink import ARTIFACT_PROPERTY

    counts: Counter[str] = Counter()
    pending = [rf]
    while pending:
        for child in store.list_children(pending.pop()):
            if child.is_folder:
                pending.append(child.id)
            elif child.properties.get(ARTIFACT_PROPERTY):
                counts[child.properties[ARTIFACT_PROPERTY]] += 1
    return counts


@pytest.mark.unit
class TestForcedUploadFailure:
    """Spec P2-G14 item 4."""

    def test_failed_discovery_upload_resumes_under_the_same_run_id(
        self, capsys, store, sandbox
    ) -> None:
        pre, route = routed(capsys)
        rf = route["run_folder_id"]
        before = sandbox.snapshot()

        store.fail_put_after = 1  # the first artifact lands, the next one fails
        code, env, raw = discovery(capsys, "run", "--data-only", "--run-folder", rf)
        store.fail_put_after = None
        assert code != 0 and env.get("ok") is False, raw

        status = ok(capsys, "status", "--run-id", pre["run_id"])
        assert status["run_id"] == pre["run_id"]
        assert status["resume"] == {
            "run_id": pre["run_id"], "run_folder_id": rf, "stage": "capture",
        }
        assert status["states"]["publication"] == "pending"

        code, env, raw = discovery(capsys, "run", "--data-only", "--run-folder", rf)
        assert code == 0, raw
        counts = _artifact_counts(store, rf)
        assert counts and max(counts.values()) == 1, counts
        committed = ok(capsys, "commit", "--run-folder", rf, "--stage", "capture")
        assert committed["run_id"] == pre["run_id"]
        assert manifest(store, rf).states["publication"] == "pending"
        assert sandbox_diff(before, sandbox.snapshot()) == []

    def test_failed_commit_is_capture_pending_and_retry_appends_once(
        self, capsys, store, sandbox
    ) -> None:
        pre, route = routed(capsys)
        rf = route["run_folder_id"]
        _run_sink(store, rf).put_json("raw/rows.json", [1, 2])
        before = sandbox.snapshot()

        store.fail_put_after = 0  # the manifest revision write fails
        code, env, raw = eng(capsys, "commit", "--run-folder", rf, "--stage", "capture")
        store.fail_put_after = None
        assert code == 4, raw
        assert env["errors"][0]["code"] == "STORAGE_ERROR"
        assert env["data"]["run_status"] == "capture_pending"
        assert env["data"]["resume"] == {
            "run_id": pre["run_id"], "run_folder_id": rf, "stage": "capture",
        }
        assert manifest(store, rf).revision == 1

        again = ok(capsys, "commit", "--run-folder", rf, "--stage", "capture")
        assert again["run_id"] == pre["run_id"] and again["revision"] == 2
        assert manifest(store, rf).states["publication"] == "pending"
        manifests = [
            c.name for c in store.list_children(rf, folders_only=True) if c.name == "manifest"
        ]
        assert len(manifests) == 1
        assert sandbox_diff(before, sandbox.snapshot()) == []

    def test_failed_host_put_leaves_no_partial_object_and_retries_cleanly(
        self, capsys, monkeypatch, store, sandbox
    ) -> None:
        _, route = routed(capsys)
        rf = route["run_folder_id"]
        before, objects = sandbox.snapshot(), store.object_count

        store.fail_put_after = 0
        monkeypatch.setattr("sys.stdin", SimpleNamespace(buffer=io.BytesIO(b"# Readme\n")))
        code, env, raw = eng(capsys, "put", "--run-folder", rf, "--path", "README.md")
        store.fail_put_after = None
        assert code == 4 and env["ok"] is False, raw
        assert "README.md" not in drive_tree(store, rf)

        put(capsys, monkeypatch, rf, {"README.md": "# Readme\n"})
        assert _artifact_counts(store, rf)["README.md"] == 1
        assert store.object_count > objects
        assert manifest(store, rf).states["publication"] == "pending"
        assert sandbox_diff(before, sandbox.snapshot()) == []
