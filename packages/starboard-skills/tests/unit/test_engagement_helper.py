"""Unit tests for ``starboard-helper engagement`` (phase-1 coverage, migrated).

The Drive-only setup lifecycle: preflight, verify-identity, route and commit.
The commit tests replace the deleted ``upload`` command. All storage is the
in-memory fake and the workspace is a fake client, so no Drive, CRM or
Databricks call is made. ``test_engagement_helper_phase2.py`` covers the
envelope, sandbox and publication lifecycle.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from starboard_core.engagement.commit import latest_manifest, read_descriptor
from starboard_core.engagement.enforce import LocalStorageRefused
from starboard_core.engagement.folders import resolve_account_route
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
from starboard_core.engagement.overlay import OverlaySignal
from starboard_core.engagement.records import RunAuthorization
from starboard_core.engagement.run_id import is_run_id
from starboard_core.engagement.sink import (
    RUN_PROPERTY,
    AccessRecheckError,
    DriveRunSink,
    SinkConflictError,
)
from starboard_core.engagement.staging import (
    QUARANTINE_PROPERTY,
    ensure_staging,
    quarantine_staging,
)
from starboard_core.ports.engagement_storage import (
    Grant,
    StorageIntegrityError,
    StoragePermissionError,
)
from starboard_skills.helpers import engagement
from starboard_skills.helpers.contract import (
    EXIT_AUTH,
    ApiError,
    ArgError,
    AuthError,
)
from starboard_skills.helpers.engagement import _envelope, _runs

RUN_ID = "20261007_3f2b8c1e-4a5d-4e6f-8a7b-9c0d1e2f3a4b"
OVERLAY_ON = OverlaySignal(enabled=True, reasons=("internal_package",))
OVERLAY_OFF = OverlaySignal(enabled=False)
HOST = "https://acme.cloud.databricks.com"
USER_ME = {
    "id": "7001",
    "userName": "pat.operator@acme.example",
    "emails": [{"value": "pat.operator@acme.example", "primary": True}],
    "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
}
OWNER = (Grant("user", "owner", "databricks.com"),)
WIDE = (Grant("user", "owner", "databricks.com"), Grant("anyone", "reader"))
SHARED = (Grant("user", "owner", "databricks.com"), Grant("user", "reader", "x.com"))


class FakeWorkspace:
    """Fake ``WorkspaceClient``: ``config.host`` plus one SCIM ``Me`` call."""

    def __init__(
        self,
        workspace_id: str = "123",
        host: str = HOST,
        me: dict[str, Any] | None = None,
    ) -> None:
        self.config = SimpleNamespace(host=host, workspace_id=None)
        self.api_client = self
        self.calls: list[tuple[str, str, tuple[str, ...]]] = []
        self._workspace_id = workspace_id
        self._me = USER_ME if me is None else me

    def do(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        self.calls.append((method, path, tuple(kw.get("response_headers") or ())))
        return {**self._me, "X-Databricks-Org-Id": self._workspace_id}


@pytest.fixture(autouse=True)
def _in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A local run creates its run dir under the relative default reports root.
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def _no_shared_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(engagement.SHARED_REGISTRY_ENV, raising=False)


@pytest.fixture(autouse=True)
def store(monkeypatch: pytest.MonkeyPatch) -> InMemoryEngagementStorage:
    s = InMemoryEngagementStorage(owner_domain="databricks.com")
    monkeypatch.setattr(_envelope, "_make_storage", lambda: s)
    return s


@pytest.fixture
def ws(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Patch the workspace-client seam; ``ws.client`` may be replaced per test."""
    holder = SimpleNamespace(client=FakeWorkspace(), built=[])

    def make(profile: str | None, host: str | None) -> FakeWorkspace:
        holder.built.append((profile, host))
        return holder.client

    monkeypatch.setattr(_envelope, "_make_workspace_client", make)
    return holder


def _overlay(monkeypatch: pytest.MonkeyPatch, signal: OverlaySignal) -> None:
    monkeypatch.setattr(_envelope, "_detect_overlay", lambda: signal)


def _preflight(**kw: object) -> SimpleNamespace:
    base = {
        "source_mode": "customer_workspace",
        "storage": None,
        "task": "health_check",
        "task_name": "ws-123",
        "account_key": "001ABC",
        "account_name": "Acme Corp",
        "reports_root": None,
        "run_dir": None,
        "resume_run_id": None,
        "unattended": False,
    }
    if kw.get("source_mode") == "internal_only":  # D4-15: it declares its workspace
        base["internal_workspace_id"] = "123"
    return SimpleNamespace(**{**base, **kw})


def _resume(run_id: str, **kw: object) -> SimpleNamespace:
    blank = dict.fromkeys(("source_mode", "task", "task_name", "account_key"))
    return _preflight(**{**blank, "account_name": None, "resume_run_id": run_id, **kw})


def _target(pre: dict[str, Any]) -> dict[str, Any]:
    """A Drive run is addressed by ``run_id``; a local run by its run dir."""
    if pre["destination"] == "drive":
        return {"run_id": pre["run_id"], "run_dir": None}
    return {"run_id": None, "run_dir": pre["run_dir"]}


def _verify(pre: dict[str, Any], **kw: object) -> SimpleNamespace:
    base = {
        **_target(pre),
        "profile": "acme",
        "host": None,
        "account_key": "001ABC",
        "account_name": None,
        "account_source": "operator",
        "workspace_id": None,
        "expected_host": None,
    }
    return SimpleNamespace(**{**base, **kw})


def _route(pre: dict[str, Any] | None, **kw: object) -> SimpleNamespace:
    base = {
        **({"run_id": None, "run_dir": None} if pre is None else _target(pre)),
        "account_key": "001ABC",
        "account_name": None,
        "ticket_ref": None,
        "shared_root_id": None,
        "override_folder_id": None,
        "internal_domain": None,
        "unattended": False,
    }
    return SimpleNamespace(**{**base, **kw})


def _commit(
    run_folder_id: str, stage: str = "capture", **kw: object
) -> SimpleNamespace:
    base = {
        "run_folder": run_folder_id,
        "stage": stage,
        "state": "complete",
        "note": None,
    }
    return SimpleNamespace(**{**base, **kw})


def _drive_pre(monkeypatch: pytest.MonkeyPatch, **kw: object) -> dict[str, Any]:
    _overlay(monkeypatch, OVERLAY_ON)
    return engagement.cmd_preflight(_preflight(**kw))


def _local_pre(monkeypatch: pytest.MonkeyPatch, **kw: object) -> dict[str, Any]:
    _overlay(monkeypatch, OVERLAY_OFF)
    return engagement.cmd_preflight(_preflight(**kw))


def _verified(monkeypatch: pytest.MonkeyPatch, **kw: object) -> dict[str, Any]:
    pre = _drive_pre(monkeypatch, **kw)
    engagement.cmd_verify_identity(_verify(pre))
    return pre


def _routed(
    monkeypatch: pytest.MonkeyPatch, **kw: object
) -> tuple[dict[str, Any], dict[str, Any]]:
    pre = _verified(monkeypatch, **kw)
    return pre, engagement.cmd_route(_route(pre))


def _staging_children(
    store: InMemoryEngagementStorage, pre: dict[str, Any]
) -> set[str]:
    return {c.name for c in store.list_children(pre["staging_folder_id"])}


def _staged(store: InMemoryEngagementStorage, pre: dict[str, Any], name: str) -> bytes:
    (obj,) = store.list_children(pre["staging_folder_id"], name=name)
    return b"".join(store.get_stream(obj.id))


def _sink(store: InMemoryEngagementStorage, run_folder_id: str) -> DriveRunSink:
    auth, _ = read_descriptor(store, run_folder_id)
    assert auth.drive is not None
    return DriveRunSink(
        store,
        run_folder_id,
        run_id=auth.run_id,
        access_fingerprint=auth.drive.permission_fingerprints[run_folder_id],
    )


def _no_local_tree(tmp_path: Path) -> None:
    assert not (tmp_path / "starboard-reports").exists()


# --------------------------------------------------------------------------- #
# preflight
# --------------------------------------------------------------------------- #


