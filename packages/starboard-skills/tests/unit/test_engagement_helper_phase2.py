"""Phase-2 lifecycle tests for ``starboard-helper engagement``.

A covered run (overlay on, customer leg) is Drive-only. ``preflight``,
``verify-identity`` and ``route`` leave the local sandbox untouched, and
``--storage local`` is refused. The run-folder lifecycle runs through the CLI
entry point against the in-memory Drive fake:

* ``status``, ``commit``, ``read`` and ``history``
* publication: ``report``, ``approve``, ``deliver`` and ``receipt``
* the registry: ``import-local`` and ``rebuild-index``

No real Drive, CRM or Databricks call is made.
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
from starboard_core.engagement.policy import StorageDecision, StoragePolicy
from starboard_core.engagement.records import (
    DeliveryReceipt,
    EvidenceRef,
    Observation,
    StorageRef,
    evidence_id,
    observation_id,
)
from starboard_core.engagement.registry import (
    REGISTRY_SEGMENT,
    ensure_registry,
    list_registrations,
)
from starboard_core.engagement.sink import DriveRunSink, open_sink, sink_evidence
from starboard_core.engagement.staging import (
    QUARANTINE_PROPERTY,
    ensure_staging,
    quarantine_staging,
)
from starboard_core.engagement.write_guard import sandbox_diff, sandbox_snapshot
from starboard_core.ports.engagement_storage import Grant
from starboard_skills.helpers import engagement
from starboard_skills.helpers.__main__ import main
from starboard_skills.helpers.engagement import _envelope, _runs
from starboard_skills.helpers.engagement.publication import _existing_record

OVERLAY_ON = OverlaySignal(enabled=True, reasons=("internal_package",))
OVERLAY_OFF = OverlaySignal(enabled=False)
HOST = "https://acme.cloud.databricks.com"
USER_ME = {
    "id": "7001",
    "userName": "pat.operator@acme.example",
    "emails": [{"value": "pat.operator@acme.example", "primary": True}],
    "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
}
INTERNAL = (Grant("user", "owner", "databricks.com"),)
WIDE = (Grant("user", "owner", "databricks.com"), Grant("anyone", "reader"))
SUBCOMMANDS = (
    "preflight",
    "source-options",
    "verify-identity",
    "route",
    "status",
    "commit",
    "put",
    "read",
    "history",
    "report",
    "approve",
    "deliver",
    "receipt",
    "import-local",
    "rebuild-index",
    "analyze",
    "case",
    "action",
    "play",
)


class FakeWorkspace:
    def __init__(self, workspace_id: str = "123") -> None:
        self.config = SimpleNamespace(host=HOST, workspace_id=None)
        self.api_client = self
        self._workspace_id = workspace_id

    def do(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        return {**USER_ME, "X-Databricks-Org-Id": self._workspace_id}


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Point HOME, cwd and TMPDIR into ``tmp_path``; return the three roots."""
    roots = [tmp_path / "home", tmp_path / "cwd", tmp_path / "tmp"]
    for root in roots:
        root.mkdir()
    monkeypatch.setenv("HOME", str(roots[0]))
    monkeypatch.chdir(roots[1])
    monkeypatch.setenv("TMPDIR", str(roots[2]))
    return roots


@pytest.fixture(autouse=True)
def store(
    monkeypatch: pytest.MonkeyPatch, sandbox: list[Path]
) -> InMemoryEngagementStorage:
    s = InMemoryEngagementStorage(owner_domain="databricks.com")
    monkeypatch.setattr(_envelope, "_make_storage", lambda: s)
    monkeypatch.setattr(_envelope, "_detect_overlay", lambda: OVERLAY_ON)
    monkeypatch.delenv(engagement.SHARED_REGISTRY_ENV, raising=False)
    return s


