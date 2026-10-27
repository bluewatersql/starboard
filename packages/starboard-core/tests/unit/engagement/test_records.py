# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for the RunAuthorization / RunState / DriveContext records."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from typing import Any

import pytest
from starboard_core.engagement.policy import SourceMode, StoragePolicy
from starboard_core.engagement.records import (
    FAMILIES,
    AccountRef,
    Approval,
    BaselineSelection,
    DeliveryReceipt,
    DriveContext,
    EvidenceRef,
    FindingRecord,
    FindingRevision,
    IdentityCheck,
    Observation,
    Registration,
    ReportRevision,
    RunAuthorization,
    RunManifest,
    RunState,
    StorageRef,
    audience_class_for,
    concern_key,
    episode_id,
    evidence_id,
    finding_id,
    observation_id,
    registration_id,
)

RID = "20261007_12345678-1234-4234-8234-123456789abc"


def make_drive(**over: Any) -> DriveContext:
    base: dict[str, Any] = {
        "provider": "google_drive",
        "principal": "user-opaque-123",
        "route": "account",
        "base_folder_id": "base1",
        "root_folder_id": "root1",
        "run_folder_id": "run1",
        "registry_folder_id": "reg1",
        "account_key": "acme",
        "acl_classification": "internal_only",
        "permission_fingerprints": {"root1": "fp-a", "run1": "fp-b"},
        "capabilities": {"upload": True, "read": True},
        "created_at": "2026-10-07T12:00:00+00:00",
        "idempotency_key": "sbk1_" + "a" * 64,
        "links": {"run": "https://drive.example/run1"},
    }
    base.update(over)
    return DriveContext(**base)


def make_auth(**over: Any) -> RunAuthorization:
    base: dict[str, Any] = {
        "engagement_id": "eng-acme-2026",
        "run_id": RID,
        "intent": "health_check",
        "task": "quarterly review",
        "account": AccountRef(id="001ABC", display_name="Acme", verifier="sfdc"),
        "requested_scope": {"workspaces": ["123"], "days": 30},
        "authorized_scope": {"workspaces": ["123"], "days": 30},
        "reporting_interval": "P30D",
        "timezone": "UTC",
        "source_mode": SourceMode.CUSTOMER_WORKSPACE,
        "storage_policy": StoragePolicy.DRIVE_REQUIRED,
        "audience": "internal",
        "methodology_version": "m1",
    }
    base.update(over)
    return RunAuthorization(**base)


# ---- AccountRef --------------------------------------------------------------


def test_account_ref_round_trip() -> None:
    a = AccountRef(id="1", display_name="Acme", verifier="sfdc")
    assert AccountRef.from_dict(a.to_dict()) == a


def test_account_ref_requires_fields() -> None:
    with pytest.raises(ValueError):
        AccountRef(id="", display_name="x", verifier="y")
    with pytest.raises(ValueError):
        AccountRef.from_dict({"id": "1"})


# ---- DriveContext ------------------------------------------------------------


def test_drive_context_round_trip_json_safe() -> None:
    d = make_drive()
    data = d.to_dict()
    assert data["schema_version"] == 1
    assert json.loads(json.dumps(data)) == data
    assert DriveContext.from_dict(json.loads(json.dumps(data))) == d


def test_drive_context_fallback_warning_round_trip() -> None:
    d = make_drive(route="override", fallback_warning="fell back to My Drive")
    assert (
        DriveContext.from_dict(d.to_dict()).fallback_warning == "fell back to My Drive"
    )
    assert make_drive().fallback_warning is None


def test_drive_context_invalid_route() -> None:
    with pytest.raises(ValueError):
        make_drive(route="elsewhere")


def test_drive_context_invalid_created_at() -> None:
    with pytest.raises(ValueError):
        make_drive(created_at="yesterday")


def test_drive_context_is_immutable() -> None:
    d = make_drive()
    with pytest.raises(FrozenInstanceError):
        d.principal = "x"  # type: ignore[misc]
    with pytest.raises(TypeError):
        d.permission_fingerprints["new"] = "x"  # type: ignore[index]


def test_drive_context_does_not_alias_input() -> None:
    fps = {"root1": "fp"}
    d = make_drive(permission_fingerprints=fps)
    fps["other"] = "x"
    assert "other" not in d.permission_fingerprints


def test_drive_context_rejects_credential_keys() -> None:
    with pytest.raises(ValueError):
        make_drive(links={"access_token": "abc"})


def test_drive_context_unsupported_schema_version() -> None:
    data = make_drive().to_dict()
    data["schema_version"] = 2
    with pytest.raises(ValueError):
        DriveContext.from_dict(data)


# ---- RunAuthorization --------------------------------------------------------


def test_authorization_round_trip_json_safe() -> None:
    a = make_auth(
        drive=make_drive(), ticket={"key": "AR-000000001", "status": "validated"}
    )
    data = a.to_dict()
    assert data["schema_version"] == 1
    assert data["source_mode"] == "customer_workspace"
    assert data["storage_policy"] == "drive_required"
    assert json.loads(json.dumps(data)) == data
    assert RunAuthorization.from_dict(json.loads(json.dumps(data))) == a


def test_authorization_round_trip_minimal() -> None:
    a = make_auth()
    assert a.drive is None and a.ticket is None
    assert RunAuthorization.from_dict(a.to_dict()) == a


