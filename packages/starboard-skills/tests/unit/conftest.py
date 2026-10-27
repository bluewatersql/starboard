"""Shared fixtures for the starboard-skills helper unit suite.

Overlay detection is pinned OFF for the whole skills suite by
``tests/conftest.py``; covered tests opt back in with ``covered_env``.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest
from starboard_skills.helpers import contract

RID = "20261008_12345678-1234-4234-8234-123456789abc"
WS = "123"


@dataclass
class DriveRun:
    """An in-memory Drive run folder with a committed run descriptor."""

    store: object
    folder_id: str
    run_id: str


def make_drive_run(
    *,
    account_key: str = "acme",
    ws: str = WS,
    run_id: str = RID,
    store=None,
    intent: str = "review",
    basis: str | None = None,
    workspace_profile: str | None = None,
) -> DriveRun:
    """A Drive run whose descriptor records ``intent`` (its ``run check`` workflow profile).

    ``basis`` / ``workspace_profile`` record how the identity was verified
    (``basis="verified"`` with a profile = ``verify-identity --profile``).
    """
    from starboard_core.engagement.commit import write_descriptor
    from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
    from starboard_core.engagement.policy import SourceMode, StoragePolicy
    from starboard_core.engagement.records import (
        AccountRef,
        DriveContext,
        RunAuthorization,
    )
    from starboard_core.ports.engagement_storage import Grant

    store = store if store is not None else InMemoryEngagementStorage()
    folder = store.create_folder(store.root_folder_id(), f"run-{run_id}", {})
    store.set_access(
        folder.id,
        can_add_children=True,
        grants=(Grant(kind="user", role="owner"),),
        complete=True,
    )
    staging = store.create_folder(store.root_folder_id(), f"staging-{run_id}", {})
    drive = DriveContext(
        provider="google_drive",
        principal="perm-1",
        route="account",
        base_folder_id="base",
        root_folder_id="root",
        run_folder_id=folder.id,
        registry_folder_id="reg",
        account_key=account_key,
        acl_classification="restricted",
        permission_fingerprints={folder.id: store.inspect_access(folder.id).fingerprint},
        capabilities={"upload": True},
        created_at="2026-10-08T09:00:00+00:00",
        idempotency_key="sbk1_" + "a" * 64,
        preflight_folder_id=staging.id,
    )
    write_descriptor(
        store,
        folder.id,
        RunAuthorization(
            engagement_id=f"{account_key}/{intent}/ws-{ws}",
            run_id=run_id,
            intent=intent,
            task="review",
            account=AccountRef(id=account_key, display_name="Acme", verifier="operator"),
            requested_scope={"workspace_ids": [ws]},
            authorized_scope={
                "account_key": account_key,
                "workspace_ids": [ws],
                **({"basis": basis} if basis else {}),
            },
            reporting_interval="P30D",
            timezone="UTC",
            source_mode=SourceMode.CUSTOMER_WORKSPACE,
            storage_policy=StoragePolicy.DRIVE_REQUIRED,
            audience="internal",
            methodology_version="m1",
            drive=drive,
            workspace_profile=workspace_profile,
        ),
    )
    return DriveRun(store, folder.id, run_id)


@pytest.fixture
def drive_run(monkeypatch: pytest.MonkeyPatch) -> DriveRun:
    """A Drive run folder; the helper's storage seam returns its in-memory store."""
    run = make_drive_run()
    monkeypatch.setattr(contract, "_load_storage", lambda: run.store)
    return run


@dataclass
class Sandbox:
    roots: tuple[Path, ...]

    def snapshot(self) -> dict[str, tuple[int, int]]:
        from starboard_core.engagement.write_guard import sandbox_snapshot

        return sandbox_snapshot(self.roots)