class TestPreflight:
    def test_overlay_customer_is_drive_required_without_local_records(
        self, monkeypatch, tmp_path
    ):
        data = _drive_pre(monkeypatch)
        assert data["decision"]["policy"] == "drive_required"
        assert data["decision"]["drive_required"] is True
        assert data["destination"] == "drive"
        assert data["covered"] is True
        assert is_run_id(data["run_id"])
        assert data["overlay"] == {"enabled": True, "reasons": ["internal_package"]}
        assert "advisory_warning" not in data
        assert data["local_file_intake_allowed"] is False
        assert data["local_file_intake_guidance"]
        assert data["run_dir"] is None and data["preflight_record"] is None
        _no_local_tree(tmp_path)

    def test_overlay_local_request_is_refused(self, monkeypatch, store, tmp_path):
        with pytest.raises(LocalStorageRefused):
            _drive_pre(monkeypatch, storage="local")
        assert store.object_count == 1
        _no_local_tree(tmp_path)

    def test_public_customer_is_local(self, monkeypatch, store):
        data = _local_pre(monkeypatch)
        assert data["decision"]["policy"] == "local"
        assert data["destination"] == "local"
        assert data["covered"] is False
        assert "advisory_warning" not in data
        assert data["local_file_intake_allowed"] is True
        assert data["local_file_intake_guidance"] is None

    def test_public_drive_request_is_optional_drive(self, monkeypatch):
        data = _local_pre(monkeypatch, storage="drive")
        assert data["decision"]["policy"] == "drive_optional"
        assert data["destination"] == "drive"
        assert data["staging_folder_id"]

    def test_internal_only_defaults_to_drive_and_allows_local(self, monkeypatch):
        default = _drive_pre(monkeypatch, source_mode="internal_only")
        assert default["decision"]["policy"] == "drive_default"
        assert default["destination"] == "drive"
        local = _drive_pre(monkeypatch, source_mode="internal_only", storage="local")
        assert local["decision"]["policy"] == "internal_only_local"
        assert local["destination"] == "local"
        assert Path(local["preflight_record"]).is_file()

    def test_unknown_source_mode_is_arg_error(self, monkeypatch):
        with pytest.raises(ArgError):
            _local_pre(monkeypatch, source_mode="nope")

    def test_account_key_is_required(self, monkeypatch):
        with pytest.raises(ArgError):
            _drive_pre(monkeypatch, account_key=None)

    def test_drive_path_matches_the_route(self, monkeypatch):
        data = _drive_pre(monkeypatch)
        run_id = data["run_id"]
        assert data["drive_path"] == (
            f"My Drive/starboard/Acme Corp/health_check/ws-123/{run_id}"
        )
        assert data["created_at"].endswith("+00:00")

    def test_local_run_creates_the_run_dir(self, monkeypatch):
        data = _local_pre(monkeypatch)
        run_id = data["run_id"]
        assert data["case_root"] == "starboard-reports/acme-corp/health_check/ws-123"
        assert data["run_dir"] == f"{data['case_root']}/{run_id}"
        assert data["local_run_dir"] == data["run_dir"]
        record = Path(data["run_dir"]) / "analysis" / "storage-preflight.json"
        assert data["preflight_record"] == record.as_posix()
        saved = json.loads(record.read_text())
        assert saved["run_id"] == run_id
        assert saved["task"] == "health_check"

    def test_local_destination_has_no_drive_path_or_staging(self, monkeypatch, store):
        data = _local_pre(monkeypatch)
        assert data["destination"] == "local"
        assert data["drive_path"] is None
        assert data["staging_folder_id"] is None
        assert data["staging_link"] is None
        assert data["drive_principal"] is None
        assert data["idempotency_key"].startswith("sbk1_")
        assert store.object_count == 1  # no Drive object touched

    def test_drive_preflight_stages_the_record(self, monkeypatch, store, tmp_path):
        data = _drive_pre(monkeypatch)
        staging = store.get(data["staging_folder_id"])
        assert staging.name == data["run_id"]
        parent = store.get(staging.parent_ids[0])
        assert parent.name == "_preflight"
        assert data["staging_link"] == staging.web_link
        assert data["drive_principal"] == "perm-owner-0001"
        assert data["idempotency_key"].startswith("sbk1_")
        (obj,) = store.list_children(staging.id, name="storage-preflight.json")
        assert (
            obj.properties[engagement.ARTIFACT_PROPERTY]
            == f"preflight:{data['run_id']}"
        )
        staged = json.loads(b"".join(store.get_stream(obj.id)))
        assert staged["run_id"] == data["run_id"]
        assert staged["staging_folder_id"] == data["staging_folder_id"]
        assert staged["idempotency_key"] == data["idempotency_key"]
        _no_local_tree(tmp_path)

    def test_staging_not_restricted_stops(self, monkeypatch, store):
        store.set_access(store.root_folder_id(), grants=WIDE)
        with pytest.raises(ApiError) as exc:
            _drive_pre(monkeypatch)
        assert "not restricted" in exc.value.message
        assert "--resume-run-id" in exc.value.message

    def test_resume_reuses_run_id_key_and_staging(self, monkeypatch, store):
        first = _drive_pre(monkeypatch)
        count = store.object_count
        again = engagement.cmd_preflight(_resume(first["run_id"]))
        assert again["resumed"] is True
        for key in ("run_id", "idempotency_key", "staging_folder_id", "drive_path"):
            assert again[key] == first[key]
        assert store.object_count == count

    def test_resume_after_staging_failure(self, monkeypatch, store):
        store.set_access(store.root_folder_id(), grants=WIDE)
        with pytest.raises(ApiError) as exc:
            _drive_pre(monkeypatch)
        match = re.search(r"--resume-run-id (\S+)`", exc.value.message)
        assert match is not None
        run_id = match.group(1)
        store.set_access(store.root_folder_id(), grants=OWNER)
        data = engagement.cmd_preflight(_preflight(resume_run_id=run_id))
        assert data["run_id"] == run_id
        assert data["staging_folder_id"]
        staged = json.loads(_staged(store, data, "storage-preflight.json"))
        assert staged["staging_folder_id"] == data["staging_folder_id"]

    def test_resume_with_different_args_is_arg_error(self, monkeypatch):
        first = _drive_pre(monkeypatch)
        with pytest.raises(ArgError):
            engagement.cmd_preflight(_resume(first["run_id"], task="discovery"))
        with pytest.raises(ArgError):
            engagement.cmd_preflight(_resume(first["run_id"], account_name="Other Co"))

    def test_resume_refuses_storage_and_local_flags(self, monkeypatch):
        first = _drive_pre(monkeypatch)
        for flags in ({"storage": "drive"}, {"run_dir": "x"}, {"reports_root": "y"}):
            with pytest.raises(ArgError):
                engagement.cmd_preflight(_resume(first["run_id"], **flags))

    def test_resume_strips_the_given_flags(self, monkeypatch):
        first = _drive_pre(monkeypatch)
        again = engagement.cmd_preflight(
            _resume(first["run_id"], account_name="  Acme Corp  ", task_name=" ws-123 ")
        )
        assert again["resumed"] is True
        assert again["account_name"] == "Acme Corp"

    def test_resume_of_an_unknown_run_is_arg_error(self, monkeypatch, store):
        _overlay(monkeypatch, OVERLAY_ON)
        with pytest.raises(ArgError) as exc:
            engagement.cmd_preflight(_resume(RUN_ID))
        assert "unknown run" in exc.value.message
        assert store.object_count == 1

    def test_resume_of_a_quarantined_run_is_refused(self, monkeypatch, ws):
        pre = _drive_pre(monkeypatch)
        ws.client = FakeWorkspace(workspace_id="999")
        with pytest.raises(ApiError):
            engagement.cmd_verify_identity(_verify(pre))
        with pytest.raises(ApiError) as exc:
            engagement.cmd_preflight(_resume(pre["run_id"]))
        assert "quarantined" in exc.value.message

    def test_unattended_local_override_is_refused(self, monkeypatch):
        with pytest.raises(LocalStorageRefused):
            _drive_pre(monkeypatch, storage="local", unattended=True)

    def test_unattended_missing_drive_auth_is_error_without_prompt(
        self, monkeypatch, store
    ):
        store.auth_failed = True
        with pytest.raises(AuthError) as exc:
            _drive_pre(monkeypatch, unattended=True)
        assert exc.value.exit_code == EXIT_AUTH
        assert "gcloud auth login" not in exc.value.message
        assert "unattended" in exc.value.message

    def test_interactive_missing_drive_auth_has_hint(self, monkeypatch, store):
        store.auth_failed = True
        with pytest.raises(AuthError) as exc:
            _drive_pre(monkeypatch)
        assert "gcloud auth login" in exc.value.message

    def test_staging_read_back_failure_is_api_error(self, monkeypatch, store):
        store.corrupt_get_stream = lambda b: b + b"!"
        with pytest.raises(ApiError) as exc:
            _drive_pre(monkeypatch)
        assert "read-back" in exc.value.message

    def test_task_selects_the_case_tree(self, monkeypatch):
        kw = {
            "task": "troubleshooting",
            "task_name": "job-987",
            "account_name": "LM Arena",
        }
        drive = _drive_pre(monkeypatch, **kw)
        assert drive["drive_path"].startswith(
            "My Drive/starboard/LM Arena/troubleshooting/job-987/"
        )
        local = _local_pre(monkeypatch, **kw)
        assert (
            local["case_root"] == "starboard-reports/lm-arena/troubleshooting/job-987"
        )

    def test_prompt_supplied_run_dir_is_used_as_given(self, monkeypatch, tmp_path):
        target = tmp_path / "elsewhere" / "my-run"
        data = _local_pre(monkeypatch, run_dir=str(target))
        assert data["run_dir"] == target.as_posix()
        assert (target / "analysis" / "storage-preflight.json").is_file()

    def test_existing_preflight_record_is_not_overwritten(self, monkeypatch, tmp_path):
        target = tmp_path / "run"
        _local_pre(monkeypatch, run_dir=str(target))
        with pytest.raises(ArgError):
            _local_pre(monkeypatch, run_dir=str(target))

    @pytest.mark.parametrize(
        "bad", ["ws-123-2026-10-07 x", "ws/123", "123", "", "WS-123"]
    )
    def test_task_name_must_be_a_stable_case_name(self, monkeypatch, bad):
        with pytest.raises(ArgError):
            _local_pre(monkeypatch, task_name=bad)

    def test_blank_account_name_is_arg_error(self, monkeypatch):
        with pytest.raises(ArgError):
            _local_pre(monkeypatch, account_name="  ")