def test_authorization_records_workspace_profile() -> None:
    a = make_auth(workspace_profile="acme-ws")
    data = a.to_dict()
    assert data["workspace_profile"] == "acme-ws"
    assert RunAuthorization.from_dict(json.loads(json.dumps(data))) == a
    assert make_auth().to_dict()["workspace_profile"] is None
    legacy = make_auth().to_dict()
    del legacy["workspace_profile"]
    assert RunAuthorization.from_dict(legacy).workspace_profile is None
    with pytest.raises(ValueError):
        make_auth(workspace_profile="  ")


def test_authorization_is_immutable() -> None:
    a = make_auth()
    with pytest.raises(FrozenInstanceError):
        a.audience = "customer"  # type: ignore[misc]
    with pytest.raises(TypeError):
        a.authorized_scope["days"] = 1  # type: ignore[index]


def test_authorization_does_not_alias_input_scope() -> None:
    scope = {"workspaces": ["1"]}
    a = make_auth(authorized_scope=scope)
    scope["workspaces"].append("2")
    assert a.to_dict()["authorized_scope"] == {"workspaces": ["1"]}


def test_authorization_validates_run_id() -> None:
    with pytest.raises(ValueError):
        make_auth(run_id="nope")


@pytest.mark.parametrize(
    "key",
    [
        "token",
        "secret",
        "password",
        "api_key",
        "access_token",
        "accessToken",
        "apiKey",
        "X-Api-Key",
        "client_secret",
        "oauth.refresh_token",
        "credentials",
    ],
)
def test_authorization_rejects_credential_keys_nested(key: str) -> None:
    with pytest.raises(ValueError, match="credential"):
        make_auth(authorized_scope={"outer": {"inner": {key: "x"}}})


def test_authorization_rejects_credential_keys_in_lists_and_ticket() -> None:
    with pytest.raises(ValueError):
        make_auth(requested_scope={"items": [{"ok": 1}, {"Password": "x"}]})
    with pytest.raises(ValueError):
        make_auth(ticket={"auth": {"API-Key": "x"}})


@pytest.mark.parametrize(
    "key", ["max_tokens", "total_tokens", "secretary", "keyboard", "tokenizer", "api"]
)
def test_authorization_allows_innocent_keys(key: str) -> None:
    make_auth(authorized_scope={"workspace_id": "1", "principal": "p", key: "x"})


def test_authorization_from_dict_rejects_credentials() -> None:
    data = make_auth().to_dict()
    data["ticket"] = {"secret": "x"}
    with pytest.raises(ValueError):
        RunAuthorization.from_dict(data)


def test_authorization_from_dict_missing_and_version() -> None:
    data = make_auth().to_dict()
    bad = dict(data)
    del bad["intent"]
    with pytest.raises(ValueError):
        RunAuthorization.from_dict(bad)
    bad = dict(data, schema_version=99)
    with pytest.raises(ValueError):
        RunAuthorization.from_dict(bad)


def test_authorization_from_dict_bad_enum() -> None:
    data = make_auth().to_dict()
    data["storage_policy"] = "cloud9"
    with pytest.raises(ValueError):
        RunAuthorization.from_dict(data)


# ---- RunState ----------------------------------------------------------------


def test_run_state_new_defaults() -> None:
    s = RunState.new(RID)
    assert s.run_id == RID
    assert s.revision == 1
    assert (
        s.capture_status
        == s.analysis_status
        == s.check_status
        == s.publication_status
        == "pending"
    )
    assert s.warnings == ()
    assert s.source_attempts == ()


def test_run_state_round_trip_json_safe() -> None:
    s = RunState.new(RID).advance(
        observed_scope={"workspaces": ["1"]},
        source_attempts=({"source": "system.billing", "status": "ok"},),
        capture_status="complete",
        warnings=("truncated at 50 rows",),
        updated_at="2026-10-07T13:00:00+00:00",
    )
    data = s.to_dict()
    assert data["schema_version"] == 1
    assert data["revision"] == 2
    assert json.loads(json.dumps(data)) == data
    assert RunState.from_dict(json.loads(json.dumps(data))) == s


def test_run_state_advance_is_immutable_and_bumps_revision() -> None:
    s0 = RunState.new(RID)
    s1 = s0.advance(capture_status="in_progress")
    s2 = s1.advance(capture_status="complete", analysis_status="in_progress")
    assert (s0.revision, s1.revision, s2.revision) == (1, 2, 3)
    assert s0.capture_status == "pending"
    assert s1.capture_status == "in_progress"
    assert s2.analysis_status == "in_progress"
    assert s2.created_at == s0.created_at


def test_run_state_advance_sets_updated_at_unless_given() -> None:
    s0 = RunState.new(RID, now_iso="2026-10-07T12:00:00+00:00")
    s1 = s0.advance(capture_status="complete")
    assert s1.updated_at != "" and s1.updated_at >= s0.updated_at
    s2 = s0.advance(updated_at="2030-01-01T00:00:00+00:00")
    assert s2.updated_at == "2030-01-01T00:00:00+00:00"


def test_run_state_advance_rejects_protected_and_unknown() -> None:
    s = RunState.new(RID)
    for field in ("run_id", "revision", "schema_version", "created_at"):
        with pytest.raises(ValueError):
            s.advance(**{field: 5})
    with pytest.raises(ValueError):
        s.advance(bogus=1)


