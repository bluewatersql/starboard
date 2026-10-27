"""D4-15: an ``internal_only`` run declares its one workspace at preflight.

``engagement preflight --internal-workspace-id <id>`` is accepted only with
``--source-mode internal_only`` (a usage error, exit 2, otherwise, before any run is
opened). The preflight record keeps it and ``route`` copies it into the descriptor's
``authorized_scope`` (``workspace_ids == [id]``, ``basis: "declared"``); a customer
leg's scope comes from ``verify-identity`` (``basis: "verified"``). An internal_only
preflight without the flag is refused before any run is opened; a run preflighted
before that (empty scope) still gets a ``case open --clue`` error naming the flag.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from starboard_core.engagement.commit import latest_manifest, read_descriptor
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
from starboard_core.engagement.overlay import OverlaySignal
from starboard_skills.helpers import contract, engagement
from starboard_skills.helpers.__main__ import main
from starboard_skills.helpers.engagement import _envelope

OVERLAY_ON = OverlaySignal(enabled=True, reasons=("internal_package",))
HOST = "https://acme.cloud.databricks.com"
USER_ME = {"id": "7001", "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"]}
DESCRIPTOR = "analysis/run-authorization.json"
FLAG = "--internal-workspace-id"


class FakeWorkspace:
    def __init__(self) -> None:
        self.config = SimpleNamespace(host=HOST, workspace_id=None)
        self.api_client = self

    def do(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        return {**USER_ME, "X-Databricks-Org-Id": "123"}


@pytest.fixture(autouse=True)
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> InMemoryEngagementStorage:
    for name in ("home", "cwd", "tmp"):
        (tmp_path / name).mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path / "cwd")
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    s = InMemoryEngagementStorage(owner_domain="databricks.com")
    monkeypatch.setattr(_envelope, "_make_storage", lambda: s)
    monkeypatch.setattr(contract, "_load_storage", lambda: s)
    monkeypatch.setattr(_envelope, "_detect_overlay", lambda: OVERLAY_ON)
    monkeypatch.setattr(
        _envelope, "_make_workspace_client", lambda p, h: FakeWorkspace()
    )
    monkeypatch.delenv(engagement.SHARED_REGISTRY_ENV, raising=False)
    return s


def run(
    capsys: pytest.CaptureFixture[str], *argv: str
) -> tuple[int, dict[str, Any], str]:
    with pytest.raises(SystemExit) as exc:
        main(["engagement", *argv])
    raw = capsys.readouterr().out
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    return int(exc.value.code or 0), json.loads(lines[-1]), raw


def ok(capsys: pytest.CaptureFixture[str], *argv: str) -> dict[str, Any]:
    code, env, raw = run(capsys, *argv)
    assert code == 0, raw
    return env["data"]


def preflight(source_mode: str, *extra: str) -> list[str]:
    return [
        "preflight",
        "--source-mode",
        source_mode,
        "--task",
        "troubleshooting",
        "--task-name",
        "job-42",
        "--account-key",
        "001ABC",
        "--account-name",
        "Acme Corp",
        *extra,
    ]


@pytest.mark.parametrize("source_mode", ["customer_workspace", "hybrid"])
@pytest.mark.parametrize("local", [False, True])
def test_the_flag_needs_internal_only(
    capsys, store, tmp_path: Path, source_mode: str, local: bool
) -> None:
    reports = tmp_path / "reports"
    extra = ("--reports-root", str(reports)) if local else ()
    objects = store.object_count
    code, env, raw = run(capsys, *preflight(source_mode, FLAG, "123", *extra))
    assert code == 2, raw
    assert "internal_only" in env["errors"][0]["message"]
    assert FLAG in env["errors"][0]["message"]
    assert store.object_count == objects
    assert not reports.exists()


def test_the_flag_must_be_a_numeric_workspace_id(capsys, store) -> None:
    code, env, raw = run(capsys, *preflight("internal_only", FLAG, "ws-1"))
    assert code == 2, raw
    assert FLAG in env["errors"][0]["message"]


def test_drive_route_declares_the_scope(capsys, store) -> None:
    pre = ok(capsys, *preflight("internal_only", FLAG, "123"))
    assert pre["internal_workspace_id"] == "123"
    route = ok(capsys, "route", "--run-id", pre["run_id"])
    auth, _ = read_descriptor(store, route["run_folder_id"])
    assert dict(auth.authorized_scope) == {
        "account_key": "001ABC",
        "workspace_ids": ("123",),
        "basis": "declared",
    }
    assert route["authorized_scope"]["basis"] == "declared"
    latest = latest_manifest(store, route["run_folder_id"])
    assert latest is not None and latest[0].workflow_profile == "troubleshooting"


def test_local_route_declares_the_scope(capsys, tmp_path: Path) -> None:
    pre = ok(
        capsys,
        *preflight(
            "internal_only",
            FLAG,
            "123",
            "--storage",
            "local",
            "--reports-root",
            str(tmp_path / "reports"),
        ),
    )
    run_dir = Path(pre["local_run_dir"])
    ok(capsys, "route", "--run-dir", str(run_dir))
    scope = json.loads((run_dir / DESCRIPTOR).read_text())["authorized_scope"]
    assert scope == {
        "account_key": "001ABC",
        "workspace_ids": ["123"],
        "basis": "declared",
    }


def _tamper_local_preflight(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, source_mode: str, value: Any
) -> Path:
    """A local preflight whose recorded ``internal_workspace_id`` is then edited."""
    extra = (FLAG, "123") if source_mode == "internal_only" else ()
    pre = ok(
        capsys,
        *preflight(
            source_mode,
            *extra,
            "--storage",
            "local",
            "--reports-root",
            str(tmp_path / "reports"),
        ),
    )
    run_dir = Path(pre["local_run_dir"])
    if source_mode != "internal_only":
        ok(
            capsys,
            "verify-identity",
            "--run-dir",
            str(run_dir),
            "--profile",
            "acme",
            "--expected-workspace-id",
            "123",
        )
    record = run_dir / "analysis" / "storage-preflight.json"
    doc = json.loads(record.read_text())
    body = doc["data"] if isinstance(doc.get("data"), dict) else doc
    body["internal_workspace_id"] = value
    record.write_text(json.dumps(doc))
    return run_dir


@pytest.mark.parametrize(
    "source_mode, value",
    [
        ("internal_only", "123 OR 1=1"),
        ("internal_only", "ws-1"),
        ("internal_only", "\u00b2"),
        ("internal_only", 123),
        ("customer_workspace", "123"),
    ],
)
def test_route_revalidates_a_tampered_preflight_workspace(
    capsys,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_mode: str,
    value: Any,
) -> None:
    if source_mode != "internal_only":
        # Only the public (no overlay) path keeps a customer_workspace run local.
        monkeypatch.setattr(
            _envelope, "_detect_overlay", lambda: OverlaySignal(enabled=False)
        )
    run_dir = _tamper_local_preflight(capsys, tmp_path, source_mode, value)
    code, env, raw = run(capsys, "route", "--run-dir", str(run_dir))
    assert code == 2, raw
    assert "internal_workspace_id" in env["errors"][0]["message"]
    assert not (run_dir / DESCRIPTOR).exists()


@pytest.mark.parametrize("local", [False, True])
def test_internal_only_needs_the_flag(
    capsys, store, tmp_path: Path, local: bool
) -> None:
    # Live customer run 2026-10-21: an internal_only preflight without the flag made a
    # run with an empty scope; its capture was refused (INTERNAL_SCOPE_REFUSED) and the
    # dead run stayed in the account registry. Preflight now refuses before any run.
    reports = tmp_path / "reports"
    extra = ("--reports-root", str(reports)) if local else ()
    objects = store.object_count
    code, env, raw = run(capsys, *preflight("internal_only", *extra))
    assert code == 2, raw
    message = env["errors"][0]["message"]
    assert FLAG in message and "internal_only" in message
    assert store.object_count == objects
    assert not reports.exists()


def test_a_customer_leg_scope_is_verified(capsys, store) -> None:
    pre = ok(capsys, *preflight("customer_workspace"))
    ok(
        capsys,
        "verify-identity",
        "--run-id",
        pre["run_id"],
        "--profile",
        "acme",
        "--expected-workspace-id",
        "123",
    )
    route = ok(capsys, "route", "--run-id", pre["run_id"])
    auth, _ = read_descriptor(store, route["run_folder_id"])
    assert tuple(auth.authorized_scope["workspace_ids"]) == ("123",)
    assert auth.authorized_scope["basis"] == "verified"


def test_case_open_without_a_scope_names_the_flag(capsys, store, monkeypatch) -> None:
    # A run preflighted before the flag was required still has an empty scope.
    from starboard_skills.helpers.engagement import setup

    monkeypatch.setattr(setup, "_check_internal_workspace_id", lambda args, mode: None)
    pre = ok(capsys, *preflight("internal_only"))
    route = ok(capsys, "route", "--run-id", pre["run_id"])
    code, env, raw = run(
        capsys,
        "case",
        "open",
        "--run-folder",
        route["run_folder_id"],
        "--clue",
        "job:42",
        "--question",
        "Why did job 42 start failing after 2026-09-22?",
    )
    assert code == 2, raw
    assert FLAG in env["errors"][0]["message"]