# --------------------------------------------------------------------------- #
# verify-identity
# --------------------------------------------------------------------------- #


def _identity_file(pre: dict[str, Any]) -> Path:
    return Path(pre["run_dir"]) / "analysis" / "identity-check.json"


class TestVerifyIdentity:
    def test_verified_on_drive_records_only_in_staging(
        self, monkeypatch, store, ws, tmp_path
    ):
        pre = _drive_pre(monkeypatch)
        data = engagement.cmd_verify_identity(_verify(pre))
        assert data["status"] == "verified"
        assert data["expected_workspace_id"] == "123"
        assert data["observed_workspace_id"] == "123"
        assert data["observed_host"] == HOST
        assert data["principal_kind"] == "user"
        assert data["reasons"] == []
        assert ws.built == [("acme", None)]
        assert ws.client.calls == [
            ("GET", "/api/2.0/preview/scim/v2/Me", ("X-Databricks-Org-Id",))
        ]
        text = _staged(store, pre, "identity-check.json").decode()
        (obj,) = store.list_children(
            pre["staging_folder_id"], name="identity-check.json"
        )
        assert data["identity_check"] == f"drive:{obj.id}"
        record = json.loads(text)
        assert record["principal_id"] == "7001"
        assert record["provisional_account_key"] == "001ABC"
        assert "acme.example" not in text and "pat.operator" not in text
        _no_local_tree(tmp_path)

    @pytest.mark.parametrize(
        "me",
        [
            {
                "id": "8001",
                "userName": "app",
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServicePrincipal"],
            },
            {"id": "8002", "userName": "0f1e2d3c-4b5a-4968-8776-655443322110"},
            {"id": "8003", "applicationId": "0f1e2d3c-4b5a-4968-8776-655443322110"},
        ],
    )
    def test_service_principal_is_detected(self, monkeypatch, ws, me):
        ws.client = FakeWorkspace(me=me)
        pre = _drive_pre(monkeypatch)
        data = engagement.cmd_verify_identity(_verify(pre))
        assert data["principal_kind"] == "service_principal"

    def test_uuid_user_name_with_emails_is_a_user(self, monkeypatch, ws):
        ws.client = FakeWorkspace(
            me={
                "id": "8004",
                "userName": "0f1e2d3c-4b5a-4968-8776-655443322110",
                "emails": [{"value": "a@b.example"}],
            }
        )
        pre = _drive_pre(monkeypatch)
        assert engagement.cmd_verify_identity(_verify(pre))["principal_kind"] == "user"

    def test_identity_mismatch_on_drive_quarantines(self, monkeypatch, store, ws):
        pre = _drive_pre(monkeypatch)
        ws.client = FakeWorkspace(workspace_id="999")
        with pytest.raises(engagement.IdentityMismatch) as exc:
            engagement.cmd_verify_identity(_verify(pre))
        assert exc.value.exit_code == engagement.EXIT_IDENTITY
        assert "workspace id differs" in exc.value.message
        assert "quarantine" in exc.value.message
        staging = store.get(pre["staging_folder_id"])
        parent = store.get(staging.parent_ids[0])
        assert parent.name == "_quarantine"
        assert store.get(parent.parent_ids[0]).name == "_preflight"
        assert "workspace id differs" in staging.properties[QUARANTINE_PROPERTY]
        record = json.loads(_staged(store, pre, "identity-check.json"))
        assert record["status"] == "mismatch"

    def test_local_mismatch_errors_after_writing_the_record(
        self, monkeypatch, store, ws
    ):
        pre = _local_pre(monkeypatch)
        ws.client = FakeWorkspace(workspace_id="999")
        with pytest.raises(ApiError) as exc:
            engagement.cmd_verify_identity(_verify(pre))
        assert "workspace id differs" in exc.value.message
        assert json.loads(_identity_file(pre).read_text())["status"] == "mismatch"
        assert store.object_count == 1  # no Drive call on a local run

    def test_local_verified_has_no_staging(self, monkeypatch, store, ws):
        pre = _local_pre(monkeypatch)
        data = engagement.cmd_verify_identity(_verify(pre))
        assert data["status"] == "verified"
        assert data["staging_folder_id"] is None
        assert data["identity_check"] == _identity_file(pre).as_posix()
        assert store.object_count == 1

    def test_run_id_and_run_dir_are_exclusive(self, monkeypatch, ws):
        pre = _drive_pre(monkeypatch)
        with pytest.raises(ArgError):
            engagement.cmd_verify_identity(_verify(pre, run_dir="x"))
        with pytest.raises(ArgError):
            engagement.cmd_verify_identity(_verify(pre, run_id=None))

    def test_host_mismatch_is_a_mismatch(self, monkeypatch, ws):
        pre = _drive_pre(monkeypatch)
        with pytest.raises(ApiError) as exc:
            engagement.cmd_verify_identity(
                _verify(pre, expected_host="https://other.cloud.databricks.com/")
            )
        assert "host differs" in exc.value.message

    def test_workspace_id_flag_is_the_expected_id(self, monkeypatch, ws):
        pre = _drive_pre(monkeypatch, task="troubleshooting", task_name="job-987")
        data = engagement.cmd_verify_identity(_verify(pre, workspace_id="123"))
        assert data["expected_workspace_id"] == "123"

    def test_no_expected_workspace_id_is_arg_error(self, monkeypatch, ws):
        pre = _drive_pre(monkeypatch, task="troubleshooting", task_name="job-987")
        with pytest.raises(ArgError):
            engagement.cmd_verify_identity(_verify(pre))
        assert ws.client.calls == []

    def test_workspace_id_disagreeing_with_task_name_is_arg_error(
        self, monkeypatch, ws
    ):
        pre = _drive_pre(monkeypatch)
        with pytest.raises(ArgError):
            engagement.cmd_verify_identity(_verify(pre, workspace_id="456"))
        with pytest.raises(ArgError):
            engagement.cmd_verify_identity(_verify(pre, workspace_id="12x"))

    def test_internal_only_run_is_arg_error(self, monkeypatch, ws):
        pre = _drive_pre(monkeypatch, source_mode="internal_only")
        with pytest.raises(ArgError):
            engagement.cmd_verify_identity(_verify(pre))

    def test_needs_profile_or_host(self, monkeypatch, ws):
        pre = _drive_pre(monkeypatch)
        with pytest.raises(ArgError):
            engagement.cmd_verify_identity(_verify(pre, profile=None))
        with pytest.raises(ArgError):
            engagement.cmd_verify_identity(_verify(pre, host=HOST))

    def test_host_is_passed_to_the_seam(self, monkeypatch, ws):
        pre = _drive_pre(monkeypatch)
        engagement.cmd_verify_identity(_verify(pre, profile=None, host=HOST))
        assert ws.built == [(None, HOST)]

    def test_account_disagreeing_with_preflight_is_arg_error(self, monkeypatch, ws):
        pre = _drive_pre(monkeypatch)
        with pytest.raises(ArgError):
            engagement.cmd_verify_identity(_verify(pre, account_name="Other Co"))
        with pytest.raises(ArgError):
            engagement.cmd_verify_identity(_verify(pre, account_key="001XYZ"))

    def test_quarantined_staging_stops_before_the_workspace_call(self, monkeypatch, ws):
        pre = _drive_pre(monkeypatch)
        ws.client = FakeWorkspace(workspace_id="999")
        with pytest.raises(ApiError):
            engagement.cmd_verify_identity(_verify(pre))
        ws.client = FakeWorkspace()
        with pytest.raises(ApiError) as exc:
            engagement.cmd_verify_identity(_verify(pre))
        assert "quarantined" in exc.value.message
        assert ws.client.calls == []

    def test_quarantine_that_does_not_read_back_is_api_error(
        self, monkeypatch, store, ws
    ):
        pre = _drive_pre(monkeypatch)
        ws.client = FakeWorkspace(workspace_id="999")
        store.drop_updates = True
        with pytest.raises(ApiError) as exc:
            engagement.cmd_verify_identity(_verify(pre))
        assert "read-back" in exc.value.message