def test_run_state_pending_publication_keeps_observations() -> None:
    s = RunState.new(RID).advance(
        observed_scope={"w": 1}, capture_status="complete", analysis_status="complete"
    )
    assert s.publication_status == "pending"
    assert s.observed_scope == {"w": 1}


def test_run_state_validates_status_and_run_id() -> None:
    with pytest.raises(ValueError):
        RunState.new(RID).advance(capture_status="done-ish")
    with pytest.raises(ValueError):
        RunState.new("bad")
    with pytest.raises(ValueError):
        replace(RunState.new(RID), revision=0)


def test_run_state_is_frozen_and_mappings_immutable() -> None:
    s = RunState.new(RID).advance(observed_scope={"a": 1})
    with pytest.raises(FrozenInstanceError):
        s.revision = 9  # type: ignore[misc]
    with pytest.raises(TypeError):
        s.observed_scope["b"] = 2  # type: ignore[index]


def test_run_state_from_dict_errors() -> None:
    data = RunState.new(RID).to_dict()
    with pytest.raises(ValueError):
        RunState.from_dict(dict(data, schema_version=2))
    bad = dict(data)
    del bad["run_id"]
    with pytest.raises(ValueError):
        RunState.from_dict(bad)
    with pytest.raises(ValueError):
        RunState.from_dict(dict(data, updated_at="not a time"))


def test_run_state_rejects_credential_keys() -> None:
    with pytest.raises(ValueError):
        RunState.new(RID).advance(source_attempts=({"api_key": "x"},))


# ---- IdentityCheck -----------------------------------------------------------


def make_identity(**over: Any) -> IdentityCheck:
    base: dict[str, Any] = {
        "run_id": RID,
        "provisional_account_key": "acme",
        "provisional_account_name": "Acme Corp",
        "provisional_source": "operator",
        "expected_workspace_id": "1234567890",
        "expected_host": "https://adb-1.azuredatabricks.net",
        "observed_workspace_id": "1234567890",
        "observed_host": "https://adb-1.azuredatabricks.net",
        "principal_id": "7781234",
        "principal_kind": "user",
        "checked_at": "2026-10-08T09:00:00+00:00",
        "status": "verified",
        "reasons": (),
    }
    base.update(over)
    return IdentityCheck(**base)


def test_identity_check_round_trip_json_safe() -> None:
    c = make_identity()
    data = c.to_dict()
    assert data["schema_version"] == 1
    assert data["reasons"] == []
    assert json.loads(json.dumps(data)) == data
    assert IdentityCheck.from_dict(json.loads(json.dumps(data))) == c


def test_identity_check_mismatch_round_trip() -> None:
    c = make_identity(
        expected_workspace_id="",
        expected_host=None,
        status="mismatch",
        reasons=["no expected workspace id"],
    )
    assert c.reasons == ("no expected workspace id",)
    assert IdentityCheck.from_dict(c.to_dict()) == c


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("provisional_source", "guess"),
        ("principal_kind", "group"),
        ("status", "maybe"),
        ("run_id", "bad"),
        ("checked_at", "now"),
        ("provisional_account_key", ""),
        ("provisional_account_name", " "),
        ("observed_workspace_id", ""),
        ("observed_host", ""),
        ("principal_id", ""),
    ],
)
def test_identity_check_validation_errors(field_name: str, value: Any) -> None:
    with pytest.raises(ValueError):
        make_identity(**{field_name: value})


def test_identity_check_rejects_email_principal() -> None:
    with pytest.raises(ValueError, match="opaque"):
        make_identity(principal_id="someone@example.com")


def test_identity_check_status_must_agree_with_reasons() -> None:
    with pytest.raises(ValueError):
        make_identity(status="verified", reasons=("host differs",))
    with pytest.raises(ValueError):
        make_identity(status="mismatch", reasons=())


def test_identity_check_verified_requires_matching_ids_and_hosts() -> None:
    with pytest.raises(ValueError):
        make_identity(observed_workspace_id="999")
    with pytest.raises(ValueError):
        make_identity(expected_workspace_id="")
    with pytest.raises(ValueError):
        make_identity(observed_host="https://other.cloud.databricks.com")
    # Without an expected host, only the workspace ID has to agree.
    assert make_identity(expected_host=None).status == "verified"


def test_identity_check_from_dict_errors() -> None:
    data = make_identity().to_dict()
    with pytest.raises(ValueError):
        IdentityCheck.from_dict(dict(data, schema_version=2))
    bad = dict(data)
    del bad["principal_id"]
    with pytest.raises(ValueError):
        IdentityCheck.from_dict(bad)
    with pytest.raises(ValueError, match="credential"):
        IdentityCheck.from_dict(dict(data, access_token="abc"))


def test_identity_check_is_frozen() -> None:
    c = make_identity()
    with pytest.raises(FrozenInstanceError):
        c.status = "mismatch"  # type: ignore[misc]


# ---- StorageRef --------------------------------------------------------------


def make_ref(**over: Any) -> StorageRef:
    base: dict[str, Any] = {
        "path": "analysis/report.json",
        "object_id": "obj-1",
        "revision": "rev-1",
        "md5": "0" * 32,
        "size": 10,
        "mime_type": "application/json",
    }
    base.update(over)
    return StorageRef(**base)


