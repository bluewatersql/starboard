"""Local engagement runs never load the Drive storage adapter.

The ``starboard.engagement_storage`` loader is patched to raise
``StorageUnavailableError`` (no adapter installed). A local run (``local`` or
``internal_only_local``) still runs ``preflight``, ``verify-identity``,
``route`` and ``status`` end to end by ``--run-id`` or ``--run-dir``; a Drive
run still refuses with ``STORAGE_UNAVAILABLE`` and mints no resumable run.
``status --run-id`` echoes the run ID on every error path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from starboard_core.engagement import sink
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
from starboard_core.engagement.sink import StorageUnavailableError
from starboard_core.ports.engagement_storage import StorageAuthError
from starboard_skills.helpers import engagement
from starboard_skills.helpers.engagement import _envelope, lifecycle

from .test_engagement_helper_phase2 import (
    OVERLAY_OFF,
    OVERLAY_ON,
    PREFLIGHT,
    FakeWorkspace,
    ok,
    run,
)

INTERNAL_LOCAL = (
    "preflight",
    "--source-mode",
    "internal_only",
    "--task",
    "discovery",
    "--task-name",
    "ws-123",
    "--account-key",
    "001ABC",
    "--account-name",
    "Acme Corp",
    "--internal-workspace-id",
    "123",
    "--storage",
    "local",
)
UNKNOWN = "20261012_0f5e8c1a-3b2d-4c6e-9a7f-1d2e3f4a5b6c"


@pytest.fixture(autouse=True)
def no_adapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """No storage entry point installed; returns the count of loader calls."""
    calls: list[int] = []

    def missing() -> Any:
        calls.append(1)
        raise StorageUnavailableError(
            "expected one 'starboard.engagement_storage' entry point, found 0"
        )

    monkeypatch.setattr(sink, "load_engagement_storage", missing)
    monkeypatch.setattr(_envelope, "_detect_overlay", lambda: OVERLAY_ON)
    monkeypatch.setattr(
        _envelope, "_make_workspace_client", lambda _p, _h: FakeWorkspace()
    )
    monkeypatch.delenv(engagement.SHARED_REGISTRY_ENV, raising=False)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    return calls


class TestLocalRunsNeedNoAdapter:
    def test_internal_only_local_by_run_id(self, capsys, no_adapter):
        pre = ok(capsys, *INTERNAL_LOCAL)
        assert pre["storage_decision"] == "internal_only_local"
        run_id = pre["run_id"]
        staged = ok(capsys, "status", "--run-id", run_id)
        assert staged["run_status"] == "staged" and staged["destination"] == "local"
        assert staged["resume"] == {
            "run_id": run_id,
            "run_folder_id": None,
            "stage": "route",
        }
        route = ok(capsys, "route", "--run-id", run_id)
        assert route["destination"] == "local"
        st = ok(capsys, "status", "--run-id", run_id)
        assert st["run_status"] == "routed" and st["resume"] is None
        assert st["run_dir"] == Path(pre["local_run_dir"]).as_posix()
        by_dir = ok(capsys, "status", "--run-dir", pre["local_run_dir"])
        assert by_dir["run_status"] == "routed"
        assert no_adapter == []

    def test_public_local_by_run_id(self, capsys, monkeypatch, no_adapter):
        monkeypatch.setattr(_envelope, "_detect_overlay", lambda: OVERLAY_OFF)
        pre = ok(capsys, *PREFLIGHT)
        assert pre["storage_decision"] == "local"
        run_id = pre["run_id"]
        st = ok(capsys, "status", "--run-id", run_id)
        assert st["resume"]["stage"] == "verify-identity"
        ok(capsys, "verify-identity", "--run-id", run_id, "--profile", "acme")
        run_dir = Path(pre["local_run_dir"])
        assert (run_dir / engagement.IDENTITY_RECORD).is_file()
        assert ok(capsys, "status", "--run-id", run_id)["resume"]["stage"] == "route"
        ok(capsys, "route", "--run-id", run_id)
        assert (run_dir / engagement.AUTHORIZATION_RECORD).is_file()
        assert ok(capsys, "status", "--run-id", run_id)["run_status"] == "routed"
        assert no_adapter == []

    def test_run_dir_outside_the_default_root(self, capsys, monkeypatch, tmp_path):
        monkeypatch.setattr(_envelope, "_detect_overlay", lambda: OVERLAY_OFF)
        pre = ok(capsys, *PREFLIGHT, "--reports-root", str(tmp_path / "elsewhere"))
        run_dir = pre["local_run_dir"]
        ok(capsys, "verify-identity", "--run-dir", run_dir, "--profile", "acme")
        ok(capsys, "route", "--run-dir", run_dir)
        assert ok(capsys, "status", "--run-dir", run_dir)["run_status"] == "routed"


class TestDriveRunsStillRefuse:
    @pytest.mark.parametrize(
        "flags",
        [PREFLIGHT, INTERNAL_LOCAL[:-2]],
        ids=["drive_required", "drive_default"],
    )
    def test_preflight_refuses_with_no_resumable_run(self, capsys, flags):
        code, env, _ = run(capsys, *flags)
        assert code == 2 and env["errors"][0]["code"] == "STORAGE_UNAVAILABLE"
        assert env["data"]["run_id"] is None and "resume" not in env["data"]
        assert not Path(engagement.DEFAULT_REPORTS_ROOT).exists()

    @pytest.mark.parametrize("verb", ["route", "status"])
    def test_unknown_run_id_reads_drive(self, capsys, verb):
        code, env, _ = run(capsys, verb, "--run-id", UNKNOWN)
        assert code == 2 and env["errors"][0]["code"] == "STORAGE_UNAVAILABLE"
        assert "--run-dir" in env["errors"][0]["message"]
        assert env["data"]["run_id"] == UNKNOWN

    def test_verify_identity_unknown_run_id_reads_drive(self, capsys):
        code, env, _ = run(
            capsys, "verify-identity", "--run-id", UNKNOWN, "--profile", "acme"
        )
        assert code == 2 and env["errors"][0]["code"] == "STORAGE_UNAVAILABLE"
        assert env["data"]["run_id"] == UNKNOWN


class TestStatusEchoesRunId:
    def _store(self, monkeypatch: pytest.MonkeyPatch) -> InMemoryEngagementStorage:
        store = InMemoryEngagementStorage(owner_domain="databricks.com")
        monkeypatch.setattr(_envelope, "_make_storage", lambda: store)
        return store

    def test_unknown_run(self, capsys, monkeypatch):
        self._store(monkeypatch)
        code, env, _ = run(capsys, "status", "--run-id", UNKNOWN)
        assert code == 2 and "unknown run" in env["errors"][0]["message"]
        assert env["data"]["run_id"] == UNKNOWN

    def test_drive_auth_failure(self, capsys, monkeypatch):
        self._store(monkeypatch)

        def denied(*_a: Any) -> Any:
            raise StorageAuthError("token expired")

        monkeypatch.setattr(lifecycle, "_locate_staging", denied)
        code, env, _ = run(capsys, "status", "--run-id", UNKNOWN)
        assert code == 3 and env["errors"][0]["code"] == "AUTH_REQUIRED"
        assert env["data"]["run_id"] == UNKNOWN

    def test_preflight_drive_auth_failure_stages_nothing(self, capsys, monkeypatch):
        """An expired Drive sign-in reports no run ID: the fix is to re-run preflight."""
        store = self._store(monkeypatch)
        monkeypatch.setattr(_envelope, "_detect_overlay", lambda: OVERLAY_ON)
        before = len(store._entries)
        store.auth_failed = True
        code, env, _ = run(capsys, *PREFLIGHT)
        assert code == 3 and env["errors"][0]["code"] == "AUTH_REQUIRED"
        assert env["data"]["run_id"] is None and "resume" not in env["data"]
        assert len(store._entries) == before

    def test_stale_local_record(self, capsys, monkeypatch):
        monkeypatch.setattr(_envelope, "_detect_overlay", lambda: OVERLAY_OFF)
        run_id = ok(capsys, *PREFLIGHT)["run_id"]
        monkeypatch.setattr(_envelope, "_detect_overlay", lambda: OVERLAY_ON)
        code, env, _ = run(capsys, "status", "--run-id", run_id)
        assert code == 2 and env["errors"][0]["code"] == "LOCAL_STORAGE_REFUSED"
        assert env["data"]["run_id"] == run_id

    def test_run_id_with_run_folder_reads_the_folder(self, capsys):
        # run-5 B3: --run-id may accompany the run's --run-folder (checked against it).
        code, env, _ = run(capsys, "status", "--run-id", UNKNOWN, "--run-folder", "f")
        assert code == 2 and env["errors"][0]["code"] == "STORAGE_UNAVAILABLE"