# --------------------------------------------------------------------------- #
# route
# --------------------------------------------------------------------------- #


def _ticket_ref(tmp_path: Path, **overrides: object) -> str:
    ref = {
        "schema_version": "1",
        "input_token": "ASQ-000000001",
        "ar_key": "AR-000000001",
        "record_id": "a0X000000000001",
        "object_name": "ApprovalRequest__c",
        "title": "Cost review",
        "account_id": "001ABC",
        "account_name": "Acme Corp",
        "status_value": "Closed",
        "looked_up_at": "2026-10-07T00:00:00Z",
        "resolution": "validated",
        "reason": "single record, account matches",
    }
    ref.update(overrides)
    path = tmp_path / "ticket.json"
    path.write_text(json.dumps({"soql": "SELECT ...", "ticket_ref": ref}))
    return str(path)


def _shared_root(store: InMemoryEngagementStorage) -> str:
    return store.add_shared_drive(
        "asqs-root",
        "ASQs",
        drive_id="d1",
        grants=(Grant("group", "fileOrganizer", "databricks.com"),),
    ).id


def _authorization_file(pre: dict[str, Any]) -> Path:
    return Path(pre["run_dir"]) / "analysis" / "run-authorization.json"


def _account_run_folder(store: InMemoryEngagementStorage, pre: dict[str, Any]) -> str:
    """Create the account route's folders ahead of ``route`` so a test can share them."""
    return resolve_account_route(
        store,
        account_key="001ABC",
        account_name=pre["account_name"],
        task=pre["task"],
        task_name=pre["task_name"],
        run_id=pre["run_id"],
    ).run_folder_id


def _run_child(store: InMemoryEngagementStorage, run: str, path: str) -> bytes:
    parent = run
    *dirs, name = path.split("/")
    for part in dirs:
        (sub,) = store.list_children(parent, name=part, folders_only=True)
        parent = sub.id
    (obj,) = store.list_children(parent, name=name)
    return b"".join(store.get_stream(obj.id))