def test_storage_ref_round_trip() -> None:
    r = make_ref()
    data = r.to_dict()
    assert data["schema_version"] == 1
    assert json.loads(json.dumps(data)) == data
    assert StorageRef.from_dict(data) == r
    bare = make_ref(revision=None, md5=None, size=None)
    assert StorageRef.from_dict(bare.to_dict()) == bare


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("path", ""),
        ("path", "/Users/me/run/x.json"),
        ("path", "~/x.json"),
        ("path", "C:\\run\\x.json"),
        ("path", "analysis/../../etc/passwd"),
        ("object_id", ""),
        ("mime_type", ""),
        ("md5", "XYZ"),
        ("size", -1),
        ("size", True),
    ],
)
def test_storage_ref_validation_errors(field_name: str, value: Any) -> None:
    with pytest.raises(ValueError):
        make_ref(**{field_name: value})


def test_storage_ref_from_dict_errors() -> None:
    data = make_ref().to_dict()
    with pytest.raises(ValueError):
        StorageRef.from_dict(dict(data, schema_version=3))
    bad = dict(data)
    del bad["object_id"]
    with pytest.raises(ValueError):
        StorageRef.from_dict(bad)
    with pytest.raises(ValueError, match="credential"):
        StorageRef.from_dict(dict(data, bearer="x"))


# ---- RunManifest -------------------------------------------------------------

_STATES = {
    "capture": "complete",
    "analysis": "complete",
    "check": "pending",
    "publication": "pending",
}


def make_manifest(**over: Any) -> RunManifest:
    base: dict[str, Any] = {
        "engagement_id": "eng-acme-2026",
        "run_id": RID,
        "revision": 1,
        "previous_object_id": None,
        "task": "workspace",
        "task_name": "ws-1234567890",
        "source_mode": SourceMode.CUSTOMER_WORKSPACE,
        "storage_policy": StoragePolicy.DRIVE_REQUIRED,
        "descriptor_ref": make_ref(path="run-authorization.json", object_id="desc-1"),
        "refs": (make_ref(),),
        "states": _STATES,
        "committed_at": "2026-10-08T09:30:00+00:00",
    }
    base.update(over)
    return RunManifest(**base)


def test_run_manifest_round_trip_json_safe() -> None:
    m = make_manifest(
        revision=2,
        previous_object_id="man-1",
        refs=[make_ref(), make_ref(path="evidence/rows.csv", object_id="obj-2")],
    )
    assert isinstance(m.refs, tuple)
    data = m.to_dict()
    assert data["schema_version"] == 1
    assert data["source_mode"] == "customer_workspace"
    assert data["storage_policy"] == "drive_required"
    assert json.loads(json.dumps(data)) == data
    assert RunManifest.from_dict(json.loads(json.dumps(data))) == m


def test_run_manifest_previous_iff_not_first() -> None:
    with pytest.raises(ValueError):
        make_manifest(revision=1, previous_object_id="man-0")
    with pytest.raises(ValueError):
        make_manifest(revision=2, previous_object_id=None)
    with pytest.raises(ValueError):
        make_manifest(revision=2, previous_object_id="")


@pytest.mark.parametrize("revision", [0, -1, True, "1"])
def test_run_manifest_revision_must_be_positive_int(revision: Any) -> None:
    with pytest.raises(ValueError):
        make_manifest(revision=revision)


def test_run_manifest_states_validated() -> None:
    with pytest.raises(ValueError):
        make_manifest(states={**_STATES, "capture": "done-ish"})
    with pytest.raises(ValueError):
        make_manifest(states={"capture": "complete"})
    with pytest.raises(ValueError):
        make_manifest(states={**_STATES, "extra": "complete"})


def test_run_manifest_other_validation_errors() -> None:
    with pytest.raises(ValueError):
        make_manifest(run_id="bad")
    with pytest.raises(ValueError):
        make_manifest(task="")
    with pytest.raises(ValueError):
        make_manifest(committed_at="later")
    with pytest.raises(ValueError):
        make_manifest(source_mode="sideways")
    with pytest.raises(ValueError):
        make_manifest(refs=(make_ref(), make_ref()))  # duplicate path
    with pytest.raises(TypeError):
        make_manifest(refs=({"path": "x"},))


def test_run_manifest_is_immutable() -> None:
    m = make_manifest()
    with pytest.raises(FrozenInstanceError):
        m.revision = 5  # type: ignore[misc]
    with pytest.raises(TypeError):
        m.states["capture"] = "failed"  # type: ignore[index]


def test_run_manifest_from_dict_errors() -> None:
    data = make_manifest().to_dict()
    with pytest.raises(ValueError):
        RunManifest.from_dict(dict(data, schema_version=2))
    bad = dict(data)
    del bad["descriptor_ref"]
    with pytest.raises(ValueError):
        RunManifest.from_dict(bad)
    with pytest.raises(ValueError, match="credential"):
        RunManifest.from_dict(dict(data, client_secret="x"))


def test_run_manifest_phase1_constructor_defaults() -> None:
    m = make_manifest()
    assert m.input_scope == {}
    assert m.workflow_profile is None
    assert m.evidence_refs == ()
    assert m.observation_refs == ()
    assert m.findings_ref is None
    assert m.reports == ()
    assert m.approvals == ()
    assert m.receipts == ()
    assert m.baseline_selection_ref is None
    assert RunManifest.from_dict(m.to_dict()) == m