@pytest.fixture(autouse=True)
def ws(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    holder = SimpleNamespace(client=FakeWorkspace())
    monkeypatch.setattr(_envelope, "_make_workspace_client", lambda p, h: holder.client)
    return holder


def run(
    capsys: pytest.CaptureFixture[str], *argv: str
) -> tuple[int, dict[str, Any], str]:
    """Run ``starboard-helper engagement <argv>``; return ``(exit, envelope, raw)``."""
    with pytest.raises(SystemExit) as exc:
        main(["engagement", *argv])
    raw = capsys.readouterr().out
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    return int(exc.value.code or 0), json.loads(lines[-1]), raw


def ok(capsys: pytest.CaptureFixture[str], *argv: str) -> dict[str, Any]:
    code, env, raw = run(capsys, *argv)
    assert code == 0, raw
    assert env["ok"] is True and env["domain"] == "engagement"
    return env["data"]


PREFLIGHT = (
    "preflight",
    "--source-mode",
    "customer_workspace",
    "--task",
    "health_check",
    "--task-name",
    "ws-123",
    "--account-key",
    "001ABC",
    "--account-name",
    "Acme Corp",
)


def routed(capsys: pytest.CaptureFixture[str], *route_flags: str) -> tuple[dict, dict]:
    pre = ok(capsys, *PREFLIGHT)
    ok(capsys, "verify-identity", "--run-id", pre["run_id"], "--profile", "acme")
    return pre, ok(capsys, "route", "--run-id", pre["run_id"], *route_flags)


def run_sink(store: InMemoryEngagementStorage, rf: str) -> DriveRunSink:
    auth, _ = read_descriptor(store, rf)
    assert auth.drive is not None
    return DriveRunSink(
        store,
        rf,
        run_id=auth.run_id,
        access_fingerprint=auth.drive.permission_fingerprints[rf],
    )


def _ref(path: str) -> StorageRef:
    return StorageRef(
        path=path,
        object_id="obj",
        revision="r1",
        md5="0" * 32,
        size=1,
        mime_type="application/json",
    )


def evidence(
    run_id: str, path: str, source_kind: str = "customer_workspace"
) -> EvidenceRef:
    audience = (
        "internal_only" if source_kind.startswith("internal_") else "customer_shareable"
    )
    return EvidenceRef(
        evidence_id=evidence_id(run_id, path, "0" * 32),
        run_id=run_id,
        storage_ref=_ref(path),
        source_kind=source_kind,
        scope_workspace_ids=("123",),
        producer="discovery",
        row_count=1,
        truncated=False,
        acquired_at="2026-10-08T09:00:00+00:00",
        audience_class=audience,
        method_version="v1",
    )


def observation(
    run_id: str,
    entity_id: str = "job-1",
    *,
    value: float = 1.0,
    start: str = "2026-10-01",
    end: str = "2026-10-31",
    source_kind: str = "customer_workspace",
    evidence_ids: tuple[str, ...] = (),
) -> Observation:
    audience = (
        "internal_only" if source_kind.startswith("internal_") else "customer_shareable"
    )
    key = ("001ABC", "123", "other", "job", entity_id, "dbus", start, end, "v1")
    return Observation(
        observation_id=observation_id(key),
        run_id=run_id,
        account_key="001ABC",
        workspace_id="123",
        family="other",
        entity_kind="job",
        entity_id=entity_id,
        metric="dbus",
        value=value,
        unit="DBU",
        grain="interval",
        method_version="v1",
        interval_start=start,
        interval_end=end,
        as_of="2026-11-01T00:00:00+00:00",
        coverage="complete",
        coverage_fraction=None,
        state="measured",
        unknown_reason=None,
        evidence_ids=evidence_ids,
        source_kind=source_kind,
        audience_class=audience,
    )


def operator_registry(store: InMemoryEngagementStorage) -> Any:
    return ensure_registry(store, "001ABC")[0]


# --------------------------------------------------------------------------- #
# Covered setup: Drive-only, nothing local
# --------------------------------------------------------------------------- #
class TestCoveredSetup:
    def test_covered_setup_leaves_the_sandbox_empty(self, capsys, sandbox, store):
        before = sandbox_snapshot(sandbox)
        pre, route = routed(capsys)
        assert sandbox_diff(before, sandbox_snapshot(sandbox)) == []
        assert pre["covered"] is True
        assert pre["storage_decision"] == "drive_required"
        assert pre["local_run_dir"] is None and pre["run_dir"] is None
        assert route["run_folder_id"]
        assert not (sandbox[1] / engagement.DEFAULT_REPORTS_ROOT).exists()

    def test_envelope_is_compact_and_fixed_shape(self, capsys):
        code, env, raw = run(capsys, *PREFLIGHT)
        assert code == 0
        assert set(env) == {"ok", "domain", "command", "data", "warnings", "errors"}
        assert env["command"] == "preflight" and env["errors"] == []
        assert raw.count("\n") == 1 and "\n  " not in raw
        assert "advisory_warning" not in env["data"]

    @pytest.mark.parametrize(
        "extra", [("--storage", "local"), ("--run-dir", "x"), ("--reports-root", "y")]
    )
    def test_local_storage_flags_are_refused_on_covered_runs(
        self, capsys, sandbox, store, extra
    ):
        before = sandbox_snapshot(sandbox)
        code, env, _ = run(capsys, *PREFLIGHT, *extra)
        assert code == 2
        assert env["ok"] is False
        assert env["errors"][0]["code"] == "LOCAL_STORAGE_REFUSED"
        assert store.object_count == 1
        assert sandbox_diff(before, sandbox_snapshot(sandbox)) == []

    def test_missing_storage_adapter_is_storage_unavailable(self, capsys, monkeypatch):
        from starboard_core.engagement.sink import StorageUnavailableError

        def boom() -> Any:
            raise StorageUnavailableError("no adapter")

        monkeypatch.setattr(_envelope, "_make_storage", boom)
        code, env, _ = run(capsys, *PREFLIGHT)
        assert code == 2 and env["errors"][0]["code"] == "STORAGE_UNAVAILABLE"

    def test_preflight_stages_the_record_in_drive(self, capsys, store):
        pre = ok(capsys, *PREFLIGHT)
        names = {c.name for c in store.list_children(pre["staging_folder_id"])}
        assert names == {engagement.STAGED_PREFLIGHT}
        assert pre["drive_principal"] == store.principal_id()

    def test_new_run_requires_account_key_and_name(self, capsys):
        flags = [f for f in PREFLIGHT if f not in ("--account-key", "001ABC")]
        code, env, _ = run(capsys, *flags)
        assert code == 2 and "--account-key" in env["errors"][0]["message"]


class TestResume:
    def test_resume_reads_the_staged_record(self, capsys, store):
        pre = ok(capsys, *PREFLIGHT)
        again = ok(capsys, "preflight", "--resume-run-id", pre["run_id"])
        assert again["run_id"] == pre["run_id"] and again["resumed"] is True
        assert again["staging_folder_id"] == pre["staging_folder_id"]

    def test_resume_rejects_disagreeing_flags(self, capsys):
        pre = ok(capsys, *PREFLIGHT)
        code, env, _ = run(
            capsys, "preflight", "--resume-run-id", pre["run_id"], "--task-name", "ws-9"
        )
        assert code == 2 and "disagrees" in env["errors"][0]["message"]

    def test_unknown_resume_id_errors_and_creates_nothing(self, capsys, store):
        ok(capsys, *PREFLIGHT)
        count = store.object_count
        code, env, _ = run(
            capsys,
            "preflight",
            "--resume-run-id",
            "20261008_3f2b8c1e-4a5d-4e6f-8a7b-9c0d1e2f3a4b",
        )
        assert code == 2 and "unknown run" in env["errors"][0]["message"]
        assert store.object_count == count

    def test_unknown_resume_id_on_empty_drive_creates_nothing(self, capsys, store):
        code, _, _ = run(
            capsys,
            "preflight",
            "--resume-run-id",
            "20261008_3f2b8c1e-4a5d-4e6f-8a7b-9c0d1e2f3a4b",
        )
        assert code == 2 and store.object_count == 1


class TestIdentity:
    def test_mismatch_quarantines_and_exits_5(self, capsys, store, ws):
        pre = ok(capsys, *PREFLIGHT)
        ws.client = FakeWorkspace(workspace_id="999")
        code, env, _ = run(
            capsys, "verify-identity", "--run-id", pre["run_id"], "--profile", "acme"
        )
        assert code == 5 and env["errors"][0]["code"] == "IDENTITY_MISMATCH"
        staged = store.get(pre["staging_folder_id"])
        assert staged.properties.get(QUARANTINE_PROPERTY)
        status = ok(capsys, "status", "--run-id", pre["run_id"])
        assert status["run_status"] == "quarantined" and status["resume"] is None
        code, env, _ = run(capsys, "route", "--run-id", pre["run_id"])
        assert code == 5 and env["errors"][0]["code"] == "RUN_QUARANTINED"

    def test_expected_workspace_id_alias(self, capsys):
        pre = ok(capsys, *PREFLIGHT)
        data = ok(
            capsys,
            "verify-identity",
            "--run-id",
            pre["run_id"],
            "--profile",
            "acme",
            "--workspace-id",
            "123",
        )
        assert data["status"] == "verified"

    @pytest.mark.parametrize(
        "reply",
        [
            RuntimeError("503 Service Unavailable"),
            None,
            {"id": "", "X-Databricks-Org-Id": "123"},
        ],
        ids=["call_failed", "no_record", "no_principal"],
    )
    def test_workspace_api_failure_is_not_a_storage_error(
        self, capsys, store, ws, reply
    ):
        pre = ok(capsys, *PREFLIGHT)

        class _Failing(FakeWorkspace):
            def do(self, method: str, path: str, **kw: Any) -> Any:
                if isinstance(reply, Exception):
                    raise reply
                return reply

        ws.client = _Failing()
        code, env, _ = run(
            capsys, "verify-identity", "--run-id", pre["run_id"], "--profile", "acme"
        )
        assert code == engagement.EXIT_WORKSPACE == 6
        assert env["errors"][0]["code"] == "WORKSPACE_API_ERROR"
        assert env["data"]["resume"]["stage"] == "verify-identity"  # retryable
        staged = store.get(pre["staging_folder_id"])
        assert not staged.properties.get(QUARANTINE_PROPERTY)

    @pytest.mark.parametrize("kind", ["unauthenticated", "permission_denied", "client"])
    def test_workspace_auth_failure_is_not_drive_auth(self, capsys, store, ws, monkeypatch, kind):
        """Databricks auth exits 3 like Drive auth, but with its own error code."""
        from databricks.sdk.errors import PermissionDenied, Unauthenticated

        pre = ok(capsys, *PREFLIGHT)
        if kind == "client":

            def no_client(*_a: Any) -> Any:
                raise _envelope.WorkspaceAuthError("Authentication error: no credentials")

            monkeypatch.setattr(_envelope, "_make_workspace_client", no_client)
        else:
            err = Unauthenticated("bad token") if kind == "unauthenticated" else (
                PermissionDenied("no scim")
            )

            class _Denied(FakeWorkspace):
                def do(self, method: str, path: str, **kw: Any) -> Any:
                    raise err

            ws.client = _Denied()
        code, env, _ = run(
            capsys, "verify-identity", "--run-id", pre["run_id"], "--profile", "acme"
        )
        assert code == engagement.EXIT_AUTH_PROMPT == 3
        assert env["errors"][0]["code"] == "WORKSPACE_AUTH_REQUIRED"

    def test_drive_auth_failure_keeps_its_code(self, capsys, store):
        store.auth_failed = True
        code, env, _ = run(capsys, *PREFLIGHT)
        assert code == 3 and env["errors"][0]["code"] == "AUTH_REQUIRED"


# --------------------------------------------------------------------------- #
# route: descriptor, manifest rev 1, registry
# --------------------------------------------------------------------------- #
class TestRoute:
    def test_account_route_registers_under_the_operator_registry(self, capsys, store):
        pre, data = routed(capsys)
        rf = data["run_folder_id"]
        registry = store.get(data["registry_folder_id"])
        assert registry.name == REGISTRY_SEGMENT
        auth, _ = read_descriptor(store, rf)
        assert auth.drive is not None
        assert auth.drive.registry_folder_id == data["registry_folder_id"]
        assert auth.drive.preflight_folder_id == pre["staging_folder_id"]
        assert auth.drive.permission_fingerprints[rf]
        manifest, _ = latest_manifest(store, rf)
        assert manifest.revision == 1 and data["manifest_revision"] == 1
        assert set(manifest.states.values()) == {"pending"}
        views = list_registrations(
            store, ensure_registry(store, "001ABC"), account_key="001ABC"
        )
        regs = [v.registration for v in views if v.registration is not None]
        assert [r.run_id for r in regs] == [pre["run_id"]]
        assert regs[0].registration_id == data["registration_id"]
        assert regs[0].run_folder_id == rf and regs[0].route == "account"

    def test_route_writes_identity_check_through_the_run_sink(self, capsys, store):
        _, data = routed(capsys)
        rf = data["run_folder_id"]
        sink = run_sink(store, rf)
        assert sink.exists(engagement.IDENTITY_RECORD)
        # The coordinator contract: a later writer can add to analysis/.
        ref = sink.put_json("analysis/x.json", {"a": 1})
        assert ref.path == "analysis/x.json"
        decision = StorageDecision(StoragePolicy.DRIVE_REQUIRED, True, "covered")
        opened = open_sink(
            decision=decision,
            run_folder_id=rf,
            local_root=None,
            storage_factory=lambda: store,
        )
        assert json.loads(opened.get_bytes("analysis/x.json")) == {"a": 1}
        analysis = [
            c
            for c in store.list_children(rf, folders_only=True)
            if c.name == "analysis"
        ]
        assert len(analysis) == 1

    def test_route_is_idempotent(self, capsys, store):
        pre, first = routed(capsys)
        again = ok(capsys, "route", "--run-id", pre["run_id"])
        assert again["run_folder_id"] == first["run_folder_id"]
        assert again["manifest_revision"] == 1
        assert again["registration_id"] == first["registration_id"]

    def test_route_status_resumes_at_capture(self, capsys):
        pre, data = routed(capsys)
        status = ok(capsys, "status", "--run-id", pre["run_id"])
        assert status["run_status"] == "routed"
        assert status["resume"]["stage"] == "capture"
        assert status["run_folder_id"] == data["run_folder_id"]

    def test_status_before_route_names_the_next_step(self, capsys):
        pre = ok(capsys, *PREFLIGHT)
        status = ok(capsys, "status", "--run-id", pre["run_id"])
        assert status["run_status"] == "staged"
        assert status["resume"]["stage"] == "verify-identity"

    def test_ticket_route_registers_under_the_operator_registry(
        self, capsys, store, tmp_path
    ):
        shared = store.add_shared_drive(
            "asqs-root",
            "ASQs",
            drive_id="d1",
            grants=(Grant("group", "fileOrganizer", "databricks.com"),),
        ).id
        ticket = tmp_path / "ticket.json"
        ticket.write_text(
            json.dumps(
                {
                    "ticket_ref": {
                        "schema_version": "1",
                        "ar_key": "AR-000000001",
                        "title": "Cost review",
                        "account_id": "001ABC",
                        "account_name": "Acme Corp",
                        "resolution": "validated",
                    }
                }
            )
        )
        _, data = routed(
            capsys,
            "--ticket-ref",
            str(ticket),
            "--shared-root-id",
            shared,
            "--internal-domain",
            "databricks.com",
        )
        assert data["route"] == "ticket"
        assert store.get(data["registry_folder_id"]).name == REGISTRY_SEGMENT
        assert data["registry_folder_id"] == operator_registry(store).folder_id

    def test_override_route_and_its_refusals(self, capsys, store):
        folder = store.create_folder(store.root_folder_id(), "Override", {})
        store.set_access(folder.id, grants=INTERNAL)
        _, data = routed(
            capsys,
            "--override-folder-id",
            folder.id,
            "--internal-domain",
            "databricks.com",
        )
        assert data["route"] == "override"
        assert data["registry_folder_id"] == operator_registry(store).folder_id

    def test_override_needs_internal_domain(self, capsys, store):
        pre = ok(capsys, *PREFLIGHT)
        ok(capsys, "verify-identity", "--run-id", pre["run_id"], "--profile", "acme")
        code, env, _ = run(
            capsys, "route", "--run-id", pre["run_id"], "--override-folder-id", "x"
        )
        assert code == 2 and "--internal-domain" in env["errors"][0]["message"]

    def test_unwritable_override_falls_back_with_warning(self, capsys, store):
        folder = store.create_folder(store.root_folder_id(), "Override", {})
        store.set_access(folder.id, grants=INTERNAL, can_add_children=False)
        _, data = routed(
            capsys,
            "--override-folder-id",
            folder.id,
            "--internal-domain",
            "databricks.com",
        )
        assert data["route"] == "account"
        assert data["fallback_warning"] and data["fallback_warning"] in data["warnings"]

    def test_broad_override_is_refused(self, capsys, store):
        folder = store.create_folder(store.root_folder_id(), "Override", {})
        store.set_access(folder.id, grants=WIDE)
        pre = ok(capsys, *PREFLIGHT)
        ok(capsys, "verify-identity", "--run-id", pre["run_id"], "--profile", "acme")
        code, env, _ = run(
            capsys,
            "route",
            "--run-id",
            pre["run_id"],
            "--override-folder-id",
            folder.id,
            "--internal-domain",
            "databricks.com",
        )
        assert code == 4 and env["ok"] is False

    def test_route_needs_a_verified_identity(self, capsys):
        pre = ok(capsys, *PREFLIGHT)
        code, env, _ = run(capsys, "route", "--run-id", pre["run_id"])
        assert code == 2 and "verify-identity" in env["errors"][0]["message"]


# --------------------------------------------------------------------------- #
# commit / status / read
# --------------------------------------------------------------------------- #
class TestCommit:
    def test_commit_records_verified_refs_and_never_touches_publication(
        self, capsys, store
    ):
        _, data = routed(capsys)
        rf = data["run_folder_id"]
        run_sink(store, rf).put_json("capture/rows.json", [1, 2])
        out = ok(capsys, "commit", "--run-folder", rf, "--stage", "capture")
        assert out["revision"] == 2 and "capture/rows.json" in out["refs_added"]
        manifest, _ = latest_manifest(store, rf)
        assert manifest.states["capture"] == "complete"
        assert manifest.states["publication"] == "pending"
        paths = [r.path for r in manifest.refs]
        assert paths == sorted(paths) and engagement.IDENTITY_RECORD in paths
        again = ok(capsys, "commit", "--run-folder", rf, "--stage", "capture")
        assert again["unchanged"] is True and again["revision"] == 2

    def test_commit_refuses_corrupt_artifacts(self, capsys, store):
        _, data = routed(capsys)
        rf = data["run_folder_id"]
        ref = run_sink(store, rf).put_json("capture/rows.json", [1, 2])
        store.corrupt_object(ref.object_id)
        code, env, _ = run(capsys, "commit", "--run-folder", rf, "--stage", "capture")
        assert code == 4 and env["errors"][0]["code"] == "STORAGE_ERROR"
        assert env["data"]["run_status"] == "capture_pending"
        assert env["data"]["resume"]["stage"] == "capture"
        assert latest_manifest(store, rf)[0].revision == 1

    def test_commit_records_evidence_and_observations(self, capsys, store):
        pre, data = routed(capsys)
        rf = data["run_folder_id"]
        sink = run_sink(store, rf)
        sink_evidence(sink, [evidence(pre["run_id"], "capture/rows.json")])
        record_json(
            sink, engagement.OBSERVATIONS_PATH, [observation(pre["run_id"]).to_dict()]
        )
        ok(capsys, "commit", "--run-folder", rf, "--stage", "analysis")
        manifest, _ = latest_manifest(store, rf)
        assert len(manifest.evidence_refs) == 1
        assert [r.path for r in manifest.observation_refs] == [
            engagement.OBSERVATIONS_PATH
        ]

    def test_revoked_access_is_blocked_access(self, capsys, store):
        _, data = routed(capsys)
        rf = data["run_folder_id"]
        store.set_access(rf, grants=WIDE)
        code, env, _ = run(capsys, "commit", "--run-folder", rf, "--stage", "capture")
        assert code == 4 and env["errors"][0]["code"] == "BLOCKED_ACCESS"
        assert env["data"]["run_status"] == "blocked_access"
        assert env["data"]["resume"] is None
        status = ok(capsys, "status", "--run-folder", rf)
        assert status["run_status"] == "blocked_access" and status["resume"] is None

    def test_status_after_capture(self, capsys, store):
        _, data = routed(capsys)
        rf = data["run_folder_id"]
        ok(capsys, "commit", "--run-folder", rf, "--stage", "capture")
        status = ok(capsys, "status", "--run-folder", rf)
        assert status["run_status"] == "analysis_pending"
        assert status["resume"]["stage"] == "analysis"
        assert status["checkpoint_revision"] == 2


# --------------------------------------------------------------------------- #
# put (host-authored artifacts, from stdin, straight to the run folder)
# --------------------------------------------------------------------------- #
def put(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    rf: str,
    path: str,
    data: bytes,
    *extra: str,
) -> tuple[int, dict[str, Any], str]:
    import io

    monkeypatch.setattr("sys.stdin", SimpleNamespace(buffer=io.BytesIO(data)))
    return run(capsys, "put", "--run-folder", rf, "--path", path, *extra)


BACKLOG = json.dumps({"items": [{"id": "opp-1", "lever": "resize"}]}).encode()


class TestPut:
    def test_put_then_commit_records_the_host_artifact(
        self, capsys, monkeypatch, store
    ):
        import hashlib

        _, data = routed(capsys)
        rf = data["run_folder_id"]
        code, env, raw = put(capsys, monkeypatch, rf, "analysis/backlog.json", BACKLOG)
        assert code == 0, raw
        out = env["data"]
        assert set(out) == {"path", "object_id", "md5", "size", "unchanged"}
        assert out["path"] == "analysis/backlog.json"
        assert out["md5"] == hashlib.md5(BACKLOG).hexdigest()
        assert out["size"] == len(BACKLOG) and out["unchanged"] is False
        committed = ok(capsys, "commit", "--run-folder", rf, "--stage", "analysis")
        assert "analysis/backlog.json" in committed["refs_added"]
        refs = {r.path: r for r in latest_manifest(store, rf)[0].refs}
        assert refs["analysis/backlog.json"].object_id == out["object_id"]
        assert refs["analysis/backlog.json"].md5 == out["md5"]

    def test_read_returns_the_put_artifact(self, capsys, monkeypatch, store):
        _, data = routed(capsys)
        rf = data["run_folder_id"]
        assert put(capsys, monkeypatch, rf, "analysis/backlog.json", BACKLOG)[0] == 0
        got = ok(capsys, "read", "--run-folder", rf, "--path", "analysis/backlog.json")
        assert json.loads(got["excerpt"]) == json.loads(BACKLOG)
        md = put(capsys, monkeypatch, rf, "domains/jobs.md", b"# Jobs\n")
        assert md[0] == 0
        got = ok(capsys, "read", "--run-folder", rf, "--path", "domains/jobs.md")
        assert got["excerpt"] == "# Jobs\n"

    @pytest.mark.parametrize(
        "path",
        ["README.md", "plan.json", "action-plan.md", "reports/cost-review/draft.md"],
    )
    def test_ordinary_run_paths_are_allowed(self, capsys, monkeypatch, path):
        _, data = routed(capsys)
        code, _, raw = put(capsys, monkeypatch, data["run_folder_id"], path, b"x")
        assert code == 0, raw

    def test_reput_of_identical_bytes_is_a_no_op(self, capsys, monkeypatch, store):
        _, data = routed(capsys)
        rf = data["run_folder_id"]
        first = put(capsys, monkeypatch, rf, "plan.json", b"{}")[1]["data"]
        count = store.object_count
        again = put(capsys, monkeypatch, rf, "plan.json", b"{}")[1]["data"]
        assert again["unchanged"] is True
        assert again["object_id"] == first["object_id"]
        assert store.object_count == count

    def test_changed_bytes_update_in_place(self, capsys, monkeypatch, store):
        _, data = routed(capsys)
        rf = data["run_folder_id"]
        first = put(capsys, monkeypatch, rf, "plan.json", b"{}")[1]["data"]
        second = put(capsys, monkeypatch, rf, "plan.json", b'{"v": 2}')[1]["data"]
        assert second["object_id"] == first["object_id"]
        assert second["md5"] != first["md5"] and second["unchanged"] is False
        assert len(store.list_children(rf, name="plan.json")) == 1

    @pytest.mark.parametrize(
        "path",
        [
            # descriptor and manifest chain
            "run-authorization.json",
            "manifest/rev-000002.json",
            # staging / registry / internal folders
            "_preflight/storage-preflight.json",
            "_registry/x.json",
            "_artifacts/x.json",
            "_quarantine/x.json",
            # records the helper itself writes
            "analysis/storage-preflight.json",
            "analysis/identity-check.json",
            "analysis/run-authorization.json",
            "analysis/baseline-selection.json",
            "reports/cost-review/rev-000001.json",
            "reports/cost-review/approvals/a1.json",
            "reports/cost-review/receipts/r1.json",
            # not run-relative
            "../outside.md",
            "/etc/passwd",
            "domains//x.md",
            "domains/",
            "./README.md",
        ],
    )
    def test_control_and_unsafe_paths_are_refused(
        self, capsys, monkeypatch, store, path
    ):
        _, data = routed(capsys)
        count = store.object_count
        code, env, _ = put(capsys, monkeypatch, data["run_folder_id"], path, b"{}")
        assert code == 2 and env["ok"] is False
        assert store.object_count == count

    def test_empty_stdin_is_refused(self, capsys, monkeypatch, store):
        _, data = routed(capsys)
        code, env, _ = put(capsys, monkeypatch, data["run_folder_id"], "plan.json", b"")
        assert code == 2 and "empty" in env["errors"][0]["message"]

    def test_stdin_over_the_cap_is_refused(self, capsys, monkeypatch, store):
        _, data = routed(capsys)
        rf = data["run_folder_id"]
        count = store.object_count
        code, env, _ = put(
            capsys, monkeypatch, rf, "plan.json", b"x" * 11, "--max-bytes", "10"
        )
        assert code == 2 and "10" in env["errors"][0]["message"]
        big = b"x" * (engagement.DEFAULT_PUT_BYTES + 1)
        code, _, _ = put(capsys, monkeypatch, rf, "plan.json", big)
        assert code == 2
        assert engagement.DEFAULT_PUT_BYTES == 5 * 2**20
        assert store.object_count == count
        code, _, _ = put(capsys, monkeypatch, rf, "plan.json", b"x", "--max-bytes", "0")
        assert code == 2

    def test_quarantined_run_is_refused(self, capsys, monkeypatch, store):
        pre, data = routed(capsys)
        quarantine_staging(store, ensure_staging(store, pre["run_id"]), "late")
        count = store.object_count
        code, env, _ = put(
            capsys, monkeypatch, data["run_folder_id"], "plan.json", b"{}"
        )
        assert code == 5 and env["errors"][0]["code"] == "RUN_QUARANTINED"
        assert store.object_count == count

    def test_changed_acl_is_refused_like_commit(self, capsys, monkeypatch, store):
        _, data = routed(capsys)
        rf = data["run_folder_id"]
        store.set_access(rf, grants=WIDE)
        code, env, _ = put(capsys, monkeypatch, rf, "plan.json", b"{}")
        commit_code, commit_env, _ = run(
            capsys, "commit", "--run-folder", rf, "--stage", "analysis"
        )
        assert code == commit_code == 4
        assert env["errors"][0]["code"] == commit_env["errors"][0]["code"]

    def test_a_non_run_folder_is_refused(self, capsys, monkeypatch, store):
        code, env, _ = put(
            capsys, monkeypatch, store.root_folder_id(), "plan.json", b"{}"
        )
        assert code in (2, 4) and env["ok"] is False

    def test_run_folder_is_required(self, capsys, monkeypatch):
        import io

        monkeypatch.setattr("sys.stdin", SimpleNamespace(buffer=io.BytesIO(b"x")))
        with pytest.raises(SystemExit) as exc:
            main(["engagement", "put", "--path", "plan.json"])
        assert exc.value.code == 2  # argparse USAGE: --run-folder is required
        with pytest.raises(SystemExit) as exc:
            main(["engagement", "put", "--run-folder", "x", "--file", "a.md"])
        assert exc.value.code == 2  # USAGE: no local-file input

    def test_put_writes_no_local_files(self, capsys, monkeypatch, store, sandbox):
        _, data = routed(capsys)
        before = sandbox_snapshot(sandbox)
        code, _, raw = put(
            capsys, monkeypatch, data["run_folder_id"], "analysis/backlog.json", BACKLOG
        )
        assert code == 0, raw
        assert sandbox_diff(before, sandbox_snapshot(sandbox)) == []


class TestRead:
    def test_read_is_bounded_and_verified(self, capsys, store):
        _, data = routed(capsys)
        rf = data["run_folder_id"]
        run_sink(store, rf).put_text("capture/big.txt", "x" * 100_000)
        out = ok(capsys, "read", "--run-folder", rf, "--path", "capture/big.txt")
        assert out["truncated"] is True and len(out["excerpt"]) < 24_000
        small = ok(
            capsys,
            "read",
            "--run-folder",
            rf,
            "--path",
            "capture/big.txt",
            "--max-bytes",
            "10",
        )
        assert len(small["excerpt"]) <= 10

    def test_plain_read_keeps_only_the_excerpt_head(self, capsys, store, monkeypatch):
        from starboard_skills.helpers.engagement import lifecycle

        _, data = routed(capsys)
        rf = data["run_folder_id"]
        run_sink(store, rf).put_text("capture/big.txt", "ab" * 300_000)

        def _whole_object(*_a: Any, **_kw: Any) -> bytes:
            raise AssertionError("a plain read must not buffer the whole object")

        monkeypatch.setattr(_envelope, "_read_verified", _whole_object)
        seen: list[int] = []
        real = lifecycle._read_head

        def _spy(storage: Any, obj: Any, keep: int, **kw: Any) -> tuple[bytes, int]:
            head, total = real(storage, obj, keep, **kw)
            seen.append(len(head))
            return head, total

        monkeypatch.setattr(lifecycle, "_read_head", _spy)
        out = ok(capsys, "read", "--run-folder", rf, "--path", "capture/big.txt")
        assert out["truncated"] is True and out["committed"] is False
        assert out["excerpt"] == ("ab" * 300_000)[: len(out["excerpt"])]
        assert 0 < len(out["excerpt"]) < 24_000 and seen and seen[0] <= 24_000
        assert out["size"] == 600_000

    def test_plain_read_still_verifies_the_bytes(self, capsys, store):
        _, data = routed(capsys)
        rf = data["run_folder_id"]
        run_sink(store, rf).put_text("capture/big.txt", "x" * 100_000)
        store.corrupt_get_stream = lambda b: b[:-1] + b"y"
        code, env, _ = run(
            capsys, "read", "--run-folder", rf, "--path", "capture/big.txt"
        )
        assert code == 4 and env["ok"] is False

    def test_jsonpath_read_has_its_own_lower_cap(self, capsys, store, monkeypatch):
        from starboard_skills.helpers.engagement import lifecycle

        _, data = routed(capsys)
        rf = data["run_folder_id"]
        run_sink(store, rf).put_json("capture/rows.json", {"rows": [{"a": 5}] * 50})
        monkeypatch.setattr(lifecycle, "_JSONPATH_MAX_BYTES", 64)
        code, env, _ = run(
            capsys,
            "read",
            "--run-folder",
            rf,
            "--path",
            "capture/rows.json",
            "--jsonpath",
            "rows.0.a",
        )
        assert code == 2 and env["errors"][0]["code"] == "READ_TOO_LARGE"

    def test_jsonpath_cap_holds_when_the_listing_has_no_size(self, capsys, store, monkeypatch):
        """The --jsonpath cap is enforced while streaming, not only on the listed size."""
        import dataclasses

        from starboard_skills.helpers.engagement import lifecycle

        _, data = routed(capsys)
        rf = data["run_folder_id"]
        run_sink(store, rf).put_json("capture/rows.json", {"rows": [{"a": 5}] * 50})
        real = lifecycle._artifacts
        monkeypatch.setattr(
            lifecycle,
            "_artifacts",
            lambda *a: {k: dataclasses.replace(v, size=None) for k, v in real(*a).items()},
        )
        monkeypatch.setattr(lifecycle, "_JSONPATH_MAX_BYTES", 64)
        code, env, _ = run(
            capsys,
            "read",
            "--run-folder",
            rf,
            "--path",
            "capture/rows.json",
            "--jsonpath",
            "rows.0.a",
        )
        assert code == 2 and env["errors"][0]["code"] == "READ_TOO_LARGE"

    def test_read_jsonpath(self, capsys, store):
        _, data = routed(capsys)
        rf = data["run_folder_id"]
        run_sink(store, rf).put_json("capture/rows.json", {"rows": [{"a": 5}]})
        out = ok(
            capsys,
            "read",
            "--run-folder",
            rf,
            "--path",
            "capture/rows.json",
            "--jsonpath",
            "rows.0.a",
        )
        assert out["excerpt"] == {"rows.0.a": 5}

    def test_read_unknown_path(self, capsys, store):
        _, data = routed(capsys)
        code, env, _ = run(
            capsys, "read", "--run-folder", data["run_folder_id"], "--path", "nope.json"
        )
        assert code == 4 and env["errors"][0]["code"] == "NOT_FOUND"


# --------------------------------------------------------------------------- #
# history
# --------------------------------------------------------------------------- #
class TestHistory:
    def test_history_selects_prior_run_baselines(self, capsys, store):
        pre_a, a = routed(capsys)
        sink_a = run_sink(store, a["run_folder_id"])
        record_json(
            sink_a,
            engagement.OBSERVATIONS_PATH,
            [
                observation(
                    pre_a["run_id"], value=1.0, start="2026-09-01", end="2026-09-30"
                ).to_dict()
            ],
        )
        ok(capsys, "commit", "--run-folder", a["run_folder_id"], "--stage", "analysis")

        pre_b, b = routed(capsys)
        rf = b["run_folder_id"]
        record_json(
            run_sink(store, rf),
            engagement.OBSERVATIONS_PATH,
            {"observations": [observation(pre_b["run_id"], value=2.0).to_dict()]},
        )
        out = ok(capsys, "history", "--run-folder", rf)
        assert out["candidates"] == 1 and out["current_observations"] == 1
        assert out["reporting_interval"] == ["2026-10-01", "2026-10-31"]
        assert run_sink(store, rf).exists(engagement.BASELINE_PATH)

    def test_run_two_selects_run_one_as_baseline_and_commits_the_refs(
        self, capsys, store
    ):
        pre_1, one = routed(capsys)
        prior = observation(
            pre_1["run_id"], value=1.0, start="2026-09-01", end="2026-09-30"
        )
        record_json(
            run_sink(store, one["run_folder_id"]),
            engagement.OBSERVATIONS_PATH,
            [prior.to_dict()],
        )
        ok(
            capsys,
            "commit",
            "--run-folder",
            one["run_folder_id"],
            "--stage",
            "analysis",
        )
        refs_1 = {r.path for r in latest_manifest(store, one["run_folder_id"])[0].refs}
        assert engagement.OBSERVATIONS_PATH in refs_1

        pre_2, two = routed(capsys)
        rf = two["run_folder_id"]
        current = observation(pre_2["run_id"], value=2.0)
        record_json(
            run_sink(store, rf), engagement.OBSERVATIONS_PATH, [current.to_dict()]
        )
        out = ok(capsys, "history", "--run-folder", rf)
        (pick,) = out["selected"]
        assert pick["baseline_observation_id"] == prior.observation_id
        assert pick["current_observation_id"] == current.observation_id
        assert pick["comparison"] == "continuing"
        read = ok(
            capsys,
            "read",
            "--run-folder",
            rf,
            "--path",
            engagement.BASELINE_PATH,
            "--jsonpath",
            "selected",
        )
        assert read["excerpt"] == {"selected": out["selected"]}

        ok(capsys, "commit", "--run-folder", rf, "--stage", "analysis")
        manifest, _ = latest_manifest(store, rf)
        assert [r.path for r in manifest.observation_refs] == [
            engagement.OBSERVATIONS_PATH
        ]
        assert manifest.baseline_selection_ref is not None
        assert manifest.baseline_selection_ref.path == engagement.BASELINE_PATH
        assert (
            manifest.baseline_selection_ref.object_id
            == (out["baseline_selection_ref"]["object_id"])
        )
        assert manifest.states["analysis"] == "complete"

    def test_history_merges_duplicate_account_folders_with_a_warning(
        self, capsys, store, monkeypatch
    ):
        from starboard_core.engagement.folders import IDENTITY_PROPERTY

        root = store.root_folder_id()
        starboard = store.add_folder(
            root, "starboard", properties={IDENTITY_PROPERTY: "segment:starboard"}
        )
        earliest = store.add_folder(
            starboard.id, "Acme (old)", properties={IDENTITY_PROPERTY: "account:001ABC"}
        )
        hidden = {earliest.id}
        listing = store.list_children

        def eventually(parent_id: str, **kw: Any) -> Any:
            return [o for o in listing(parent_id, **kw) if o.id not in hidden]

        monkeypatch.setattr(store, "list_children", eventually)
        pre_a, a = routed(capsys)
        assert a["account_folder_id"] != earliest.id
        record_json(
            run_sink(store, a["run_folder_id"]),
            engagement.OBSERVATIONS_PATH,
            [
                observation(
                    pre_a["run_id"], value=1.0, start="2026-09-01", end="2026-09-30"
                ).to_dict()
            ],
        )
        ok(capsys, "commit", "--run-folder", a["run_folder_id"], "--stage", "analysis")
        hidden.clear()

        pre_b, b = routed(capsys)
        assert b["account_folder_id"] == earliest.id
        assert any(w.startswith("duplicate_account_folders:") for w in b["warnings"])
        rf = b["run_folder_id"]
        record_json(
            run_sink(store, rf),
            engagement.OBSERVATIONS_PATH,
            [observation(pre_b["run_id"], value=2.0).to_dict()],
        )
        code, env, raw = run(capsys, "history", "--run-folder", rf)
        assert code == 0, raw
        assert env["data"]["candidates"] == 1
        assert any(
            w.startswith("duplicate_account_folders:") for w in env["warnings"]
        )

    def test_history_without_observations_needs_an_interval(self, capsys, store):
        _, data = routed(capsys)
        rf = data["run_folder_id"]
        code, env, _ = run(capsys, "history", "--run-folder", rf)
        assert code == 2 and "--interval-start" in env["errors"][0]["message"]
        out = ok(
            capsys,
            "history",
            "--run-folder",
            rf,
            "--interval-start",
            "2026-10-01",
            "--interval-end",
            "2026-10-31",
        )
        assert out["candidates"] == 0


# --------------------------------------------------------------------------- #
# publication
# --------------------------------------------------------------------------- #
def _report(capsys, rf: str, *extra: str, audience: str = "customer") -> dict[str, Any]:
    return ok(
        capsys,
        "report",
        "--run-folder",
        rf,
        "--report-id",
        "cost-review",
        "--audience",
        audience,
        "--path",
        "deliverables/report.md",
        *extra,
    )


class TestPublication:
    def _setup(
        self, capsys, store, *, internal_evidence: bool = False
    ) -> tuple[dict, str]:
        pre, data = routed(capsys)
        rf = data["run_folder_id"]
        sink = run_sink(store, rf)
        kind = "internal_mirror" if internal_evidence else "customer_workspace"
        ev = evidence(pre["run_id"], "capture/rows.json", kind)
        sink_evidence(sink, [ev])
        sink.put_text("deliverables/report.md", "# Report\n")
        # ``report`` binds only committed bytes (UNCOMMITTED_ARTIFACT otherwise).
        ok(capsys, "commit", "--run-folder", rf, "--stage", "capture")
        return {"pre": pre, "ev": ev}, rf

    def test_blocked_audience_cannot_be_delivered(self, capsys, store):
        ctx, rf = self._setup(capsys, store, internal_evidence=True)
        out = _report(capsys, rf, "--cite-evidence", ctx["ev"].evidence_id)
        assert out["state"] == "blocked_audience" and out["blocked_reasons"]
        code, env, _ = run(
            capsys,
            "deliver",
            "--run-folder",
            rf,
            "--report-id",
            "cost-review",
            "--revision",
            "1",
            "--destination-folder-id",
            store.root_folder_id(),
        )
        assert code == 2 and env["errors"][0]["code"] == "DELIVERY_REFUSED"

    def test_unknown_citation_fails_closed(self, capsys, store):
        _, rf = self._setup(capsys, store)
        out = _report(capsys, rf, "--cite-observation", "obs_missing")
        assert out["state"] == "blocked_audience"

    def test_approve_then_deliver_completes(self, capsys, store):
        ctx, rf = self._setup(capsys, store)
        out = _report(capsys, rf, "--cite-evidence", ctx["ev"].evidence_id)
        assert out["state"] == "ready" and out["revision"] == 1
        assert _report(capsys, rf, "--cite-evidence", ctx["ev"].evidence_id)[
            "unchanged"
        ]
        flags = ("--run-folder", rf, "--report-id", "cost-review", "--revision", "1")
        code, env, _ = run(
            capsys, "deliver", *flags, "--destination-folder-id", store.root_folder_id()
        )
        assert code == 2 and "approval" in env["errors"][0]["message"]
        approved = ok(capsys, "approve", *flags)
        assert approved["approval_id"].startswith("apr_")
        dest = store.create_folder(store.root_folder_id(), "Delivered", {}).id
        delivered = ok(capsys, "deliver", *flags, "--destination-folder-id", dest)
        assert delivered["state"] == "delivered"
        assert delivered["publication"] == "complete"
        assert [c.name for c in store.list_children(dest)] == ["report.md"]
        again = ok(capsys, "deliver", *flags, "--destination-folder-id", dest)
        assert again["receipt_id"] == delivered["receipt_id"]
        assert len(store.list_children(dest)) == 1
        manifest, _ = latest_manifest(store, rf)
        assert manifest.states["publication"] == "complete"
        assert manifest.approvals == (approved["approval_id"],)
        assert manifest.receipts == (delivered["receipt_id"],)

    def test_internal_report_needs_no_delivery(self, capsys, store):
        _, rf = self._setup(capsys, store)
        _report(capsys, rf, audience="internal")
        assert latest_manifest(store, rf)[0].states["publication"] == "skipped"

    def test_failed_delivery_leaves_publication_pending(self, capsys, store):
        ctx, rf = self._setup(capsys, store)
        _report(capsys, rf, "--cite-evidence", ctx["ev"].evidence_id)
        ok(
            capsys,
            "approve",
            "--run-folder",
            rf,
            "--report-id",
            "cost-review",
            "--revision",
            "1",
        )
        dest = store.create_folder(store.root_folder_id(), "Delivered", {}).id
        store.fail_put_after = 0
        code, env, _ = run(
            capsys,
            "deliver",
            "--run-folder",
            rf,
            "--report-id",
            "cost-review",
            "--revision",
            "1",
            "--destination-folder-id",
            dest,
        )
        store.fail_put_after = None
        assert code == 4 and env["data"]["run_status"] == "publication_pending"
        assert latest_manifest(store, rf)[0].states["publication"] == "pending"

    def test_slack_receipt_never_delivers(self, capsys, store):
        ctx, rf = self._setup(capsys, store)
        _report(capsys, rf, "--cite-evidence", ctx["ev"].evidence_id)
        flags = ("--run-folder", rf, "--report-id", "cost-review", "--revision", "1")
        ok(capsys, "approve", *flags)
        out = ok(
            capsys,
            "receipt",
            *flags,
            "--channel",
            "slack",
            "--external-object-id",
            "p123",
            "--destination-id",
            "C0123",
        )
        assert out["verified"] is False and out["state"] != "delivered"
        assert latest_manifest(store, rf)[0].states["publication"] == "pending"

    def test_drive_receipt_delivers(self, capsys, store, monkeypatch):
        # The in-memory store stamps objects from 2026-01-01; report "before" that.
        monkeypatch.setattr(_envelope, "_now", lambda: BEFORE_APPROVAL)
        _, rf = self._setup(capsys, store)
        _report(capsys, rf, audience="internal")
        dest = store.create_folder(store.root_folder_id(), "Delivered", {}).id
        doc = store.put_stream(dest, "Doc", "text/plain", [REPORT_BYTES], properties={})
        out = ok(
            capsys,
            "receipt",
            "--run-folder",
            rf,
            "--report-id",
            "cost-review",
            "--revision",
            "1",
            "--channel",
            "google_doc",
            "--external-object-id",
            doc.id,
            "--destination-id",
            dest,
        )
        assert out["verified"] is True and out["state"] == "delivered"

    def test_unattended_run_cannot_approve(self, capsys, store):
        pre = ok(capsys, *PREFLIGHT, "--unattended")
        ok(capsys, "verify-identity", "--run-id", pre["run_id"], "--profile", "acme")
        data = ok(capsys, "route", "--run-id", pre["run_id"])
        rf = data["run_folder_id"]
        sink = run_sink(store, rf)
        ev = evidence(pre["run_id"], "capture/rows.json")
        sink_evidence(sink, [ev])
        sink.put_text("deliverables/report.md", "# Report\n")
        ok(capsys, "commit", "--run-folder", rf, "--stage", "capture")
        _report(capsys, rf, "--cite-evidence", ev.evidence_id)
        code, env, _ = run(
            capsys,
            "approve",
            "--run-folder",
            rf,
            "--report-id",
            "cost-review",
            "--revision",
            "1",
        )
        assert code == 2 and env["errors"][0]["code"] == "APPROVAL_REFUSED"


# --------------------------------------------------------------------------- #
# Local runs, import-local, rebuild-index
# --------------------------------------------------------------------------- #
def _internal_local_run(capsys) -> Path:
    pre = ok(
        capsys,
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
        "--storage",
        "local",
        "--internal-workspace-id",
        "123",
    )
    assert pre["storage_decision"] == "internal_only_local"
    run_dir = Path(pre["local_run_dir"])
    ok(capsys, "route", "--run-dir", str(run_dir))
    return run_dir


class TestLocalRuns:
    def test_internal_only_local_creates_the_run_dir(self, capsys, store):
        run_dir = _internal_local_run(capsys)
        assert (run_dir / engagement.PREFLIGHT_RECORD).is_file()
        assert (run_dir / engagement.AUTHORIZATION_RECORD).is_file()
        assert store.object_count == 1

    def test_public_mode_keeps_local_storage(self, capsys, monkeypatch, store):
        monkeypatch.setattr(_envelope, "_detect_overlay", lambda: OVERLAY_OFF)
        pre = ok(capsys, *PREFLIGHT)
        assert pre["destination"] == "local" and pre["covered"] is False
        run_dir = Path(pre["local_run_dir"])
        assert (run_dir / engagement.PREFLIGHT_RECORD).is_file()
        ok(capsys, "verify-identity", "--run-dir", str(run_dir), "--profile", "acme")
        assert (run_dir / engagement.IDENTITY_RECORD).is_file()
        route = ok(capsys, "route", "--run-dir", str(run_dir))
        assert route["destination"] == "local"
        assert store.object_count == 1

    def test_public_local_record_refused_once_overlay_is_on(
        self, capsys, monkeypatch, store
    ):
        """A local preflight record does not exempt a customer run on an overlay install."""
        monkeypatch.setattr(_envelope, "_detect_overlay", lambda: OVERLAY_OFF)
        pre = ok(capsys, *PREFLIGHT)
        run_dir = Path(pre["local_run_dir"])
        monkeypatch.setattr(_envelope, "_detect_overlay", lambda: OVERLAY_ON)
        code, env, _ = run(
            capsys, "verify-identity", "--run-dir", str(run_dir), "--profile", "acme"
        )
        assert code == 2 and env["errors"][0]["code"] == "LOCAL_STORAGE_REFUSED"
        assert not (run_dir / engagement.IDENTITY_RECORD).exists()
        code, env, _ = run(capsys, "route", "--run-dir", str(run_dir))
        assert code == 2 and env["errors"][0]["code"] == "LOCAL_STORAGE_REFUSED"
        assert not (run_dir / engagement.AUTHORIZATION_RECORD).exists()


class TestImportLocal:
    def test_import_registers_a_summary(self, capsys, store):
        run_dir = _internal_local_run(capsys)
        obs = observation(
            "20261008_3f2b8c1e-4a5d-4e6f-8a7b-9c0d1e2f3a4b",
            source_kind="internal_mirror",
        )
        (run_dir / engagement.OBSERVATIONS_PATH).write_text(json.dumps([obs.to_dict()]))
        out = ok(
            capsys,
            "import-local",
            "--run-dir",
            str(run_dir),
            "--account-key",
            "001ABC",
            "--confirm",
        )
        assert out["registration_id"].startswith("reg_imp_")
        again = ok(
            capsys,
            "import-local",
            "--run-dir",
            str(run_dir),
            "--account-key",
            "001ABC",
            "--confirm",
        )
        assert again["registration_id"] == out["registration_id"]
        views = list_registrations(
            store, ensure_registry(store, "001ABC"), account_key="001ABC"
        )
        regs = [v.registration for v in views if v.registration is not None]
        assert [r.kind for r in regs] == ["imported_local"]
        assert regs[0].run_folder_id is None
        assert "@" not in regs[0].provenance["approved_by"]

    def test_import_refusals(self, capsys, store):
        run_dir = _internal_local_run(capsys)
        base = ("import-local", "--run-dir", str(run_dir), "--account-key", "001ABC")
        code, env, _ = run(capsys, *base)
        assert code == 2 and env["errors"][0]["code"] == "CONFIRM_REQUIRED"
        code, env, _ = run(capsys, *base, "--confirm", "--unattended")
        assert code == 2 and env["errors"][0]["code"] == "IMPORT_REFUSED"
        code, env, _ = run(
            capsys,
            "import-local",
            "--run-dir",
            str(run_dir),
            "--account-key",
            "001XYZ",
            "--confirm",
        )
        assert code == 2
        (run_dir / "capture").mkdir(exist_ok=True)
        (run_dir / "capture" / "rows.json").write_text(
            json.dumps({"rows": [{"source_kind": "customer_workspace"}]})
        )
        code, env, _ = run(capsys, *base, "--confirm")
        assert code == 2 and env["errors"][0]["code"] == "IMPORT_REFUSED"
        assert store.object_count == 1

    def test_public_local_run_cannot_be_imported(self, capsys, monkeypatch, store):
        monkeypatch.setattr(_envelope, "_detect_overlay", lambda: OVERLAY_OFF)
        pre = ok(capsys, *PREFLIGHT)
        run_dir = Path(pre["local_run_dir"])
        ok(capsys, "verify-identity", "--run-dir", str(run_dir), "--profile", "acme")
        ok(capsys, "route", "--run-dir", str(run_dir))
        code, env, _ = run(
            capsys,
            "import-local",
            "--run-dir",
            str(run_dir),
            "--account-key",
            "001ABC",
            "--confirm",
        )
        assert code == 2 and env["errors"][0]["code"] == "IMPORT_REFUSED"


class TestRebuildIndex:
    def test_rebuild_index_counts_registrations(self, capsys, store):
        routed(capsys)
        routed(capsys)
        out = ok(capsys, "rebuild-index", "--account-key", "001ABC")
        assert out["entries"] == 2 and out["handles"][0]["location"] == "operator"
        again = ok(capsys, "rebuild-index", "--account-key", "001ABC")
        assert again["index_revision"] == out["index_revision"]


class TestSurface:
    def test_upload_is_gone(self, capsys):
        assert not hasattr(engagement, "cmd_upload")
        assert not hasattr(engagement, "ADVISORY_WARNING")
        with pytest.raises(SystemExit) as exc:
            main(["engagement", "upload", "--run-folder", "x"])
        assert exc.value.code != 0
        capsys.readouterr()

    def test_registered_subcommands(self):
        import argparse

        parser = argparse.ArgumentParser()
        engagement.register(parser.add_subparsers(dest="domain"))
        sub = parser._subparsers._group_actions[0].choices["engagement"]  # type: ignore[union-attr]
        commands = sub._subparsers._group_actions[0].choices  # type: ignore[union-attr]
        assert tuple(commands) == SUBCOMMANDS


# --------------------------------------------------------------------------- #
# Hardening (phase-2 review group C)
# --------------------------------------------------------------------------- #
JSON_MIME = "application/json"
REPORT_BYTES = b"# Report\n"
BEFORE_APPROVAL = "2025-12-01T00:00:00+00:00"


def record_json(sink: DriveRunSink, path: str, payload: Any) -> StorageRef:
    """Write a kernel record the way kernel writers do (``put_record``)."""
    return sink.put_record(path, json.dumps(payload).encode(), JSON_MIME)


class TestErrorClassification:
    @pytest.mark.parametrize("exc", [RuntimeError("kaboom"), KeyError("kaboom")])
    def test_unexpected_errors_exit_1_with_a_traceback(self, capsys, monkeypatch, exc):
        def boom(*_a: Any, **_k: Any) -> Any:
            raise exc

        monkeypatch.setattr(_envelope, "_make_storage", boom)
        with pytest.raises(SystemExit) as code:
            main(["engagement", "status", "--run-folder", "rf-1"])
        out = capsys.readouterr()
        env = json.loads(out.out.strip().splitlines()[-1])
        assert code.value.code == engagement.EXIT_INTERNAL == 1
        assert env["ok"] is False and env["errors"][0]["code"] == "INTERNAL"
        assert "Traceback" in out.err and type(exc).__name__ in out.err

    def test_value_errors_stay_usage_errors(self, capsys, monkeypatch):
        def bad(*_a: Any, **_k: Any) -> Any:
            raise ValueError("bad argument")

        monkeypatch.setattr(_envelope, "_make_storage", bad)
        code, env, _ = run(capsys, "status", "--run-folder", "rf-1")
        assert code == 2 and env["errors"][0]["code"] == "USAGE"

    def test_a_corrupt_existing_record_is_an_integrity_error(self, capsys, store):
        from starboard_core.engagement.records import DeliveryReceipt
        from starboard_core.ports.engagement_storage import StorageIntegrityError

        pre, data = routed(capsys)
        rf = data["run_folder_id"]
        rel = "reports/cost-review/receipts/rcp_x.json"
        record_json(run_sink(store, rf), rel, {"receipt_id": 1})
        objs = _runs._artifacts(store, rf, pre["run_id"])
        with pytest.raises(StorageIntegrityError, match="not a valid record"):
            _existing_record(store, objs, rel, DeliveryReceipt)


class TestReservedRecords:
    @pytest.mark.parametrize(
        "path",
        [
            "analysis/observations.json",
            "analysis/findings.json",
            "findings-manifest.json",
            "evidence/index.json",
            "analysis/run-check.json",
            "analysis/recur-result.json",
            "Analysis/Run-Authorization.json",
            "REPORTS/cost-review/REV-000001.JSON",
            "reports/cost-review/receipts/nested/r1.json",
        ],
    )
    def test_put_refuses_kernel_records(self, capsys, monkeypatch, store, path):
        _, data = routed(capsys)
        count = store.object_count
        code, env, _ = put(capsys, monkeypatch, data["run_folder_id"], path, b"{}")
        assert code == 2 and env["ok"] is False
        assert store.object_count == count

    def test_put_max_bytes_cannot_exceed_the_default(self, capsys, monkeypatch):
        _, data = routed(capsys)
        rf = data["run_folder_id"]
        over = str(engagement.DEFAULT_PUT_BYTES + 1)
        code, env, _ = put(
            capsys, monkeypatch, rf, "plan.json", b"{}", "--max-bytes", over
        )
        assert (
            code == 2
            and str(engagement.DEFAULT_PUT_BYTES) in env["errors"][0]["message"]
        )
        at = str(engagement.DEFAULT_PUT_BYTES)
        assert (
            put(capsys, monkeypatch, rf, "plan.json", b"{}", "--max-bytes", at)[0] == 0
        )

    def test_commit_note_is_gone(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(
                [
                    "engagement",
                    "commit",
                    "--run-folder",
                    "x",
                    "--stage",
                    "capture",
                    "--note",
                    "n",
                ]
            )
        assert exc.value.code == 2
        capsys.readouterr()


class TestPinnedInternalDomains:
    def test_an_unpinned_internal_domain_is_refused(self, capsys, store):
        folder = store.create_folder(store.root_folder_id(), "Override", {})
        store.set_access(folder.id, grants=(Grant("user", "owner", "gmail.com"),))
        pre = ok(capsys, *PREFLIGHT)
        ok(capsys, "verify-identity", "--run-id", pre["run_id"], "--profile", "acme")
        code, env, _ = run(
            capsys,
            "route",
            "--run-id",
            pre["run_id"],
            "--override-folder-id",
            folder.id,
            "--internal-domain",
            "gmail.com",
        )
        assert code == 2 and "pinned" in env["errors"][0]["message"]

    def test_pinned_domains_match_case_insensitively(self, capsys, store):
        folder = store.create_folder(store.root_folder_id(), "Override", {})
        store.set_access(folder.id, grants=INTERNAL)
        _, data = routed(
            capsys,
            "--override-folder-id",
            folder.id,
            "--internal-domain",
            "Databricks.COM",
        )
        assert data["route"] == "override"

    def test_history_refuses_an_unpinned_domain(self, capsys):
        _, data = routed(capsys)
        code, env, _ = run(
            capsys,
            "history",
            "--run-folder",
            data["run_folder_id"],
            "--internal-domain",
            "evil.example",
        )
        assert code == 2 and "pinned" in env["errors"][0]["message"]


class TestReportGate:
    def _committed(self, capsys, store, *, body_source: str | None = None):
        pre, data = routed(capsys)
        rf = data["run_folder_id"]
        sink = run_sink(store, rf)
        ev = evidence(pre["run_id"], "capture/rows.json")
        refs = [ev]
        if body_source is not None:
            refs.append(evidence(pre["run_id"], "deliverables/report.md", body_source))
        sink_evidence(sink, refs)
        sink.put_bytes("deliverables/report.md", REPORT_BYTES, "text/markdown")
        sink.put_bytes("raw/report.md", REPORT_BYTES, "text/markdown")
        ok(capsys, "commit", "--run-folder", rf, "--stage", "capture")
        return ev, rf

    def test_customer_report_needs_a_citation(self, capsys, store):
        _, rf = self._committed(capsys, store)
        code, env, _ = run(
            capsys,
            "report",
            "--run-folder",
            rf,
            "--report-id",
            "cost-review",
            "--audience",
            "customer",
            "--path",
            "deliverables/report.md",
        )
        assert code == 2 and env["errors"][0]["code"] == "REPORT_REFUSED"
        assert "citation" in env["errors"][0]["message"]

    @pytest.mark.parametrize(
        "path", ["raw/report.md", "evidence/report.md", "Raw/report.md"]
    )
    @pytest.mark.parametrize("audience", ["internal", "customer"])
    def test_report_body_cannot_be_raw_or_evidence(self, capsys, store, path, audience):
        ev, rf = self._committed(capsys, store)
        code, env, _ = run(
            capsys,
            "report",
            "--run-folder",
            rf,
            "--report-id",
            "cost-review",
            "--audience",
            audience,
            "--path",
            path,
            "--cite-evidence",
            ev.evidence_id,
        )
        assert code == 2 and env["errors"][0]["code"] == "REPORT_REFUSED"

    def test_customer_report_body_cannot_be_internal_evidence(self, capsys, store):
        ev, rf = self._committed(capsys, store, body_source="internal_mirror")
        code, env, _ = run(
            capsys,
            "report",
            "--run-folder",
            rf,
            "--report-id",
            "cost-review",
            "--audience",
            "customer",
            "--path",
            "deliverables/report.md",
            "--cite-evidence",
            ev.evidence_id,
        )
        assert code == 2 and env["errors"][0]["code"] == "REPORT_REFUSED"
        assert "internal" in env["errors"][0]["message"]
        assert _report(capsys, rf, audience="internal")["state"] == "ready"


class TestReportDerivative:
    """D4-6: ``--derived-from`` must resolve; the gate reads the run's source mode."""

    def _run(self, capsys, store, source_mode: str) -> tuple[EvidenceRef, str]:
        argv = list(PREFLIGHT)
        argv[argv.index("--source-mode") + 1] = source_mode
        if source_mode == "internal_only":  # D4-15: it declares its workspace
            argv += ["--internal-workspace-id", "123"]
        pre = ok(capsys, *argv)
        if source_mode != "internal_only":  # no customer-workspace leg to verify
            ok(
                capsys,
                "verify-identity",
                "--run-id",
                pre["run_id"],
                "--profile",
                "acme",
            )
        rf = ok(capsys, "route", "--run-id", pre["run_id"])["run_folder_id"]
        sink = run_sink(store, rf)
        ev = evidence(pre["run_id"], "capture/rows.json")
        sink_evidence(sink, [ev])
        sink.put_text("deliverables/internal.md", "# Internal\n")
        sink.put_text("deliverables/report.md", "# Report\n")
        ok(capsys, "commit", "--run-folder", rf, "--stage", "capture")
        return ev, rf

    def _register(
        self, capsys, rf: str, report_id: str, path: str, audience: str, *extra: str
    ) -> tuple[int, dict[str, Any], str]:
        return run(
            capsys,
            "report",
            "--run-folder",
            rf,
            "--report-id",
            report_id,
            "--audience",
            audience,
            "--path",
            path,
            *extra,
        )

    def _internal(self, capsys, rf: str) -> dict[str, Any]:
        code, env, raw = self._register(
            capsys, rf, "internal-review", "deliverables/internal.md", "internal"
        )
        assert code == 0, raw
        return env["data"]

    def _customer(
        self,
        capsys,
        rf: str,
        ev: EvidenceRef,
        *extra: str,
        report_id: str = "cost-review",
    ) -> tuple[int, dict[str, Any], str]:
        return self._register(
            capsys,
            rf,
            report_id,
            "deliverables/report.md",
            "customer",
            "--cite-evidence",
            ev.evidence_id,
            *extra,
        )

    @staticmethod
    def _reports(store: InMemoryEngagementStorage, rf: str) -> list[str]:
        return sorted(
            p for p in run_sink(store, rf).list("") if p.startswith("reports/")
        )

    @pytest.mark.parametrize(
        ("mode", "allowed"),
        [
            ("customer_workspace", ["internal", "customer"]),
            ("hybrid", ["internal", "customer"]),
            ("internal_only", ["internal"]),
        ],
    )
    def test_output_carries_the_audience_derivation(self, capsys, store, mode, allowed):
        _, rf = self._run(capsys, store, mode)
        data = self._internal(capsys, rf)
        assert data["state"] == "ready"
        assert data["allowed_audiences"] == allowed
        assert "customer_eligible" not in data  # allowed_audiences is the one answer
        assert data["derived_from_revision"] is None
        again = self._internal(capsys, rf)
        assert again["unchanged"] is True
        assert again["allowed_audiences"] == allowed
        assert again["derived_from_revision"] is None

    def test_internal_only_run_blocks_a_customer_report(self, capsys, store):
        ev, rf = self._run(capsys, store, "internal_only")
        code, env, raw = self._customer(capsys, rf, ev)
        assert code == 0, raw
        assert env["data"]["state"] == "blocked_audience"
        assert env["data"]["blocked_reasons"][0] == "internal_only_run"

    def test_customer_workspace_run_needs_no_derivative(self, capsys, store):
        ev, rf = self._run(capsys, store, "customer_workspace")
        code, env, raw = self._customer(capsys, rf, ev)
        assert code == 0, raw
        assert env["data"]["state"] == "ready"

    def test_hybrid_customer_report_needs_an_internal_derivative(self, capsys, store):
        ev, rf = self._run(capsys, store, "hybrid")
        code, env, _ = self._customer(capsys, rf, ev)
        assert env["data"]["state"] == "blocked_audience"
        assert env["data"]["blocked_reasons"] == ["derivative_required"]

        src = self._internal(capsys, rf)
        code, env, raw = self._customer(
            capsys, rf, ev, "--derived-from", "internal-review@1", report_id="cust-a"
        )
        assert code == 0, raw
        data = env["data"]
        assert data["state"] == "ready" and data["blocked_reasons"] == []
        assert data["derived_from_revision"] == {
            "report_id": "internal-review",
            "revision": 1,
            "audience": "internal",
            "state": "ready",
            "object_md5": src["object_ref"]["md5"],
        }

        code, env, raw = self._customer(
            capsys, rf, ev, "--derived-from", "cust-a@1", report_id="cust-b"
        )
        assert code == 0, raw
        assert env["data"]["blocked_reasons"] == ["derivative_source_not_internal"]

    @pytest.mark.parametrize(
        "source", ["other@9", "internal-review@2", "cost-review@1"]
    )
    def test_dangling_or_self_derived_from_is_refused(self, capsys, store, source):
        ev, rf = self._run(capsys, store, "hybrid")
        self._internal(capsys, rf)
        if source.startswith("cost-review@"):
            code, _, raw = self._customer(
                capsys, rf, ev, "--derived-from", "internal-review@1"
            )
            assert code == 0, raw
        reports, objects = self._reports(store, rf), store.object_count
        manifest_rev = latest_manifest(store, rf)[0].revision
        code, env, _ = self._customer(capsys, rf, ev, "--derived-from", source)
        assert code == 2 and env["errors"][0]["code"] == "REPORT_REFUSED"
        assert self._reports(store, rf) == reports
        assert store.object_count == objects
        assert latest_manifest(store, rf)[0].revision == manifest_rev

    def test_approved_derivative_delivers_only_its_exact_revision(self, capsys, store):
        ev, rf = self._run(capsys, store, "hybrid")
        self._internal(capsys, rf)
        code, env, raw = self._customer(
            capsys, rf, ev, "--derived-from", "internal-review@1"
        )
        assert code == 0 and env["data"]["state"] == "ready", raw
        flags = ("--run-folder", rf, "--report-id", "cost-review", "--revision", "1")
        ok(capsys, "approve", *flags)
        slack = ok(
            capsys,
            "receipt",
            *flags,
            "--channel",
            "slack",
            "--external-object-id",
            "p123",
            "--destination-id",
            "C0123",
        )
        assert slack["verified"] is False and slack["state"] != "delivered"
        assert latest_manifest(store, rf)[0].states["publication"] == "pending"
        dest = store.create_folder(store.root_folder_id(), "Delivered", {}).id
        delivered = ok(capsys, "deliver", *flags, "--destination-folder-id", dest)
        assert delivered["state"] == "delivered"
        rcpt = _existing_record(
            store,
            _runs._artifacts(store, rf, read_descriptor(store, rf)[0].run_id),
            f"reports/cost-review/receipts/{delivered['receipt_id']}.json",
            DeliveryReceipt,
        )
        assert rcpt.verified is True and rcpt.channel != "slack"
        assert rcpt.object_md5 == env["data"]["object_ref"]["md5"]


class TestDeliveryDestination:
    def _approved(self, capsys, store) -> tuple[str, tuple[str, ...]]:
        ctx, rf = TestPublication()._setup(capsys, store)
        _report(capsys, rf, "--cite-evidence", ctx["ev"].evidence_id)
        flags = ("--run-folder", rf, "--report-id", "cost-review", "--revision", "1")
        ok(capsys, "approve", *flags)
        return rf, flags

    @pytest.mark.parametrize(
        ("grants", "complete"),
        [
            (WIDE, True),
            ((Grant("user", "reader", "acme.example"),), True),
            (INTERNAL, False),
        ],
    )
    def test_deliver_refuses_a_widened_or_unknown_destination(
        self, capsys, store, grants, complete
    ):
        _, flags = self._approved(capsys, store)
        dest = store.create_folder(store.root_folder_id(), "Shared", {}).id
        store.set_access(dest, grants=grants, complete=complete)
        code, env, _ = run(capsys, "deliver", *flags, "--destination-folder-id", dest)
        assert code == 2 and env["errors"][0]["code"] == "DELIVERY_REFUSED"
        assert store.list_children(dest) == []


class TestReceiptVerification:
    @pytest.fixture(autouse=True)
    def _early_clock(self, monkeypatch):
        # The in-memory store stamps objects from 2026-01-01; approve "before" that.
        monkeypatch.setattr(_envelope, "_now", lambda: BEFORE_APPROVAL)

    def _approved(self, capsys, store) -> tuple[str, tuple[str, ...]]:
        ctx, rf = TestPublication()._setup(capsys, store)
        _report(capsys, rf, "--cite-evidence", ctx["ev"].evidence_id)
        flags = ("--run-folder", rf, "--report-id", "cost-review", "--revision", "1")
        ok(capsys, "approve", *flags)
        return rf, flags

    def _receipt(self, capsys, flags, external: str, *extra: str) -> dict[str, Any]:
        return ok(
            capsys,
            "receipt",
            *flags,
            "--channel",
            "google_doc",
            "--external-object-id",
            external,
            *extra,
        )

    def _doc(self, store, parent: str, data: bytes = REPORT_BYTES) -> str:
        return store.put_stream(
            parent, "Doc", "text/markdown", [data], properties={}
        ).id

    def test_a_matching_doc_in_the_destination_delivers(self, capsys, store):
        rf, flags = self._approved(capsys, store)
        dest = store.create_folder(store.root_folder_id(), "Delivered", {}).id
        out = self._receipt(
            capsys, flags, self._doc(store, dest), "--destination-id", dest
        )
        assert out["verified"] is True and out["state"] == "delivered"
        assert latest_manifest(store, rf)[0].states["publication"] == "complete"

    def test_the_recorded_deliver_destination_is_used(self, capsys, store):
        _, flags = self._approved(capsys, store)
        dest = store.create_folder(store.root_folder_id(), "Delivered", {}).id
        ok(capsys, "deliver", *flags, "--destination-folder-id", dest)
        out = self._receipt(capsys, flags, self._doc(store, dest))
        assert out["verified"] is True

    def test_unverifiable_receipts_never_deliver(self, capsys, store, monkeypatch):
        rf, flags = self._approved(capsys, store)
        dest = store.create_folder(store.root_folder_id(), "Delivered", {}).id
        other = store.create_folder(store.root_folder_id(), "Other", {}).id
        auth, _ = read_descriptor(store, rf)
        assert auth.drive is not None
        staging = auth.drive.preflight_folder_id
        sub = store.create_folder(rf, "nested", {}).id
        cases = [
            (self._doc(store, dest), ()),  # no destination given or recorded
            (self._doc(store, dest), ("--destination-id", other)),  # wrong parent
            (self._doc(store, rf), ("--destination-id", rf)),  # inside the run
            (self._doc(store, sub), ("--destination-id", sub)),  # nested in the run
            (self._doc(store, staging), ("--destination-id", staging)),  # staging
            (self._doc(store, dest, b"tampered"), ("--destination-id", dest)),  # md5
        ]
        for external, extra in cases:
            out = self._receipt(capsys, flags, external, *extra)
            assert out["verified"] is False, (external, extra)
            assert out["state"] != "delivered"
        monkeypatch.setattr(_envelope, "_now", lambda: "2027-01-01T00:00:00+00:00")
        ctx2, rf2 = TestPublication()._setup(capsys, store)
        _report(capsys, rf2, "--cite-evidence", ctx2["ev"].evidence_id)
        flags2 = ("--run-folder", rf2, "--report-id", "cost-review", "--revision", "1")
        ok(capsys, "approve", *flags2)
        stale = self._doc(store, dest)  # created before the approval time
        out = self._receipt(capsys, flags2, stale, "--destination-id", dest)
        assert out["verified"] is False and out["state"] != "delivered"
        assert latest_manifest(store, rf2)[0].states["publication"] == "pending"


class TestImportLocalHardening:
    def _import(self, capsys, run_dir: Path) -> tuple[int, dict[str, Any], str]:
        return run(
            capsys,
            "import-local",
            "--run-dir",
            str(run_dir),
            "--account-key",
            "001ABC",
            "--confirm",
        )

    def test_reimport_with_a_changed_summary_is_refused(self, capsys, store):
        from starboard_core.engagement.registry import import_registration_id

        run_dir = _internal_local_run(capsys)
        local_id = json.loads((run_dir / engagement.AUTHORIZATION_RECORD).read_text())[
            "run_id"
        ]
        first = self._import(capsys, run_dir)
        assert first[0] == 0, first[2]
        assert first[1]["data"]["registration_id"] == import_registration_id(local_id)
        obs = observation(local_id, source_kind="internal_mirror")
        (run_dir / engagement.OBSERVATIONS_PATH).write_text(json.dumps([obs.to_dict()]))
        count = store.object_count
        code, env, _ = self._import(capsys, run_dir)
        assert code == 2 and env["errors"][0]["code"] == "IMPORT_REFUSED"
        assert store.object_count == count
        views = list_registrations(
            store, ensure_registry(store, "001ABC"), account_key="001ABC"
        )
        assert len([v for v in views if v.registration is not None]) == 1

    @pytest.mark.parametrize("content", [b"{not json", b"\xff\xfe\x00"])
    def test_an_unreadable_file_refuses_the_import(self, capsys, store, content):
        run_dir = _internal_local_run(capsys)
        (run_dir / "capture").mkdir(exist_ok=True)
        (run_dir / "capture" / "rows.json").write_bytes(content)
        code, env, _ = self._import(capsys, run_dir)
        assert code == 2 and env["errors"][0]["code"] == "IMPORT_REFUSED"
        assert "capture/rows.json" in env["errors"][0]["message"]
        assert store.object_count == 1

    def test_a_symlinked_json_file_refuses_the_import(self, capsys, store, tmp_path):
        run_dir = _internal_local_run(capsys)
        outside = tmp_path / "outside.json"
        outside.write_text(json.dumps({"source_kind": "customer_workspace"}))
        (run_dir / "capture").mkdir(exist_ok=True)
        (run_dir / "capture" / "rows.json").symlink_to(outside)
        code, env, _ = self._import(capsys, run_dir)
        assert code == 2 and env["errors"][0]["code"] == "IMPORT_REFUSED"
        assert "capture/rows.json" in env["errors"][0]["message"]
        assert "symlink" in env["errors"][0]["message"]
        assert store.object_count == 1


class TestRunUnattended:
    """``_run_unattended`` fails closed only on an unreadable staged record."""

    AUTH = SimpleNamespace(
        drive=SimpleNamespace(preflight_folder_id="stg"), run_id="r1"
    )

    def _with(self, monkeypatch, exc: BaseException) -> Any:
        from starboard_skills.helpers.engagement import publication

        def boom(*_a: Any, **_k: Any) -> Any:
            raise exc

        monkeypatch.setattr(publication, "_read_staged", boom)
        return publication._run_unattended

    @pytest.mark.parametrize("make", ["integrity", "not_found", "value"])
    def test_unreadable_record_counts_as_unattended(self, monkeypatch, store, make):
        from starboard_core.ports.engagement_storage import (
            StorageIntegrityError,
            StorageNotFoundError,
        )

        exc = {
            "integrity": StorageIntegrityError("bad md5"),
            "not_found": StorageNotFoundError("gone"),
            "value": ValueError("bad json"),
        }[make]
        assert self._with(monkeypatch, exc)(store, self.AUTH) is True

    def test_a_bug_is_not_swallowed(self, monkeypatch, store):
        fn = self._with(monkeypatch, RuntimeError("bug"))
        with pytest.raises(RuntimeError, match="bug"):
            fn(store, self.AUTH)


class TestReadRefCap:
    """``_read_ref`` streams a committed revision under a byte cap."""

    class _Stream:
        def __init__(self, chunks: int) -> None:
            self.chunks, self.pulled, self.revisions = chunks, 0, []

        def get_stream(self, object_id: str, revision: str | None = None):
            self.revisions.append(revision)
            for _ in range(self.chunks):
                self.pulled += 1
                yield b"x" * 1024

    def _ref(self, size: int | None) -> StorageRef:
        return StorageRef(
            path="capture/big.json",
            object_id="o1",
            revision="r7",
            md5=None,
            size=size,
            mime_type="application/json",
        )

    def test_stream_stops_at_the_cap(self):
        from starboard_core.ports.engagement_storage import StorageIntegrityError

        fake = self._Stream(1000)
        with pytest.raises(StorageIntegrityError, match="larger than"):
            _runs._read_ref(fake, self._ref(None), max_bytes=4096)
        assert fake.pulled <= 5 and fake.revisions == ["r7"]

    def test_recorded_size_over_the_cap_is_refused_before_download(self):
        from starboard_core.ports.engagement_storage import StorageIntegrityError

        fake = self._Stream(10)
        with pytest.raises(StorageIntegrityError, match="larger than"):
            _runs._read_ref(fake, self._ref(10 * 1024), max_bytes=4096)
        assert fake.pulled == 0

    def test_default_cap_reads_the_committed_revision(self):
        fake = self._Stream(2)
        assert _runs._read_ref(fake, self._ref(2048)) == b"x" * 2048
        assert fake.revisions == ["r7"]