class TestRoute:
    def test_account_route_writes_descriptor_and_manifest(
        self, monkeypatch, store, ws, tmp_path
    ):
        pre, data = _routed(monkeypatch)
        run_id = pre["run_id"]
        assert data["route"] == "account"
        assert data["path"] == pre["drive_path"]
        run = store.get(data["run_folder_id"])
        assert run.name == run_id
        assert data["fallback_warning"] is None
        assert data["ticket"] is None
        assert data["destination"] == "drive"
        assert data["authorized_scope"] == {
            "account_key": "001ABC",
            "workspace_ids": ["123"],
            "basis": "verified",
        }
        assert data["manifest_revision"] == 1
        auth, desc = read_descriptor(store, data["run_folder_id"])
        assert data["descriptor_id"] == desc.id
        assert auth.drive is not None
        assert auth.drive.preflight_folder_id == pre["staging_folder_id"]
        assert auth.drive.idempotency_key == pre["idempotency_key"]
        assert auth.drive.principal == "perm-owner-0001"
        assert auth.drive.acl_classification == "owner_only"
        assert auth.drive.registry_folder_id == data["registry_folder_id"]
        assert store.get(data["registry_folder_id"]).name == "_registry"
        fp = store.inspect_access(data["run_folder_id"]).fingerprint
        assert auth.drive.permission_fingerprints == {data["run_folder_id"]: fp}
        assert auth.account.verifier == "identity_check"
        manifest, mobj = latest_manifest(store, data["run_folder_id"])
        assert data["manifest_id"] == mobj.id
        assert manifest.revision == 1
        assert [r.path for r in manifest.refs] == ["analysis/identity-check.json"]
        assert dict(manifest.states) == {
            "capture": "pending",
            "analysis": "pending",
            "check": "pending",
            "publication": "pending",
        }
        ident = _run_child(store, data["run_folder_id"], "analysis/identity-check.json")
        assert ident == _staged(store, pre, "identity-check.json")
        # Covered runs keep no local descriptor copy.
        assert data["run_authorization"] is None
        _no_local_tree(tmp_path)

    def test_local_run_authorization_round_trips_through_discovery_loader(
        self, monkeypatch, ws
    ):
        from starboard_x.discovery._authorization import (
            AUTHORIZATION_RELPATH,
            load_authorized_workspace_ids,
        )

        pre = _local_pre(monkeypatch)
        engagement.cmd_verify_identity(_verify(pre))
        data = engagement.cmd_route(_route(pre))
        assert (Path(pre["run_dir"]) / AUTHORIZATION_RELPATH).as_posix() == data[
            "run_authorization"
        ]
        assert load_authorized_workspace_ids(pre["run_dir"]) == ("123",)
        saved = json.loads(_authorization_file(pre).read_text())
        auth = RunAuthorization.from_dict(saved)
        assert auth.to_dict() == saved
        assert auth.run_id == pre["run_id"]

    def test_route_is_idempotent(self, monkeypatch, store, ws):
        pre, first = _routed(monkeypatch)
        count = store.object_count
        second = engagement.cmd_route(_route(pre))
        assert second["run_folder_id"] == first["run_folder_id"]
        assert second["descriptor_id"] == first["descriptor_id"]
        assert second["manifest_revision"] == 1
        assert second["manifest_id"] == first["manifest_id"]
        assert second["registration_id"] == first["registration_id"]
        assert store.object_count == count

    def test_refuses_without_identity_check(self, monkeypatch, store, ws):
        pre = _drive_pre(monkeypatch)
        count = store.object_count
        with pytest.raises(ArgError) as exc:
            engagement.cmd_route(_route(pre))
        assert "verify-identity first" in exc.value.message
        assert store.object_count == count

    def test_refuses_a_mismatch_check(self, monkeypatch, ws):
        pre = _local_pre(monkeypatch)
        ws.client = FakeWorkspace(workspace_id="999")
        with pytest.raises(ApiError):
            engagement.cmd_verify_identity(_verify(pre))
        with pytest.raises(ArgError) as exc:
            engagement.cmd_route(_route(pre))
        assert "verify-identity first" in exc.value.message

    def test_refuses_the_wrong_account(self, monkeypatch, ws):
        pre = _verified(monkeypatch)
        with pytest.raises(ArgError) as exc:
            engagement.cmd_route(_route(pre, account_key="001XYZ"))
        assert "verify-identity first" in exc.value.message or "account" in (
            exc.value.message
        )

    def test_refuses_a_local_check_from_another_run(self, monkeypatch, ws, tmp_path):
        other = _local_pre(monkeypatch, run_dir=str(tmp_path / "other"))
        engagement.cmd_verify_identity(_verify(other))
        pre = _local_pre(monkeypatch)
        shutil.copy(_identity_file(other), _identity_file(pre))
        with pytest.raises(ArgError) as exc:
            engagement.cmd_route(_route(pre))
        assert "verify-identity first" in exc.value.message

    def test_refuses_a_staged_check_from_another_run(self, monkeypatch, store, ws):
        other = _verified(monkeypatch)
        pre = _drive_pre(monkeypatch)
        body = _staged(store, other, "identity-check.json")
        store.put_stream(
            pre["staging_folder_id"],
            "identity-check.json",
            "application/json",
            [body],
            properties={engagement.ARTIFACT_PROPERTY: f"identity:{pre['run_id']}"},
        )
        with pytest.raises(ArgError) as exc:
            engagement.cmd_route(_route(pre))
        assert "verify-identity first" in exc.value.message

    def test_local_destination_writes_only_the_local_record(
        self, monkeypatch, store, ws
    ):
        pre = _local_pre(monkeypatch)
        engagement.cmd_verify_identity(_verify(pre))
        data = engagement.cmd_route(_route(pre))
        assert store.object_count == 1
        assert data["destination"] == "local"
        assert data["descriptor_id"] is None
        assert data["manifest_revision"] is None
        assert data["run_folder_id"] is None
        assert data["registry_folder_id"] is None
        saved = json.loads(_authorization_file(pre).read_text())
        assert saved["drive"] is None
        assert saved["authorized_scope"]["workspace_ids"] == ["123"]
        assert (
            engagement.cmd_route(_route(pre))["run_authorization"]
            == data["run_authorization"]
        )

    def test_internal_only_needs_no_identity_check(self, monkeypatch, store):
        pre = _drive_pre(monkeypatch, source_mode="internal_only")
        data = engagement.cmd_route(_route(pre))
        assert data["authorized_scope"]["account_key"] == "001ABC"
        # D4-15: the declared workspace, no identity check.
        assert list(data["authorized_scope"]["workspace_ids"]) == ["123"]
        assert data["authorized_scope"]["basis"] == "declared"
        manifest, _ = latest_manifest(store, data["run_folder_id"])
        assert manifest.refs == ()
        auth, _ = read_descriptor(store, data["run_folder_id"])
        assert auth.account.verifier == "operator"

    def test_a_run_target_is_required(self, ws):
        with pytest.raises(ArgError):
            engagement.cmd_route(_route(None))

    def test_unknown_run_id_is_arg_error(self, monkeypatch, store, ws):
        _overlay(monkeypatch, OVERLAY_ON)
        with pytest.raises(ArgError):
            engagement.cmd_route(_route(None, run_id=RUN_ID))
        assert store.object_count == 1

    def test_missing_account_key_uses_the_preflight_key(self, monkeypatch, ws):
        pre = _verified(monkeypatch)
        data = engagement.cmd_route(_route(pre, account_key=None))
        assert data["account_key"] == "001ABC"

    def test_auth_error_maps_to_auth_with_hint(self, monkeypatch, store, ws):
        pre = _verified(monkeypatch)
        store.auth_failed = True
        with pytest.raises(AuthError) as exc:
            engagement.cmd_route(_route(pre))
        assert exc.value.exit_code == EXIT_AUTH
        assert "gcloud auth login" in exc.value.message

    def test_validated_ticket_routes_to_shared_root(
        self, monkeypatch, store, ws, tmp_path
    ):
        pre = _verified(monkeypatch)
        data = engagement.cmd_route(
            _route(
                pre,
                account_key=None,
                ticket_ref=_ticket_ref(tmp_path),
                shared_root_id=_shared_root(store),
                internal_domain=["databricks.com"],
            )
        )
        assert data["route"] == "ticket"
        assert "AR-000000001: Cost review" in data["path"]
        assert data["ticket"]["ar_key"] == "AR-000000001"
        assert data["ticket"]["status_value"] == "Closed"
        assert "input_token" not in data["ticket"]
        assert data["ticket_warning"] is None
        auth, _ = read_descriptor(store, data["run_folder_id"])
        assert auth.drive is not None
        assert auth.drive.acl_classification == "internal_only"
        assert auth.ticket is not None and "input_token" not in auth.ticket
        # The operator registry, never the shared ticket tree (E2).
        registry = store.get(auth.drive.registry_folder_id)
        assert registry.name == "_registry"
        assert data["run_folder_id"] not in registry.parent_ids

    def test_unwritable_shared_root_falls_back_with_warning(
        self, monkeypatch, store, ws, tmp_path
    ):
        pre = _verified(monkeypatch)
        shared = _shared_root(store)
        store.set_access(shared, can_add_children=False)
        data = engagement.cmd_route(
            _route(
                pre,
                ticket_ref=_ticket_ref(tmp_path),
                shared_root_id=shared,
                internal_domain=["databricks.com"],
            )
        )
        assert data["route"] == "account"
        assert data["fallback_warning"]
        assert data["path"].startswith("My Drive/starboard/")
        auth, _ = read_descriptor(store, data["run_folder_id"])
        assert auth.drive is not None
        assert auth.drive.fallback_warning == data["fallback_warning"]

    def test_unattended_fallback_is_error_before_the_descriptor(
        self, monkeypatch, store, ws, tmp_path
    ):
        pre = _verified(monkeypatch)
        shared = _shared_root(store)
        store.set_access(shared, can_add_children=False)
        with pytest.raises(ArgError) as exc:
            engagement.cmd_route(
                _route(
                    pre,
                    ticket_ref=_ticket_ref(tmp_path),
                    shared_root_id=shared,
                    internal_domain=["databricks.com"],
                    unattended=True,
                )
            )
        assert "approved destination" in exc.value.message
        run = _account_run_folder(store, pre)
        assert store.list_children(run, name="run-authorization.json") == []

    def test_unattended_preflight_carries_to_route(
        self, monkeypatch, store, ws, tmp_path
    ):
        pre = _verified(monkeypatch, unattended=True)
        with pytest.raises(ArgError):
            engagement.cmd_route(
                _route(
                    pre,
                    ticket_ref=_ticket_ref(
                        tmp_path, resolution="mismatch", reason="account differs"
                    ),
                )
            )

    def test_unvalidated_ticket_uses_account_route_and_warns(
        self, monkeypatch, ws, tmp_path
    ):
        pre = _verified(monkeypatch)
        data = engagement.cmd_route(
            _route(
                pre,
                ticket_ref=_ticket_ref(
                    tmp_path, resolution="mismatch", reason="account differs"
                ),
            )
        )
        assert data["route"] == "account"
        assert "mismatch" in data["ticket_warning"]

    def test_validated_ticket_needs_shared_root_and_domain(
        self, monkeypatch, ws, tmp_path
    ):
        pre = _verified(monkeypatch)
        with pytest.raises(ArgError):
            engagement.cmd_route(_route(pre, ticket_ref=_ticket_ref(tmp_path)))
        with pytest.raises(ArgError):
            engagement.cmd_route(
                _route(pre, ticket_ref=_ticket_ref(tmp_path), shared_root_id="x")
            )

    def test_quarantined_run_is_refused(self, monkeypatch, ws):
        pre = _drive_pre(monkeypatch)
        ws.client = FakeWorkspace(workspace_id="999")
        with pytest.raises(ApiError):
            engagement.cmd_verify_identity(_verify(pre))
        with pytest.raises(engagement.RunQuarantined):
            engagement.cmd_route(_route(pre))

    @pytest.mark.parametrize(
        "grants",
        [
            (Grant("anyone", "reader"),),
            (Grant("user", "reader", "customer.example"),),
            (Grant("domain", "reader", "customer.example"),),
            (Grant("user", "reader", "databricks.com"),),  # no --internal-domain
        ],
    )
    def test_account_route_refuses_a_shared_run_folder(
        self, monkeypatch, store, ws, grants
    ):
        pre = _verified(monkeypatch)
        run = _account_run_folder(store, pre)
        store.set_access(run, grants=grants)
        internal = None if grants[0].domain == "databricks.com" else ["databricks.com"]
        with pytest.raises(ApiError) as exc:
            engagement.cmd_route(_route(pre, internal_domain=internal))
        assert "not internal-only" in exc.value.message
        assert store.list_children(run, name="run-authorization.json") == []

    def test_account_route_refuses_an_incomplete_acl(self, monkeypatch, store, ws):
        pre = _verified(monkeypatch)
        run = _account_run_folder(store, pre)
        store.set_access(run, complete=False)
        with pytest.raises(ApiError) as exc:
            engagement.cmd_route(_route(pre, internal_domain=["databricks.com"]))
        assert "unknown" in exc.value.message
        assert store.list_children(run, name="run-authorization.json") == []

    def test_account_route_accepts_internal_staff_grants(self, monkeypatch, store, ws):
        pre = _verified(monkeypatch)
        run = _account_run_folder(store, pre)
        store.set_access(run, grants=(Grant("user", "reader", "databricks.com"),))
        data = engagement.cmd_route(_route(pre, internal_domain=["databricks.com"]))
        assert data["run_folder_id"] == run
        auth, _ = read_descriptor(store, run)
        assert auth.drive is not None
        assert auth.drive.acl_classification == "internal_only"

    def test_reroute_after_an_acl_change_is_a_descriptor_conflict(
        self, monkeypatch, store, ws
    ):
        pre, routed = _routed(monkeypatch)
        run = routed["run_folder_id"]
        store.set_access(run, grants=(Grant("user", "reader", "databricks.com"),))
        with pytest.raises(ApiError) as exc:
            engagement.cmd_route(_route(pre, internal_domain=["databricks.com"]))
        assert "immutable" in exc.value.message
        assert "re-run `engagement route`" not in exc.value.message.lower()
        assert len(store.list_children(run, name="run-authorization.json")) == 1

    def test_corrupt_staged_identity_check_is_api_error(self, monkeypatch, store, ws):
        pre = _verified(monkeypatch)
        (obj,) = store.list_children(
            pre["staging_folder_id"], name="identity-check.json"
        )
        store.corrupt_object(obj.id)
        count = store.object_count
        with pytest.raises(ApiError):
            engagement.cmd_route(_route(pre))
        assert store.object_count == count

    def test_corrupt_local_identity_check_is_api_error(self, monkeypatch, store, ws):
        pre = _local_pre(monkeypatch)
        engagement.cmd_verify_identity(_verify(pre))
        _identity_file(pre).write_text("{not json")
        with pytest.raises(ApiError) as exc:
            engagement.cmd_route(_route(pre))
        assert "identity-check.json" in exc.value.message
        assert store.object_count == 1

    @pytest.mark.parametrize("fail_on", ["identity-check.json", "rev-000001.json"])
    def test_retry_after_a_failure_past_the_descriptor_converges(
        self, monkeypatch, store, ws, fail_on
    ):
        pre = _verified(monkeypatch)
        put = store.put_stream
        failed: list[str] = []

        def flaky(parent_id: str, name: str, *a: Any, **kw: Any):
            if name == fail_on and not failed:
                failed.append(name)
                raise StoragePermissionError("injected")
            return put(parent_id, name, *a, **kw)

        monkeypatch.setattr(store, "put_stream", flaky)
        with pytest.raises(ApiError):
            engagement.cmd_route(_route(pre))
        assert failed == [fail_on]
        data = engagement.cmd_route(_route(pre))
        run = data["run_folder_id"]
        assert data["manifest_revision"] == 1
        assert len(store.list_children(run, name="run-authorization.json")) == 1
        (folder,) = store.list_children(run, name="manifest", folders_only=True)
        assert [c.name for c in store.list_children(folder.id)] == ["rev-000001.json"]
        manifest, _ = latest_manifest(store, run)
        assert [r.path for r in manifest.refs] == ["analysis/identity-check.json"]


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ("001000000000001", "001000000000001AAA", True),
        ("001000000000001AAA", "001000000000001", True),
        ("001000000000001", "001000000000001", True),
        ("001000000000001AAA", "001000000000001BBB", False),
        ("001000000000001", "001000000000002AAA", False),
        ("1234567890123456", "1234567890123457", False),
        ("1234567890123456", "123456789012345", False),
        ("001000000000001", "001000000000001a", False),
    ],
)
def test_same_sf_id_prefix_rule_is_only_for_15_and_18_char_ids(a, b, same):
    assert _runs._same_sf_id(a, b) is same