def test_run_manifest_phase2_fields_round_trip() -> None:
    m = make_manifest(
        input_scope={"workspaces": ["123"]},
        workflow_profile="health_check",
        evidence_refs=["ev_" + "a" * 24],
        observation_refs=[make_ref(path="analysis/observations.json", object_id="o1")],
        findings_ref=make_ref(path="analysis/findings.json", object_id="f1"),
        reports=[
            {"report_id": "r1", "revision": 1, "audience": "customer", "state": "ready"}
        ],
        approvals=["apr_1"],
        receipts=["rcp_1"],
        baseline_selection_ref=make_ref(
            path="analysis/baseline-selection.json", object_id="b1"
        ),
    )
    assert isinstance(m.evidence_refs, tuple)
    assert isinstance(m.observation_refs, tuple)
    data = json.loads(json.dumps(m.to_dict()))
    assert RunManifest.from_dict(data) == m


def test_run_manifest_rejects_unknown_workflow_profile() -> None:
    for bad in ("health", "bogus", "", "Review"):
        with pytest.raises(ValueError, match="workflow_profile"):
            make_manifest(workflow_profile=bad)
    from starboard_core.engagement.profiles import WORKFLOW_PROFILES

    for profile in WORKFLOW_PROFILES:
        m = make_manifest(workflow_profile=profile)
        assert RunManifest.from_dict(json.loads(json.dumps(m.to_dict()))) == m
    assert make_manifest(workflow_profile=None).workflow_profile is None


def test_run_manifest_from_dict_rejects_unknown_workflow_profile() -> None:
    data = json.loads(json.dumps(make_manifest(workflow_profile="review").to_dict()))
    data["workflow_profile"] = "health"
    with pytest.raises(ValueError, match="workflow_profile"):
        RunManifest.from_dict(data)


def test_run_manifest_phase2_field_validation() -> None:
    with pytest.raises(TypeError):
        make_manifest(observation_refs=({"path": "x"},))
    with pytest.raises(TypeError):
        make_manifest(findings_ref={"path": "x"})
    with pytest.raises(TypeError):
        make_manifest(baseline_selection_ref="b1")
    with pytest.raises(ValueError):
        make_manifest(evidence_refs=("",))
    with pytest.raises(ValueError):
        make_manifest(
            reports=[
                {
                    "report_id": "r1",
                    "revision": 1,
                    "audience": "customer",
                    "state": "done",
                }
            ]
        )
    with pytest.raises(ValueError):
        make_manifest(
            reports=[
                {
                    "report_id": "r1",
                    "revision": 0,
                    "audience": "customer",
                    "state": "ready",
                }
            ]
        )
    with pytest.raises(ValueError):
        make_manifest(
            reports=[
                {
                    "report_id": "r1",
                    "revision": 1,
                    "audience": "public",
                    "state": "ready",
                }
            ]
        )
    with pytest.raises(ValueError):
        make_manifest(reports=[{"report_id": "r1"}])
    with pytest.raises(ValueError, match="credential"):
        make_manifest(input_scope={"api_key": "x"})


# ---- ID helpers --------------------------------------------------------------


def test_id_helpers_are_deterministic() -> None:
    a = evidence_id(RID, "raw/W-W01.json", "0" * 32)
    assert a == evidence_id(RID, "raw/W-W01.json", "0" * 32)
    assert a.startswith("ev_") and len(a) == 3 + 24
    assert a != evidence_id(RID, "raw/W-W01.json", "1" * 32)
    assert a != evidence_id(RID, "raw/W-W02.json", "0" * 32)
    key = (
        "acme",
        "123",
        "other",
        "job",
        "j1",
        "dbus",
        "2026-09-01",
        "2026-09-30",
        "m1",
    )
    o = observation_id(key)
    assert o == observation_id(key)
    assert o.startswith("obs_") and len(o) == 4 + 24
    assert o != observation_id(key[:-1] + ("m2",))
    assert registration_id(RID) == f"reg_{RID}"
    with pytest.raises(ValueError):
        registration_id("bad")


def test_families_constant() -> None:
    assert FAMILIES == (
        "consumption_trajectory",
        "efficiency",
        "reliability",
        "adoption_breadth",
        "concentration",
        "governance",
        "other",
    )


def test_audience_class_for() -> None:
    assert audience_class_for("internal_mirror") == "internal_only"
    assert audience_class_for("internal_telemetry") == "internal_only"
    assert audience_class_for("customer_workspace") == "customer_shareable"
    with pytest.raises(ValueError):
        audience_class_for("elsewhere")


# ---- EvidenceRef -------------------------------------------------------------


def make_evidence(**over: Any) -> EvidenceRef:
    ref = over.pop("storage_ref", make_ref(path="raw/W-W01.json", object_id="ev-obj"))
    base: dict[str, Any] = {
        "run_id": RID,
        "storage_ref": ref,
        "source_kind": "customer_workspace",
        "scope_workspace_ids": ["123"],
        "producer": "discovery:W-W01",
        "row_count": 12,
        "truncated": False,
        "acquired_at": "2026-10-08T09:00:00+00:00",
        "audience_class": "customer_shareable",
        "method_version": "discovery_v1",
    }
    base.update(over)
    if "evidence_id" not in base:
        base["evidence_id"] = evidence_id(RID, ref.path, ref.md5 or "")
    return EvidenceRef(**base)