@pytest.fixture
def covered_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Sandbox:
    """Overlay ON, and HOME/cwd/TMPDIR sandboxed under tmp_path."""
    from starboard_core.engagement.overlay import OverlaySignal

    home, cwd, tmp = tmp_path / "home", tmp_path / "cwd", tmp_path / "tmp"
    for d in (home, cwd, tmp):
        d.mkdir()
    monkeypatch.setenv("STARBOARD_OVERLAY", "1")
    monkeypatch.setattr(
        contract,
        "_detect_overlay",
        lambda: OverlaySignal(True, ("forced_by_env",)),
        raising=False,
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("TMPDIR", str(tmp))
    monkeypatch.setattr(tempfile, "tempdir", str(tmp))
    monkeypatch.chdir(cwd)
    return Sandbox((home, cwd, tmp))


def drive_sink(run: DriveRun):
    """A reader sink over the run folder (as a later beat would open it)."""
    from starboard_core.engagement.policy import StorageDecision, StoragePolicy
    from starboard_core.engagement.sink import open_sink

    return open_sink(
        decision=StorageDecision(StoragePolicy.DRIVE_OPTIONAL, False, "test reader"),
        run_folder_id=run.folder_id,
        local_root=None,
        storage_factory=lambda: run.store,
    )


def drive_files(run: DriveRun) -> dict[str, bytes]:
    sink = drive_sink(run)
    return {rel: sink.get_bytes(rel) for rel in sink.list("")}


def evidence(run: DriveRun) -> list[dict]:
    import json

    sink = drive_sink(run)
    if not sink.exists("evidence/index.json"):
        return []
    return json.loads(sink.get_bytes("evidence/index.json"))


def run_main(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    """``starboard-helper argv`` -> (exit code, stdout)."""
    from starboard_skills.helpers import __main__ as cli

    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    code = exc.value.code if isinstance(exc.value.code, int) else 1
    return code, capsys.readouterr().out


def covered_ok(sandbox: Sandbox, before: dict, stdout: str) -> dict:
    """Covered-run invariants: no local write in the sandbox, compact stdout <= 24 000 B."""
    import json

    from starboard_core.engagement.write_guard import sandbox_diff

    assert sandbox_diff(before, sandbox.snapshot()) == []
    assert len(stdout.encode("utf-8")) <= 24_000
    assert stdout.count("\n") == 1, "bounded stdout is one compact JSON line"
    return json.loads(stdout)


def upload_tree(run: DriveRun, local: Path) -> dict[str, object]:
    """Upload every file under ``local`` into the run folder; ``{relpath: StorageRef}``.

    Kernel records go through ``put_record`` (fixture setup stands in for the
    kernel writer).
    """
    from starboard_core.engagement.sink import reserved_record

    sink = drive_sink(run)
    refs: dict[str, object] = {}
    for p in sorted(local.rglob("*")):
        if p.is_file():
            rel = p.relative_to(local).as_posix()
            put = sink.put_record if reserved_record(rel) else sink.put_bytes
            refs[rel] = put(rel, p.read_bytes(), "application/octet-stream")
    return refs


def put_files(run: DriveRun, files: dict[str, bytes | str]) -> dict[str, object]:
    """Fixture setup: write ``files``; kernel records go through ``put_record``."""
    from starboard_core.engagement.sink import reserved_record

    sink = drive_sink(run)
    out: dict[str, object] = {}
    for rel, data in files.items():
        raw = data.encode() if isinstance(data, str) else data
        put = sink.put_record if reserved_record(rel) else sink.put_bytes
        out[rel] = put(rel, raw, "application/json")
    return out


def commit_manifest(run: DriveRun, refs=(), **over):
    """Commit the next manifest revision of ``run`` (states default to analysis complete).

    ``workflow_profile`` defaults to the descriptor's (as route records it); pass it
    explicitly to tamper with it.
    """
    from starboard_core.engagement.commit import (
        DESCRIPTOR_NAME,
        append_manifest,
        read_descriptor,
    )
    from starboard_core.engagement.profiles import profile_for_task
    from starboard_core.engagement.records import RunManifest, StorageRef

    auth, obj = read_descriptor(run.store, run.folder_id)
    desc_ref = StorageRef(
        path=DESCRIPTOR_NAME, object_id=obj.id, revision=obj.revision, md5=obj.md5,
        size=obj.size, mime_type=obj.mime_type,
    )

    def build(n: int, previous: str | None) -> RunManifest:
        base = {
            "engagement_id": auth.engagement_id,
            "run_id": auth.run_id,
            "revision": n,
            "previous_object_id": previous,
            "task": auth.task,
            "task_name": "ws-123",
            "source_mode": auth.source_mode,
            "storage_policy": auth.storage_policy,
            "descriptor_ref": desc_ref,
            "refs": tuple(refs),
            "states": {"capture": "complete", "analysis": "complete", "check": "pending",
                       "publication": "pending"},
            "committed_at": "2026-10-08T10:00:00+00:00",
            "workflow_profile": profile_for_task(auth.intent),
        }
        base.update(over)
        return RunManifest(**base)

    return append_manifest(run.store, run.folder_id, build)[0]


def profile_kw(kw: dict) -> dict:
    """A mocked SDK client's construction kwargs as ``{"profile": p}`` (``{}`` = ambient).

    ``contract.make_client`` passes ``config=`` (stubbed suite-wide to a dict with the
    profile and the bounded retry budget); tests assert on the profile it carries."""
    profile = (kw.get("config") or {}).get("profile")
    return {"profile": profile} if profile else {}