def test_route_tells_16_digit_account_keys_apart(monkeypatch, ws):
    pre = _drive_pre(monkeypatch, account_key="1234567890123456")
    engagement.cmd_verify_identity(_verify(pre, account_key="1234567890123456"))
    with pytest.raises(ArgError):
        engagement.cmd_route(_route(pre, account_key="1234567890123457"))


# --------------------------------------------------------------------------- #
# commit (replaces the deleted ``upload``: artifacts are written to Drive by a
# DriveRunSink and ``commit`` records verified refs in a new manifest revision)
# --------------------------------------------------------------------------- #


def _fill(sink: DriveRunSink) -> dict[str, Any]:
    return {
        "README.md": sink.put_text("README.md", "# Run\n"),
        "deliverables/exec-summary.md": sink.put_text(
            "deliverables/exec-summary.md", "summary\n"
        ),
        "deliverables/chart.png": sink.put_bytes(
            "deliverables/chart.png", b"\x89PNG fake", mime_type="image/png"
        ),
    }


def _revisions(store: InMemoryEngagementStorage, run: str) -> list[str]:
    (folder,) = store.list_children(run, name="manifest", folders_only=True)
    return sorted(c.name for c in store.list_children(folder.id))


class TestCommit:
    def test_commit_records_sink_artifacts_and_extends_the_chain(
        self, monkeypatch, store, ws
    ):
        import hashlib

        _, routed = _routed(monkeypatch)
        run = routed["run_folder_id"]
        written = _fill(_sink(store, run))
        data = engagement.cmd_commit(_commit(run))
        assert data["revision"] == 2 and data["unchanged"] is False
        assert sorted(data["refs_added"]) == sorted(written)
        manifest, mobj = latest_manifest(store, run)
        assert data["manifest_object_id"] == mobj.id
        assert manifest.previous_object_id == routed["manifest_id"]
        refs = {r.path: r for r in manifest.refs}
        assert sorted(refs) == sorted([*written, "analysis/identity-check.json"])
        png = refs["deliverables/chart.png"]
        assert png.mime_type == "image/png"
        assert png.md5 == hashlib.md5(b"\x89PNG fake").hexdigest()
        assert png.size == len(b"\x89PNG fake")
        assert manifest.descriptor_ref.object_id == routed["descriptor_id"]
        # The descriptor and the staged records are never manifest refs.
        assert "run-authorization.json" not in refs
        assert "analysis/storage-preflight.json" not in refs
        # commit never touches publication (E1).
        assert dict(manifest.states) == {
            "capture": "complete",
            "analysis": "pending",
            "check": "pending",
            "publication": "pending",
        }

    def test_descriptor_ref_matches_the_descriptor_bytes(self, monkeypatch, store, ws):
        import hashlib

        pre, routed = _routed(monkeypatch)
        run = routed["run_folder_id"]
        engagement.cmd_commit(_commit(run))
        auth, desc = read_descriptor(store, run)
        body = b"".join(store.get_stream(desc.id))
        assert json.loads(body) == auth.to_dict()
        assert auth.run_id == pre["run_id"]
        manifest, _ = latest_manifest(store, run)
        assert manifest.descriptor_ref.md5 == hashlib.md5(body).hexdigest()
        assert manifest.descriptor_ref.size == len(body)

    def test_states_follow_the_committed_stages(self, monkeypatch, store, ws):
        _, routed = _routed(monkeypatch)
        run = routed["run_folder_id"]
        for stage in engagement.STAGES:
            engagement.cmd_commit(_commit(run, stage))
        manifest, _ = latest_manifest(store, run)
        assert {s: manifest.states[s] for s in engagement.STAGES} == dict.fromkeys(
            engagement.STAGES, "complete"
        )
        assert manifest.states["publication"] == "pending"
        failed = engagement.cmd_commit(_commit(run, "check", state="failed"))
        assert latest_manifest(store, run)[0].states["check"] == "failed"
        assert failed["revision"] == manifest.revision + 1

    def test_recommit_unchanged_is_skipped(self, monkeypatch, store, ws):
        _, routed = _routed(monkeypatch)
        run = routed["run_folder_id"]
        _fill(_sink(store, run))
        engagement.cmd_commit(_commit(run))
        count = store.object_count
        again = engagement.cmd_commit(_commit(run))
        assert again["unchanged"] is True and again["revision"] == 2
        assert again["refs_added"] == []
        assert store.object_count == count

    def test_changed_artifact_updates_in_place(self, monkeypatch, store, ws):
        _, routed = _routed(monkeypatch)
        run = routed["run_folder_id"]
        sink = _sink(store, run)
        first = _fill(sink)
        engagement.cmd_commit(_commit(run))
        second = sink.put_text("README.md", "# Run v2\n")
        assert second.object_id == first["README.md"].object_id
        assert second.revision != first["README.md"].revision
        engagement.cmd_commit(_commit(run))
        assert len(store.list_children(run, name="README.md")) == 1
        manifest, _ = latest_manifest(store, run)
        refs = {r.path: r for r in manifest.refs}
        assert manifest.revision == 3
        assert refs["README.md"].revision == second.revision
        assert "deliverables/chart.png" in refs  # carried from the prior revision

    def test_acl_changed_stops_before_any_write(self, monkeypatch, store, ws):
        _, routed = _routed(monkeypatch)
        run = routed["run_folder_id"]
        store.set_access(run, grants=SHARED)
        count = store.object_count
        with pytest.raises(AccessRecheckError) as exc:
            engagement.cmd_commit(_commit(run))
        assert "changed" in str(exc.value) and "blocked_access" in str(exc.value)
        assert store.object_count == count
        assert latest_manifest(store, run)[0].revision == 1

    def test_revoked_access_stops(self, monkeypatch, store, ws):
        _, routed = _routed(monkeypatch)
        run = routed["run_folder_id"]
        store.set_access(run, can_add_children=False)
        with pytest.raises(AccessRecheckError) as exc:
            engagement.cmd_commit(_commit(run))
        assert "revoked" in str(exc.value)

    def test_acl_changed_between_write_and_commit_writes_no_manifest(
        self, monkeypatch, store, ws
    ):
        _, routed = _routed(monkeypatch)
        run = routed["run_folder_id"]
        _fill(_sink(store, run))
        store.set_access(run, grants=SHARED)
        with pytest.raises(AccessRecheckError):
            engagement.cmd_commit(_commit(run))
        assert latest_manifest(store, run)[0].revision == 1

    def test_route_must_run_before_commit(self, monkeypatch, store, ws):
        _, routed = _routed(monkeypatch)
        run = routed["run_folder_id"]
        (desc,) = store.list_children(run, name="run-authorization.json")
        store.update(desc.id, name="moved.json")
        with pytest.raises(ApiError) as exc:
            engagement.cmd_commit(_commit(run))
        assert "descriptor" in exc.value.message

    def test_identical_manifest_twin_does_not_wedge_the_run(
        self, monkeypatch, store, ws
    ):
        # Run 13: a retried upload left two identical copies of one revision; every
        # later commit and status failed STORAGE_ERROR "concurrent writer".
        _, routed = _routed(monkeypatch)
        run = routed["run_folder_id"]
        store.duplicate_on_put.add("rev-000002.json")
        assert engagement.cmd_commit(_commit(run))["revision"] == 2
        engagement.cmd_commit(_commit(run))  # a later commit is not wedged
        assert latest_manifest(store, run)[0].revision == 2

    def test_differing_manifest_twin_is_api_error(self, monkeypatch, store, ws):
        _, routed = _routed(monkeypatch)
        run = routed["run_folder_id"]
        engagement.cmd_commit(_commit(run))
        (folder,) = store.list_children(run, name="manifest", folders_only=True)
        (rev,) = store.list_children(folder.id, name="rev-000002.json")
        store.put_stream(  # a second writer's different revision 2
            folder.id, "rev-000002.json", "application/json", [b"{}"],
            properties=dict(rev.properties),
        )
        with pytest.raises(ApiError) as exc:
            engagement.cmd_commit(_commit(run))
        assert "more than once" in exc.value.message

    def test_identical_duplicate_artifact_converges_with_a_warning(
        self, monkeypatch, store, ws
    ):
        # A retried upload left two identical copies: the run is not wedged.
        _, routed = _routed(monkeypatch)
        run = routed["run_folder_id"]
        store.duplicate_on_put.add("README.md")
        ref = _sink(store, run).put_text("README.md", "# Run\n")
        data = engagement.cmd_commit(_commit(run))
        assert data["revision"] == 2
        assert "README.md" in data["refs_added"]
        (note,) = [w for w in data["warnings"] if w.startswith("duplicate_artifact:")]
        assert ref.object_id in note
        manifest = latest_manifest(store, run)[0]
        assert {r.path: r.object_id for r in manifest.refs}[
            "README.md"
        ] == ref.object_id
        readmes = store.find_by_property(engagement.ARTIFACT_PROPERTY, "README.md")
        assert [o.id for o in readmes] == [ref.object_id]  # the twin is trashed

    def test_commit_lists_the_run_once_and_checks_access_once(
        self, monkeypatch, store, ws
    ):
        from collections import Counter

        _, routed = _routed(monkeypatch)
        run = routed["run_folder_id"]
        _fill(_sink(store, run))
        calls: Counter[str] = Counter()
        for name in ("find_by_property", "inspect_access", "list_children"):
            real = getattr(store, name)

            def counted(*a, _real=real, _name=name, **k):
                calls[_name] += 1
                return _real(*a, **k)

            monkeypatch.setattr(store, name, counted)
        engagement.cmd_commit(_commit(run))
        assert calls["find_by_property"] == 1
        assert calls["inspect_access"] == 1
        assert _runs._OPEN_SINKS == {}  # the command's index is dropped

    def test_differing_duplicate_artifact_objects_are_api_error(
        self, monkeypatch, store, ws
    ):
        _, routed = _routed(monkeypatch)
        run = routed["run_folder_id"]
        auth, _ = read_descriptor(store, run)
        props = {engagement.ARTIFACT_PROPERTY: "README.md", RUN_PROPERTY: auth.run_id}
        for body in (b"# Run\n", b"# Other\n"):
            store.put_stream(
                run, "README.md", "text/markdown", [body], properties=props
            )
        with pytest.raises(SinkConflictError):
            _sink(store, run).put_text("README.md", "# Run\n")
        with pytest.raises(ApiError) as exc:
            engagement.cmd_commit(_commit(run))
        assert "reconcile" in exc.value.message
        assert latest_manifest(store, run)[0].revision == 1

    def test_read_paths_must_stay_under_the_run(self, monkeypatch, store, ws):
        _, routed = _routed(monkeypatch)
        args = SimpleNamespace(
            run_folder=routed["run_folder_id"],
            path="../outside.txt",
            max_bytes=None,
            jsonpath=None,
            offset=0,
        )
        with pytest.raises(ArgError):
            engagement.cmd_read(args)

    def test_target_must_be_a_run_folder(self, store):
        with pytest.raises((ArgError, ApiError)):
            engagement.cmd_commit(_commit(store.root_folder_id()))

    def test_integrity_failure_is_api_error(self, monkeypatch, store, ws):
        _, routed = _routed(monkeypatch)
        run = routed["run_folder_id"]
        ref = _sink(store, run).put_text("README.md", "# Run\n")
        store.corrupt_object(ref.object_id)
        with pytest.raises(ApiError):
            engagement.cmd_commit(_commit(run))
        assert latest_manifest(store, run)[0].revision == 1

    def test_commit_is_bound_to_its_run_folder(self, monkeypatch, store, ws):
        _, a = _routed(monkeypatch)
        _, b = _routed(monkeypatch)
        _sink(store, b["run_folder_id"]).put_text("README.md", "other run\n")
        _sink(store, a["run_folder_id"]).put_text("notes.md", "this run\n")
        data = engagement.cmd_commit(_commit(a["run_folder_id"]))
        assert data["refs_added"] == ["notes.md"]
        manifest, _ = latest_manifest(store, a["run_folder_id"])
        assert all(r.object_id != b["descriptor_id"] for r in manifest.refs)
        assert "README.md" not in {r.path for r in manifest.refs}
        assert latest_manifest(store, b["run_folder_id"])[0].revision == 1

    def test_sink_refuses_another_runs_fingerprint(self, monkeypatch, store, ws):
        _, a = _routed(monkeypatch)
        _, b = _routed(monkeypatch)
        store.set_access(b["run_folder_id"], grants=SHARED)
        auth, _ = read_descriptor(store, a["run_folder_id"])
        assert auth.drive is not None
        foreign = DriveRunSink(
            store,
            b["run_folder_id"],
            run_id=auth.run_id,
            access_fingerprint=auth.drive.permission_fingerprints[a["run_folder_id"]],
        )
        with pytest.raises(AccessRecheckError):
            foreign.put_text("x.md", "x")

    def test_quarantined_run_is_refused_before_any_write(self, monkeypatch, store, ws):
        pre, routed = _routed(monkeypatch)
        run = routed["run_folder_id"]
        quarantine_staging(store, ensure_staging(store, pre["run_id"]), "late mismatch")
        count = store.object_count
        with pytest.raises(engagement.RunQuarantined) as exc:
            engagement.cmd_commit(_commit(run))
        assert "quarantined" in exc.value.message
        assert store.object_count == count
        assert latest_manifest(store, run)[0].revision == 1

    @pytest.mark.parametrize("fault", ["deny", "corrupt"])
    def test_retry_after_a_failed_artifact_write_converges(
        self, monkeypatch, store, ws, fault
    ):
        import hashlib

        _, routed = _routed(monkeypatch)
        run = routed["run_folder_id"]
        sink = _sink(store, run)
        put = store.put_stream
        names: list[str] = []

        def flaky(parent_id: str, name: str, *a: Any, **kw: Any):
            names.append(name)
            if name != "README.md" or names.count(name) > 1:
                return put(parent_id, name, *a, **kw)
            if fault == "deny":
                raise StoragePermissionError("injected")
            store.corrupt_read_back = lambda b: b + b"!"
            try:
                return put(parent_id, name, *a, **kw)
            finally:
                store.corrupt_read_back = None

        monkeypatch.setattr(store, "put_stream", flaky)
        with pytest.raises((StoragePermissionError, StorageIntegrityError)):
            sink.put_text("README.md", "# Run\n")
        monkeypatch.setattr(store, "put_stream", put)
        if fault == "deny":
            # A refused write latches the sink: no further writes this process.
            with pytest.raises(StoragePermissionError):
                sink.put_text("README.md", "# Run\n")

        ref = _sink(store, run).put_text("README.md", "# Run\n")  # the retry
        again = engagement.cmd_commit(_commit(run))
        assert again["revision"] == 2 and "README.md" in again["refs_added"]
        assert _revisions(store, run) == ["rev-000001.json", "rev-000002.json"]
        (only,) = store.list_children(run, name="README.md")
        assert only.id == ref.object_id
        refs = {r.path: r for r in latest_manifest(store, run)[0].refs}
        assert refs["README.md"].revision == ref.revision
        assert refs["README.md"].md5 == hashlib.md5(b"# Run\n").hexdigest()

    def test_retry_after_a_denied_manifest_write_converges(
        self, monkeypatch, store, ws
    ):
        _, routed = _routed(monkeypatch)
        run = routed["run_folder_id"]
        _fill(_sink(store, run))
        put = store.put_stream

        def deny(parent_id: str, name: str, *a: Any, **kw: Any):
            if name == "rev-000002.json":
                raise StoragePermissionError("injected")
            return put(parent_id, name, *a, **kw)

        monkeypatch.setattr(store, "put_stream", deny)
        with pytest.raises(ApiError):
            engagement.cmd_commit(_commit(run))
        assert latest_manifest(store, run)[0].revision == 1
        monkeypatch.setattr(store, "put_stream", put)
        assert engagement.cmd_commit(_commit(run))["revision"] == 2
        assert _revisions(store, run) == ["rev-000001.json", "rev-000002.json"]

    def test_corrupt_manifest_write_fails_closed(self, monkeypatch, store, ws):
        _, routed = _routed(monkeypatch)
        run = routed["run_folder_id"]
        store.corrupt_read_back = lambda b: b + b"!"
        with pytest.raises(ApiError):
            engagement.cmd_commit(_commit(run))
        store.corrupt_read_back = None
        # No delete operations: the broken revision is never silently replaced.
        with pytest.raises(ApiError) as exc:
            engagement.cmd_commit(_commit(run))
        assert "not valid" in exc.value.message
        assert _revisions(store, run) == ["rev-000001.json", "rev-000002.json"]