def test_evidence_ref_round_trip() -> None:
    e = make_evidence()
    assert e.scope_workspace_ids == ("123",)
    data = json.loads(json.dumps(e.to_dict()))
    assert data["schema_version"] == 1
    assert EvidenceRef.from_dict(data) == e


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("evidence_id", "ev_wrong"),
        ("run_id", "bad"),
        ("source_kind", "elsewhere"),
        ("producer", ""),
        ("row_count", -1),
        ("row_count", True),
        ("truncated", "no"),
        ("acquired_at", "soon"),
        ("audience_class", "public"),
        ("method_version", ""),
    ],
)
def test_evidence_ref_validation(field_name: str, value: Any) -> None:
    with pytest.raises(ValueError):
        make_evidence(**{field_name: value})


def test_evidence_ref_internal_source_is_internal_only() -> None:
    with pytest.raises(ValueError, match="internal_only"):
        make_evidence(
            source_kind="internal_mirror", audience_class="customer_shareable"
        )
    assert (
        make_evidence(
            source_kind="internal_mirror", audience_class="internal_only"
        ).audience_class
        == "internal_only"
    )


def test_evidence_ref_requires_md5_and_storage_ref() -> None:
    with pytest.raises(ValueError):
        make_evidence(storage_ref=make_ref(md5=None), evidence_id="ev_" + "0" * 24)
    with pytest.raises(TypeError):
        make_evidence(storage_ref={"path": "x"}, evidence_id="ev_" + "0" * 24)


def test_evidence_ref_from_dict_errors() -> None:
    data = make_evidence().to_dict()
    with pytest.raises(ValueError):
        EvidenceRef.from_dict(dict(data, schema_version=2))
    with pytest.raises(ValueError, match="credential"):
        EvidenceRef.from_dict(dict(data, access_token="x"))
    bad = dict(data)
    del bad["producer"]
    with pytest.raises(ValueError):
        EvidenceRef.from_dict(bad)


# ---- Observation -------------------------------------------------------------


def make_observation(**over: Any) -> Observation:
    base: dict[str, Any] = {
        "run_id": RID,
        "account_key": "acme",
        "workspace_id": "123",
        "family": "other",
        "entity_kind": "job",
        "entity_id": "j1",
        "metric": "dbus",
        "value": 10.5,
        "unit": "DBU",
        "grain": "interval",
        "method_version": "discovery_facts_v1",
        "interval_start": "2026-09-01",
        "interval_end": "2026-09-30",
        "as_of": "2026-10-01T00:00:00+00:00",
        "coverage": "complete",
        "coverage_fraction": None,
        "state": "measured",
        "unknown_reason": None,
        "evidence_ids": ["ev_" + "a" * 24],
        "source_kind": "customer_workspace",
        "audience_class": "customer_shareable",
        "dedupe_key": None,
    }
    base.update(over)
    if "observation_id" not in base:
        base["observation_id"] = observation_id(
            tuple(
                base[k]
                for k in (
                    "account_key",
                    "workspace_id",
                    "family",
                    "entity_kind",
                    "entity_id",
                    "metric",
                    "interval_start",
                    "interval_end",
                    "method_version",
                )
            )
        )
    return Observation(**base)


def test_observation_round_trip() -> None:
    o = make_observation()
    assert o.evidence_ids == ("ev_" + "a" * 24,)
    data = json.loads(json.dumps(o.to_dict()))
    assert data["schema_version"] == 1
    assert Observation.from_dict(data) == o
    u = make_observation(
        state="unknown", value=None, unknown_reason="F-04 timed out", coverage="unknown"
    )
    assert Observation.from_dict(u.to_dict()) == u


def test_observation_int_value_becomes_float() -> None:
    assert make_observation(value=3).value == 3.0


def test_observation_key_order() -> None:
    o = make_observation()
    assert o.key == (
        "acme",
        "123",
        "other",
        "job",
        "j1",
        "dbus",
        "2026-09-01",
        "2026-09-30",
        "discovery_facts_v1",
    )