# --------------------------------------------------------------------------- #
# workspace-client seam
# --------------------------------------------------------------------------- #


class TestWorkspaceClientSeam:
    def test_profile_uses_the_masked_profile_factory(self, monkeypatch):
        seen: list[str | None] = []
        monkeypatch.setattr(
            _envelope, "make_client", lambda profile=None: seen.append(profile) or "c"
        )
        assert _envelope._make_workspace_client("acme", None) == "c"
        assert seen == ["acme"]

    def test_host_masks_the_ambient_profile_and_foreign_env_auth(self, monkeypatch):
        import databricks.sdk as sdk

        seen: dict[str, Any] = {}

        def fake_client(**kw: Any) -> str:
            import os

            seen["kw"] = kw
            seen["env"] = {
                k: os.environ.get(k)
                for k in (
                    "DATABRICKS_CONFIG_PROFILE",
                    "DATABRICKS_HOST",
                    "DATABRICKS_TOKEN",
                )
            }
            return "c"

        monkeypatch.setattr(sdk, "WorkspaceClient", fake_client)
        monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "ambient")
        monkeypatch.setenv("DATABRICKS_HOST", "https://other.cloud.databricks.com")
        monkeypatch.setenv("DATABRICKS_TOKEN", "x")
        assert _envelope._make_workspace_client(None, HOST) == "c"
        assert seen["kw"] == {"host": HOST}
        assert seen["env"] == {
            "DATABRICKS_CONFIG_PROFILE": None,
            "DATABRICKS_HOST": None,
            "DATABRICKS_TOKEN": None,
        }
        import os

        assert os.environ["DATABRICKS_CONFIG_PROFILE"] == "ambient"

    def test_host_keeps_env_auth_for_the_same_host(self, monkeypatch):
        import databricks.sdk as sdk

        seen: dict[str, Any] = {}

        def fake_client(**kw: Any) -> str:
            import os

            seen["profile"] = os.environ.get("DATABRICKS_CONFIG_PROFILE")
            seen["token"] = os.environ.get("DATABRICKS_TOKEN")
            return "c"

        monkeypatch.setattr(sdk, "WorkspaceClient", fake_client)
        monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "ambient")
        monkeypatch.setenv("DATABRICKS_HOST", HOST + "/")
        monkeypatch.setenv("DATABRICKS_TOKEN", "x")
        _envelope._make_workspace_client(None, HOST)
        assert seen == {"profile": None, "token": "x"}

    def test_needs_profile_or_host(self):
        with pytest.raises(ArgError):
            _envelope._make_workspace_client(None, None)