@pytest.mark.parametrize(
    ("over"),
    [
        {"observation_id": "obs_" + "0" * 24},
        {"family": "vibes"},
        {"coverage": "most"},
        {"state": "guessed"},
        {"value": True},
        {"value": "1"},
        {"coverage_fraction": 1.5},
        {"state": "measured", "value": None},
        {"state": "unknown", "value": None, "unknown_reason": None},
        {"state": "unknown", "value": 1.0, "unknown_reason": "x"},
        {"interval_start": "2026-10-01", "interval_end": "2026-09-01"},
        {"as_of": "whenever"},
        {"source_kind": "internal_mirror", "audience_class": "customer_shareable"},
        {"metric": ""},
        {"run_id": "bad"},
    ],
)
def test_observation_validation(over: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        make_observation(**over)


def test_observation_uncertainty_codes() -> None:
    assert make_observation().uncertainty == ()
    o = make_observation(
        uncertainty=["verify_limit_reached", "per_job_cap_25", "per_job_cap_25"]
    )
    assert o.uncertainty == ("per_job_cap_25", "verify_limit_reached")
    data = json.loads(json.dumps(o.to_dict()))
    assert data["uncertainty"] == ["per_job_cap_25", "verify_limit_reached"]
    assert Observation.from_dict(data) == o
    legacy = make_observation().to_dict()
    del legacy["uncertainty"]
    assert Observation.from_dict(legacy).uncertainty == ()


@pytest.mark.parametrize(
    "bad", ["per_job_cap_25", ["capped by 25 jobs"], [""], [3], None]
)
def test_observation_uncertainty_rejects_non_codes(bad: Any) -> None:
    with pytest.raises((TypeError, ValueError)):
        make_observation(uncertainty=bad)


def test_observation_from_dict_errors() -> None:
    data = make_observation().to_dict()
    with pytest.raises(ValueError):
        Observation.from_dict(dict(data, schema_version=9))
    with pytest.raises(ValueError, match="credential"):
        Observation.from_dict(dict(data, password="x"))


# ---- FindingRecord -----------------------------------------------------------


def make_finding(**over: Any) -> FindingRecord:
    key = concern_key("acme", "123", "warehouse", "wh-1", "rule:warehouse_queueing")
    fid = finding_id(key)
    obs = "obs_" + "a" * 24
    base: dict[str, Any] = {
        "finding_id": fid,
        "finding_key": key,
        "concern_code": "rule:warehouse_queueing",
        "family": "efficiency",
        "account_key": "acme",
        "workspace_id": "123",
        "entity_kind": "warehouse",
        "entity_id": "wh-1",
        "episode_id": episode_id(fid, RID),
        "episode_started_run_id": RID,
        "state": "active",
        "severity": "serious",
        "last_confirmed_severity": "serious",
        "symptom_confidence": "confirmed",
        "cause_confidence": "unassessed",
        "rule_id": "warehouse_queueing",
        "rule_version": 1,
        "revision": 1,
        "revisions": (
            FindingRevision(
                revision=1,
                run_id=RID,
                reason="detected",
                severity="serious",
                symptom_confidence="confirmed",
                cause_confidence="unassessed",
                observation_ids=(obs,),
                evidence_ids=(),
                case_id=None,
            ),
        ),
        "observation_ids": [obs],
        "possible_links": [],
        "run_id": RID,
    }
    base.update(over)
    return FindingRecord(**base)


def test_finding_record_round_trip_and_validation() -> None:
    f = make_finding()
    assert FindingRecord.from_dict(json.loads(json.dumps(f.to_dict()))) == f
    with pytest.raises(ValueError):
        make_finding(state="gone")
    with pytest.raises(ValueError):
        make_finding(finding_key="")
    with pytest.raises(ValueError):
        make_finding(finding_key="W-W01::wh-1")
    with pytest.raises(ValueError):
        make_finding(run_id="bad")
    with pytest.raises(ValueError, match="credential"):
        FindingRecord.from_dict(dict(f.to_dict(), secret="x"))


# ---- Registration ------------------------------------------------------------


def make_registration(**over: Any) -> Registration:
    base: dict[str, Any] = {
        "registration_id": registration_id(RID),
        "kind": "run",
        "run_id": RID,
        "engagement_id": "eng-acme-2026",
        "account_key": "acme",
        "task": "workspace",
        "task_name": "ws-123",
        "route": "account",
        "source_mode": SourceMode.CUSTOMER_WORKSPACE,
        "storage_policy": StoragePolicy.DRIVE_REQUIRED,
        "run_folder_id": "run1",
        "descriptor_ref": make_ref(path="run-authorization.json", object_id="d1"),
        "observation_summary_ref": None,
        "acl_classification": "internal_restricted",
        "principal_id": "user-opaque-1",
        "registered_at": "2026-10-08T09:00:00+00:00",
        "provenance": {
            "origin": "drive_run",
            "local_run_id": None,
            "approved_by": None,
        },
    }
    base.update(over)
    return Registration(**base)


def test_registration_round_trip() -> None:
    r = make_registration()
    data = json.loads(json.dumps(r.to_dict()))
    assert data["source_mode"] == "customer_workspace"
    assert Registration.from_dict(data) == r
    imp = make_registration(
        registration_id="reg_imp_" + "c" * 24,
        kind="imported_local",
        run_folder_id=None,
        descriptor_ref=None,
        storage_policy=StoragePolicy.INTERNAL_ONLY_LOCAL,
        source_mode=SourceMode.INTERNAL_ONLY,
        provenance={
            "origin": "local_reference",
            "local_run_id": RID,
            "approved_by": "user-opaque-1",
        },
    )
    assert Registration.from_dict(imp.to_dict()) == imp


@pytest.mark.parametrize(
    "over",
    [
        {"registration_id": "reg_other"},
        {"kind": "copied"},
        {"route": "sideways"},
        {"run_folder_id": None},
        {"principal_id": "someone@example.com"},
        {"registered_at": "later"},
        {"provenance": {"origin": "local_reference"}},
        {"provenance": {"origin": "drive_run", "token": "x"}},
        {"descriptor_ref": {"path": "x"}},
        {"account_key": ""},
    ],
)
def test_registration_validation(over: dict[str, Any]) -> None:
    with pytest.raises((ValueError, TypeError)):
        make_registration(**over)


def test_registration_imported_local_rules() -> None:
    with pytest.raises(ValueError):
        make_registration(
            registration_id="reg_imp_" + "c" * 24,
            kind="imported_local",
            run_folder_id="run1",
            provenance={
                "origin": "local_reference",
                "local_run_id": RID,
                "approved_by": "u",
            },
        )
    with pytest.raises(ValueError):
        make_registration(
            registration_id=registration_id(RID),
            kind="imported_local",
            run_folder_id=None,
            provenance={
                "origin": "local_reference",
                "local_run_id": RID,
                "approved_by": "u",
            },
        )


# ---- ReportRevision / Approval / DeliveryReceipt -----------------------------


def make_revision(**over: Any) -> ReportRevision:
    base: dict[str, Any] = {
        "report_id": "cost-review",
        "revision": 1,
        "audience": "customer",
        "object_ref": make_ref(path="deliverables/report.md", object_id="rep-1"),
        "cited_evidence_ids": ["ev_" + "a" * 24],
        "cited_observation_ids": [],
        "derived_from": None,
        "state": "ready",
        "blocked_reasons": [],
        "created_at": "2026-10-08T10:00:00+00:00",
    }
    base.update(over)
    return ReportRevision(**base)


def test_report_revision_round_trip_and_requires_delivery() -> None:
    r = make_revision(derived_from="internal-review@2")
    assert ReportRevision.from_dict(json.loads(json.dumps(r.to_dict()))) == r
    assert r.requires_delivery is True
    assert make_revision(audience="internal").requires_delivery is False


@pytest.mark.parametrize(
    "over",
    [
        {"revision": 0},
        {"audience": "public"},
        {"state": "shipped"},
        {"derived_from": "no-at-sign"},
        {"derived_from": "r@0"},
        {"report_id": ""},
        {"report_id": "a/b"},
        {"created_at": "x"},
        {"object_ref": make_ref(md5=None)},
        {"state": "blocked_audience", "blocked_reasons": []},
        {"state": "ready", "blocked_reasons": ["internal_only_evidence:ev_x"]},
    ],
)
def test_report_revision_validation(over: dict[str, Any]) -> None:
    with pytest.raises((ValueError, TypeError)):
        make_revision(**over)


def make_approval(**over: Any) -> Approval:
    base: dict[str, Any] = {
        "approval_id": "apr_1",
        "report_id": "cost-review",
        "revision": 1,
        "object_md5": "0" * 32,
        "approver_principal_id": "user-opaque-1",
        "approved_at": "2026-10-08T11:00:00+00:00",
    }
    base.update(over)
    return Approval(**base)


def test_approval_round_trip_and_validation() -> None:
    a = make_approval()
    assert Approval.from_dict(json.loads(json.dumps(a.to_dict()))) == a
    for over in (
        {"object_md5": "x"},
        {"revision": 0},
        {"approver_principal_id": "a@b.c"},
        {"approved_at": "x"},
        {"approval_id": ""},
    ):
        with pytest.raises(ValueError):
            make_approval(**over)


def make_receipt(**over: Any) -> DeliveryReceipt:
    base: dict[str, Any] = {
        "receipt_id": "rcp_1",
        "report_id": "cost-review",
        "revision": 1,
        "object_md5": "0" * 32,
        "channel": "drive",
        "destination_id": "dest-folder",
        "delivered_object_id": "copy-1",
        "delivered_revision": None,
        "verified": True,
        "delivered_at": "2026-10-08T12:00:00+00:00",
    }
    base.update(over)
    return DeliveryReceipt(**base)


def test_receipt_round_trip_and_validation() -> None:
    r = make_receipt()
    assert DeliveryReceipt.from_dict(json.loads(json.dumps(r.to_dict()))) == r
    slack = make_receipt(channel="slack", verified=False)
    assert DeliveryReceipt.from_dict(slack.to_dict()) == slack
    for over in (
        {"channel": "email"},
        {"channel": "slack", "verified": True},
        {"verified": "yes"},
        {"object_md5": "Z"},
        {"delivered_object_id": ""},
        {"delivered_at": "x"},
    ):
        with pytest.raises(ValueError):
            make_receipt(**over)


# ---- BaselineSelection -------------------------------------------------------


def make_selection(**over: Any) -> BaselineSelection:
    base: dict[str, Any] = {
        "run_id": RID,
        "selected": [
            {
                "key": ["acme", "123", "other", "job", "j1", "dbus"],
                "current_observation_id": "obs_" + "a" * 24,
                "baseline_observation_id": "obs_" + "b" * 24,
                "comparison": "continuing",
            }
        ],
        "rejected": [
            {
                "key": ["acme", "123", "other", "job", "j1", "dbus"],
                "candidate_observation_id": "obs_" + "c" * 24,
                "candidate_run_id": RID,
                "interval": {"start": "2026-08-01", "end": "2026-08-31"},
                "reason": "unit_mismatch",
            }
        ],
        "unavailable": [{"registration_id": "reg_x", "reason": "history_unavailable"}],
        "reporting_interval": ["2026-09-01", "2026-09-30"],
        "computed_at": "2026-10-08T12:00:00+00:00",
    }
    base.update(over)
    return BaselineSelection(**base)


def test_baseline_selection_round_trip() -> None:
    s = make_selection()
    assert s.reporting_interval == ("2026-09-01", "2026-09-30")
    assert s.selected[0]["key"] == ("acme", "123", "other", "job", "j1", "dbus")
    data = json.loads(json.dumps(s.to_dict()))
    assert BaselineSelection.from_dict(data) == s


@pytest.mark.parametrize(
    "over",
    [
        {"selected": [{"key": ["a"], "comparison": "continuing"}]},
        {
            "selected": [
                {
                    "key": ["a"],
                    "current_observation_id": None,
                    "baseline_observation_id": None,
                    "comparison": "maybe",
                }
            ]
        },
        {"rejected": [{"key": ["a"], "reason": "x"}]},
        {"unavailable": [{"registration_id": "reg_x"}]},
        {"reporting_interval": ["2026-09-01"]},
        {"computed_at": "x"},
        {"run_id": "bad"},
    ],
)
def test_baseline_selection_validation(over: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        make_selection(**over)