# --------------------------------------------------------------------------- #
# dispatcher wiring
# --------------------------------------------------------------------------- #


def test_domain_is_registered(monkeypatch, capsys):
    from starboard_skills.helpers.__main__ import main

    _overlay(monkeypatch, OVERLAY_OFF)
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "engagement",
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
            ]
        )
    assert exc.value.code in (0, None)
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["domain"] == "engagement"
    assert payload["command"] == "preflight"
    assert payload["data"]["decision"]["policy"] == "local"


@pytest.mark.parametrize(
    "argv",
    [
        # neither --profile nor --host
        ["engagement", "verify-identity", "--run-id", RUN_ID, "--account-key", "k"],
        # both --profile and --host
        [
            "engagement",
            "verify-identity",
            "--run-id",
            RUN_ID,
            "--account-key",
            "k",
            "--profile",
            "p",
            "--host",
            HOST,
        ],
        # removed subcommand
        ["engagement", "upload", "--run-folder", "x"],
        # commit needs --run-folder and --stage
        ["engagement", "commit", "--run-folder", "x"],
        ["engagement", "commit", "--run-folder", "x", "--stage", "publication"],
    ],
)
def test_bad_args_exit_usage(argv, capsys):
    from starboard_skills.helpers.__main__ import main

    with pytest.raises(SystemExit) as exc:
        main(argv)
    # run-5 B2: an engagement argument error is USAGE (exit 2), not exit 4 (storage).
    assert exc.value.code == 2
    env = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert env["domain"] == "engagement" and env["errors"][0]["code"] == "USAGE"


def test_route_without_a_target_is_a_usage_error(monkeypatch, capsys):
    from starboard_skills.helpers.__main__ import main

    with pytest.raises(SystemExit) as exc:
        main(["engagement", "route", "--account-key", "k"])
    assert exc.value.code in (2, 4)
    out = capsys.readouterr().out
    if out:
        assert json.loads(out)["ok"] is False


def test_verify_identity_is_wired(monkeypatch, capsys, ws):
    from starboard_skills.helpers.__main__ import main

    _overlay(monkeypatch, OVERLAY_OFF)
    pre = engagement.cmd_preflight(_preflight())
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "engagement",
                "verify-identity",
                "--run-dir",
                pre["run_dir"],
                "--profile",
                "acme",
                "--account-key",
                "001ABC",
            ]
        )
    assert exc.value.code in (0, None)
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["status"] == "verified"


def test_domain_is_in_discovery_catalog():
    from starboard_skills.helpers.discovery import DOMAIN_CATALOG

    entry = next(d for d in DOMAIN_CATALOG if d["name"] == "engagement")
    assert entry["commands"] == [
        "preflight",
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
    ]


class TestRecoveryHints:
    """Error hints name a step that can actually fix the problem."""

    def test_commit_error_does_not_send_the_user_back_to_route(self):
        from starboard_core.engagement.commit import CommitError

        with pytest.raises(ApiError) as exc, _envelope._storage_errors():
            raise CommitError("manifest revisions are not contiguous")
        message = exc.value.message
        assert "re-run `engagement route`" not in message.lower()
        assert "engagement preflight" in message


class TestVerifiedProfile:
    """verify-identity records its profile; the run's fetches read as that identity."""

    def test_drive_descriptor_records_the_verified_profile(self, monkeypatch, store, ws):
        _, routed = _routed(monkeypatch)
        auth, _ = read_descriptor(store, routed["run_folder_id"])
        assert auth.authorized_scope["basis"] == "verified"
        assert auth.workspace_profile == "acme"
        assert ws.built == [("acme", None)]

    def test_host_verified_descriptor_records_no_profile(self, monkeypatch, store, ws):
        pre = _drive_pre(monkeypatch)
        engagement.cmd_verify_identity(
            _verify(pre, profile=None, host="https://adb-1.azuredatabricks.net")
        )
        routed = engagement.cmd_route(_route(pre))
        auth, _ = read_descriptor(store, routed["run_folder_id"])
        assert auth.workspace_profile is None

    def test_local_identity_check_records_the_profile(self, monkeypatch, ws):
        pre = _local_pre(monkeypatch)
        data = engagement.cmd_verify_identity(_verify(pre))
        assert data["workspace_profile"] == "acme"
        record = json.loads(_identity_file(pre).read_text())
        assert record["workspace_profile"] == "acme"

    def test_fetch_on_the_run_uses_and_guards_the_verified_profile(
        self, monkeypatch, store, ws, capsys
    ):
        from starboard_skills.helpers import contract

        from .conftest import profile_kw, run_main

        _, routed = _routed(monkeypatch)
        run = routed["run_folder_id"]
        monkeypatch.setattr(contract, "_load_storage", lambda: store)
        monkeypatch.setattr(contract, "_detect_overlay", lambda: OVERLAY_ON)
        built: list[dict[str, Any]] = []

        def client(**kw: Any) -> Any:
            from unittest.mock import MagicMock

            built.append(profile_kw(kw))
            return MagicMock()

        monkeypatch.setattr("databricks.sdk.WorkspaceClient", client)
        code, out = run_main(["job", "list", "--run-folder", run], capsys)
        assert code == 0, out
        assert built == [{"profile": "acme"}]
        code, out = run_main(
            ["--profile", "other", "job", "list", "--run-folder", run], capsys
        )
        assert code == 2
        assert json.loads(out)["error"].startswith("PROFILE_MISMATCH")
        assert built == [{"profile": "acme"}]
