# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Tests for prior-record loading across task folders (WP3-10, D3-25)."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from starboard_core.engagement.assess import CurrentInputs, RunAssessment, assess_run
from starboard_core.engagement.cases import open_case
from starboard_core.engagement.commit import (
    DESCRIPTOR_NAME,
    append_manifest,
    write_descriptor,
)
from starboard_core.engagement.folders import (
    IDENTITY_PROPERTY,
    FolderResolution,
    resolve_account_route,
)
from starboard_core.engagement.jobruns import RunSlice
from starboard_core.engagement.memory_storage import InMemoryEngagementStorage
from starboard_core.engagement.policy import SourceMode, StoragePolicy
from starboard_core.engagement.prior import PriorRecords, load_prior, load_prior_local
from starboard_core.engagement.records import (
    AccountRef,
    Case,
    DriveContext,
    FindingRecord,
    Observation,
    Registration,
    RunAuthorization,
    RunManifest,
    StorageRef,
    registration_id,
)
from starboard_core.engagement.registry import ensure_registry, register
from starboard_core.engagement.staging import encode_json
from starboard_core.ports.engagement_storage import (
    StorageAuthError,
    StorageError,
    StorageObject,
)

pytestmark = pytest.mark.unit

ACCOUNT = "AR-000000001"
NAME = "Example Account"
WS = "123"
JOB = "42"
BASE_RUN = "20260908_12345678-1234-4234-8234-123456789abc"
J42_RUN = "20261008_12345678-1234-4234-8234-123456789abc"
CASE_RUN = "20261001_22345678-1234-4234-8234-123456789abc"
OTHER_WS_RUN = "20261002_42345678-1234-4234-8234-123456789abc"
CURRENT_RUN = "20261107_12345678-1234-4234-8234-123456789abc"
BASELINE = ("2026-08-09", "2026-09-07")
CURRENT = ("2026-09-08", "2026-10-07")
STATES = {
    "capture": "pending",
    "analysis": "pending",
    "check": "pending",
    "publication": "pending",
}


# ---- record fixtures -----------------------------------------------------------------


def rows(
    first: int, window: tuple[str, str], success: int, failed: int, ws: str
) -> Any:
    out = []
    for i, state in enumerate(["SUCCESS"] * success + ["FAILED"] * failed):
        stamp = window[0] if i % 2 else window[1]
        out.append(
            {
                "workspace_id": ws,
                "job_id": JOB,
                "run_id": str(first + i),
                "result_state": state,
                "first_period_start": f"{stamp}T01:00:00",
                "last_period_end": f"{stamp}T02:00:00",
            }
        )
    return tuple(out)


def run_slice(window: tuple[str, str], data: Any, ws: str = WS) -> RunSlice:
    return RunSlice(
        source_kind="customer_workspace",
        window_start=window[0],
        window_end=window[1],
        job_ids=(JOB,),
        evidence_id="ev_" + "1" * 24,
        rows=data,
        workspace_id=ws,
    )


def assessed(
    prior: PriorRecords,
    run_id: str,
    window: tuple[str, str],
    failed: int,
    *,
    ws: str = WS,
) -> RunAssessment:
    return assess_run(
        prior,
        CurrentInputs(
            verify_slices=(
                run_slice(window, rows(100, window, 100 - failed, failed, ws), ws),
            )
        ),
        run_id=run_id,
        account_key=ACCOUNT,
        workspace_id=ws,
        interval=window,
        # The day after the window: runs ending on ``today`` are still open.
        today=date.fromisoformat(window[1]) + timedelta(days=1),
    )


def runs() -> tuple[RunAssessment, RunAssessment]:
    base = assessed(PriorRecords(), BASE_RUN, BASELINE, 1)
    j42 = assessed(PriorRecords(observations=as_candidates(base)), J42_RUN, CURRENT, 8)
    assert j42.findings and j42.actions
    return base, j42


def as_candidates(run: RunAssessment) -> Any:
    from starboard_core.engagement.history import Candidate

    return tuple(Candidate(o, 1, registration_id(o.run_id)) for o in run.observations)


def standalone_case() -> tuple[Case, FindingRecord]:
    case, finding = open_case(
        account_key=ACCOUNT,
        workspace_id=WS,
        origin="clue",
        origin_ref=f"job:{JOB}",
        question="nightly load fails",
        run_id=CASE_RUN,
    )
    assert finding is not None
    return case, finding


# ---- Drive fixtures ------------------------------------------------------------------


def _store() -> InMemoryEngagementStorage:
    return InMemoryEngagementStorage(root_id="my-root", owner_domain="example.com")


def _ref(obj: StorageObject, path: str) -> StorageRef:
    return StorageRef(
        path=path,
        object_id=obj.id,
        revision=obj.revision,
        md5=obj.md5,
        size=obj.size,
        mime_type=obj.mime_type,
    )


def _put(
    store: InMemoryEngagementStorage, parent: str, path: str, data: Any
) -> StorageRef:
    body = (json.dumps(data, sort_keys=True) + "\n").encode()
    obj = store.put_stream(
        parent, path.rsplit("/", 1)[-1], "application/json", [body], properties={}
    )
    return _ref(obj, path)


def _folder(
    store: InMemoryEngagementStorage, run_id: str, task: str, task_name: str
) -> tuple[FolderResolution, StorageObject]:
    res = resolve_account_route(
        store,
        account_key=ACCOUNT,
        account_name=NAME,
        task=task,
        task_name=task_name,
        run_id=run_id,
    )
    fp = store.inspect_access(res.run_folder_id).fingerprint
    drive = DriveContext(
        provider="google_drive",
        principal="perm-owner-0001",
        route=res.route,
        base_folder_id=res.base_id,
        root_folder_id=res.base_id,
        run_folder_id=res.run_folder_id,
        registry_folder_id="reg",
        account_key=ACCOUNT,
        acl_classification="internal_only",
        permission_fingerprints={res.run_folder_id: fp},
        capabilities={"upload": True},
        created_at="2026-10-08T09:00:00+00:00",
        idempotency_key="sbk1_" + "a" * 64,
    )
    desc = write_descriptor(
        store,
        res.run_folder_id,
        RunAuthorization(
            engagement_id=f"{ACCOUNT}/{task}/{task_name}",
            run_id=run_id,
            intent="troubleshooting" if task == "troubleshoot" else "health_check",
            task=task,
            account=AccountRef(id=ACCOUNT, display_name=NAME, verifier="operator"),
            requested_scope={},
            authorized_scope={"account_key": ACCOUNT},
            reporting_interval="P30D",
            timezone="UTC",
            source_mode=SourceMode.CUSTOMER_WORKSPACE,
            storage_policy=StoragePolicy.DRIVE_REQUIRED,
            audience="internal",
            methodology_version="m1",
            drive=drive,
        ),
    )
    return res, desc


def commit_run(
    store: InMemoryEngagementStorage,
    run_id: str,
    *,
    task: str = "workspace",
    task_name: str = "ws-123",
    observations: Any = (),
    findings: Any = (),
    cases: Any = (),
    actions: Any = (),
    findings_path: str = "analysis/findings.json",
    revisions: int = 1,
    registered: bool = True,
) -> FolderResolution:
    """One committed run folder holding the given records (``revisions`` manifests)."""
    res, desc = _folder(store, run_id, task, task_name)
    folder = res.run_folder_id
    refs: dict[str, Any] = {
        "observation_refs": (
            _put(
                store,
                folder,
                "analysis/observations.json",
                [o.to_dict() for o in observations],
            ),
        ),
        "findings_ref": _put(
            store, folder, findings_path, [f.to_dict() for f in findings]
        ),
        "cases_ref": _put(
            store, folder, "analysis/cases.json", [c.to_dict() for c in cases]
        ),
        "actions_ref": _put(
            store, folder, "analysis/actions.json", [a.to_dict() for a in actions]
        ),
    }

    def build(n: int, previous: str | None) -> RunManifest:
        return RunManifest(
            engagement_id=f"{ACCOUNT}/{task}/{task_name}",
            run_id=run_id,
            revision=n,
            previous_object_id=previous,
            task=task,
            task_name=task_name,
            source_mode=SourceMode.CUSTOMER_WORKSPACE,
            storage_policy=StoragePolicy.DRIVE_REQUIRED,
            descriptor_ref=_ref(desc, DESCRIPTOR_NAME),
            refs=(),
            states=STATES,
            committed_at=f"2026-10-08T10:0{n}:00+00:00",
            **refs,
        )

    for _ in range(revisions):
        append_manifest(store, folder, build)
    if registered:
        (handle,) = ensure_registry(store, ACCOUNT, account_name=NAME)
        register(
            store,
            handle,
            Registration(
                registration_id=registration_id(run_id),
                kind="run",
                run_id=run_id,
                engagement_id=f"{ACCOUNT}/{task}/{task_name}",
                account_key=ACCOUNT,
                task=task,
                task_name=task_name,
                route=res.route,
                source_mode=SourceMode.CUSTOMER_WORKSPACE,
                storage_policy=StoragePolicy.DRIVE_REQUIRED,
                run_folder_id=folder,
                descriptor_ref=None,
                observation_summary_ref=None,
                acl_classification="internal_only",
                principal_id="perm-owner-0001",
                registered_at="2026-10-08T09:00:00+00:00",
                provenance={"origin": "drive_run"},
            ),
        )
    return res


def load(store: InMemoryEngagementStorage, **over: Any) -> PriorRecords:
    kwargs: dict[str, Any] = {
        "account_key": ACCOUNT,
        "workspace_id": WS,
        "exclude_run_id": CURRENT_RUN,
    }
    kwargs.update(over)
    return load_prior(store, **kwargs)


def history_store() -> tuple[InMemoryEngagementStorage, RunAssessment, RunAssessment]:
    """A health run, its follow-up and a standalone troubleshooting case."""
    base, j42 = runs()
    store = _store()
    commit_run(store, BASE_RUN, observations=base.observations)
    commit_run(
        store,
        J42_RUN,
        observations=j42.observations,
        findings=j42.findings,
        actions=j42.actions,
    )
    case, finding = standalone_case()
    commit_run(
        store,
        CASE_RUN,
        task="troubleshoot",
        task_name="job-42",
        findings=(finding,),
        cases=(case,),
    )
    return store, base, j42


# ---- load_prior ----------------------------------------------------------------------


def test_loads_every_task_folder_of_the_workspace() -> None:
    store, base, j42 = history_store()
    other = assessed(PriorRecords(), OTHER_WS_RUN, CURRENT, 8, ws="999")
    commit_run(
        store,
        OTHER_WS_RUN,
        task_name="ws-999",
        observations=other.observations,
        findings=other.findings,
        actions=other.actions,
    )
    prior = load(store)

    assert prior.unavailable == ()
    assert {c.observation for c in prior.observations} == {
        *base.observations,
        *j42.observations,
    }
    assert {c.registration_id for c in prior.observations} == {
        registration_id(BASE_RUN),
        registration_id(J42_RUN),
    }
    case, finding = standalone_case()
    assert set(prior.findings) == {*j42.findings, finding}
    assert prior.cases == (case,)
    assert prior.actions == j42.actions


def test_none_workspace_loads_every_workspace() -> None:
    store, _, _ = history_store()
    other = assessed(PriorRecords(), OTHER_WS_RUN, CURRENT, 8, ws="999")
    commit_run(
        store,
        OTHER_WS_RUN,
        task_name="ws-999",
        observations=other.observations,
        findings=other.findings,
        actions=other.actions,
    )
    prior = load(store, workspace_id=None)
    assert {c.observation.workspace_id for c in prior.observations} == {WS, "999"}
    assert {a.action_id for a in prior.actions} >= {a.action_id for a in other.actions}


def test_excluded_run_is_not_prior() -> None:
    store, base, _ = history_store()
    prior = load(store, exclude_run_id=J42_RUN)
    assert {c.observation for c in prior.observations} == set(base.observations)
    assert prior.actions == ()


def test_only_folder_restricts_to_one_registered_folder() -> None:
    base, j42 = runs()
    store = _store()
    commit_run(store, BASE_RUN, observations=base.observations)
    res = commit_run(store, J42_RUN, observations=j42.observations)
    prior = load(store, only_folder=res.run_folder_id)
    assert {c.observation for c in prior.observations} == set(j42.observations)


def test_only_folder_unregistered_is_read_directly_with_a_warning() -> None:
    base, _ = runs()
    store = _store()
    res = commit_run(store, BASE_RUN, observations=base.observations, registered=False)
    warnings: list[str] = []
    prior = load(store, only_folder=res.run_folder_id, warnings=warnings)
    assert {c.observation for c in prior.observations} == set(base.observations)
    assert {c.registration_id for c in prior.observations} == {
        registration_id(BASE_RUN)
    }
    assert any("not in the account registry" in w for w in warnings)


def test_only_folder_unreadable_is_unavailable_not_raised() -> None:
    base, _ = runs()
    store = _store()
    commit_run(store, BASE_RUN, observations=base.observations)
    prior = load(store, only_folder="no-such-folder")
    assert prior.observations == ()
    (gone,) = prior.unavailable
    assert gone.object_id == "no-such-folder" and gone.registration is None


def test_highest_finding_revision_wins_across_folders() -> None:
    store, _, j42 = history_store()
    (finding,) = j42.findings
    later = replace(
        finding,
        revision=2,
        revisions=(*finding.revisions, replace(finding.revisions[-1], revision=2)),
    )
    commit_run(
        store,
        "20261009_32345678-1234-4234-8234-123456789abc",
        task="troubleshoot",
        task_name="job-42-again",
        findings=(later,),
    )
    prior = load(store)
    (loaded,) = [f for f in prior.findings if f.finding_id == finding.finding_id]
    assert loaded.revision == 2


def test_latest_manifest_revision_is_read() -> None:
    base, _ = runs()
    store = _store()
    commit_run(store, BASE_RUN, observations=base.observations, revisions=3)
    prior = load(store)
    assert {c.committed_revision for c in prior.observations} == {3}


def test_phase2_findings_manifest_is_not_read_as_findings() -> None:
    _, j42 = runs()
    store = _store()
    commit_run(
        store,
        J42_RUN,
        observations=j42.observations,
        findings=j42.findings,
        findings_path="findings-manifest.json",
    )
    prior = load(store)
    assert prior.findings == () and prior.unavailable == ()
    assert prior.observations


def test_missing_account_folder_is_unavailable() -> None:
    prior = load(_store())
    (gone,) = prior.unavailable
    assert gone.registration is None and "registry" in gone.reason.lower()
    assert prior == PriorRecords(unavailable=prior.unavailable)


class _HidingStore(InMemoryEngagementStorage):
    """Hides chosen objects from listings (an eventually-consistent sibling)."""

    def __init__(self) -> None:
        super().__init__(root_id="my-root", owner_domain="example.com")
        self.hidden: set[str] = set()

    def list_children(self, parent_id, *, name=None, folders_only=False):  # type: ignore[no-untyped-def]
        out = super().list_children(parent_id, name=name, folders_only=folders_only)
        return [o for o in out if o.id not in self.hidden]


def test_ambiguous_registry_level_is_unavailable_not_raised() -> None:
    store = _store()
    root = store.root_folder_id()
    for identity in ("segment:starboard", "segment:other"):
        store.add_folder(root, "starboard", properties={IDENTITY_PROPERTY: identity})
    prior = load(store)
    (gone,) = prior.unavailable
    assert gone.registration is None and gone.status == "history_unavailable"
    assert "registry" in gone.reason.lower()


def test_registrations_of_duplicate_account_folders_merge_with_a_warning() -> None:
    base, j42 = runs()
    store = _HidingStore()
    root = store.root_folder_id()
    starboard = store.add_folder(
        root, "starboard", properties={IDENTITY_PROPERTY: "segment:starboard"}
    )
    earliest = store.add_folder(
        starboard.id,
        "Example Old",
        properties={IDENTITY_PROPERTY: f"account:{ACCOUNT}"},
    )
    store.hidden = {earliest.id}
    later = commit_run(store, BASE_RUN, observations=base.observations)
    store.hidden = set()
    current = commit_run(
        store,
        J42_RUN,
        observations=j42.observations,
        findings=j42.findings,
        actions=j42.actions,
    )
    assert later.account_folder_id != earliest.id
    assert current.account_folder_id == earliest.id
    notes: list[str] = []
    prior = load(store, warnings=notes)
    assert prior.unavailable == ()
    assert {c.observation for c in prior.observations} == {
        *base.observations,
        *j42.observations,
    }
    dup = [n for n in notes if n.startswith("duplicate_account_folders:")]
    assert dup and earliest.id in dup[0] and later.account_folder_id in dup[0]


def test_unreadable_registry_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    store, _, _ = history_store()
    (handle,) = ensure_registry(store, ACCOUNT, account_name=NAME)
    listing = store.list_children

    def unreadable(parent_id: str, **kw: Any) -> Any:
        if parent_id == handle.registrations_folder_id:
            raise StorageError("registry listing failed")
        return listing(parent_id, **kw)

    monkeypatch.setattr(store, "list_children", unreadable)
    prior = load(store)
    assert prior.observations == () and prior.findings == ()
    assert [u.registration for u in prior.unavailable] == [None]
    assert prior.unavailable[0].status == "history_unavailable"


def test_revoked_run_folder_is_unavailable_and_others_load() -> None:
    store, base, j42 = history_store()
    j42_folder = _run_folder(store, J42_RUN)
    store.set_access(j42_folder, can_add_children=False)
    prior = load(store)
    assert {c.observation for c in prior.observations} == set(base.observations)
    (gone,) = prior.unavailable
    assert gone.registration is not None and gone.registration.run_id == J42_RUN
    assert gone.records == ("observations", "findings", "cases", "actions")
    assert not {f.finding_id for f in prior.findings} & {
        f.finding_id for f in j42.findings
    }


def _run_folder(store: InMemoryEngagementStorage, run_id: str) -> str:
    (handle,) = ensure_registry(store, ACCOUNT, account_name=NAME)
    from starboard_core.engagement.registry import list_registrations

    (view,) = [
        v
        for v in list_registrations(store, (handle,), account_key=ACCOUNT)
        if v.registration and v.registration.run_id == run_id
    ]
    assert view.registration is not None and view.registration.run_folder_id
    return view.registration.run_folder_id


def test_corrupt_record_is_unavailable_for_that_kind_only() -> None:
    store, base, j42 = history_store()
    folder = _run_folder(store, J42_RUN)
    (actions_obj,) = [
        o for o in store.list_children(folder) if o.name == "actions.json"
    ]
    store.corrupt_object(actions_obj.id)
    prior = load(store)
    assert prior.actions == ()
    assert set(j42.findings) <= set(prior.findings)
    (gone,) = prior.unavailable
    assert gone.records == ("actions",)
    assert gone.registration is not None and gone.registration.run_id == J42_RUN


def test_imported_local_gives_observations_only() -> None:
    base, _ = runs()
    store = _store()
    res = commit_run(store, J42_RUN)
    summary = _put(
        store,
        res.account_folder_id,
        "import-summary.json",
        {"observations": [o.to_dict() for o in base.observations]},
    )
    (handle,) = ensure_registry(store, ACCOUNT, account_name=NAME)
    reg_id = "reg_imp_" + "c" * 24
    register(
        store,
        handle,
        Registration(
            registration_id=reg_id,
            kind="imported_local",
            run_id=BASE_RUN,
            engagement_id=f"{ACCOUNT}/workspace/ws-123",
            account_key=ACCOUNT,
            task="workspace",
            task_name="ws-123",
            route=res.route,
            source_mode=SourceMode.CUSTOMER_WORKSPACE,
            storage_policy=StoragePolicy.DRIVE_REQUIRED,
            run_folder_id=None,
            descriptor_ref=None,
            observation_summary_ref=summary,
            acl_classification="internal_only",
            principal_id="perm-owner-0001",
            registered_at="2026-10-08T09:00:00+00:00",
            provenance={
                "origin": "local_reference",
                "local_run_id": BASE_RUN,
                "approved_by": "operator-1",
            },
        ),
    )
    prior = load(store)
    assert {c.observation for c in prior.observations} == set(base.observations)
    assert {(c.committed_revision, c.registration_id) for c in prior.observations} == {
        (1, reg_id)
    }
    (imported,) = prior.unavailable
    assert imported.records == ("findings", "cases", "actions")
    assert imported.registration is not None
    assert imported.registration.registration_id == reg_id


def test_auth_failure_is_raised() -> None:
    store, _, _ = history_store()

    def boom(*_: Any, **__: Any) -> Any:
        raise StorageAuthError("token expired")

    store.get_stream = boom  # type: ignore[method-assign]
    with pytest.raises(StorageAuthError):
        load(store)


def test_load_is_deterministic() -> None:
    store, _, _ = history_store()
    assert load(store) == load(store)


def _downloads(store: InMemoryEngagementStorage) -> list[str]:
    """The names of the objects downloaded from now on."""
    names: list[str] = []
    get_stream = store.get_stream

    def counted(object_id: str, *args: Any, **kwargs: Any) -> Any:
        names.append(store.get(object_id).name)
        return get_stream(object_id, *args, **kwargs)

    store.get_stream = counted  # type: ignore[method-assign]
    return names


def test_each_prior_descriptor_is_read_once() -> None:
    store, _, _ = history_store()
    names = _downloads(store)
    prior = load(store, workspace_id=None)
    assert len(prior.run_manifests) == 3
    # The registry check reads each descriptor; reading the manifest does not again.
    assert names.count(DESCRIPTOR_NAME) == 3, names
    assert names.count("rev-000001.json") == 3, names  # one manifest per run


def test_kinds_limits_the_record_sets_read() -> None:
    store, base, j42 = history_store()
    names = _downloads(store)
    prior = load(store, workspace_id=None, kinds=("observations",))
    assert {"findings.json", "cases.json", "actions.json"}.isdisjoint(names), names
    assert len(prior.observations) == len(base.observations) + len(j42.observations)
    assert prior.findings == () and prior.cases == () and prior.actions == ()
    full = load(store, workspace_id=None)
    assert prior.observations == full.observations
    assert prior.run_manifests == full.run_manifests


def test_unknown_kind_is_a_value_error() -> None:
    with pytest.raises(ValueError, match="unknown record kinds"):
        load(_store(), kinds=("observations", "plays"))


# ---- load_prior_local ----------------------------------------------------------------


def _local_authorization(run_id: str, account_key: str = ACCOUNT) -> dict[str, Any]:
    """A public LOCAL run authorization of ``account_key`` (D4-16 ownership)."""
    return RunAuthorization(
        engagement_id=f"{account_key}/health_check/ws-{WS}",
        run_id=run_id,
        intent="health_check",
        task=f"ws-{WS}",
        account=AccountRef(id=account_key, display_name=NAME, verifier="operator"),
        requested_scope={"account_key": account_key, "workspace_ids": [WS]},
        authorized_scope={"account_key": account_key, "workspace_ids": [WS]},
        reporting_interval="unspecified",
        timezone="UTC",
        source_mode=SourceMode.CUSTOMER_WORKSPACE,
        storage_policy=StoragePolicy.LOCAL,
        audience="operator",
        methodology_version="m1",
    ).to_dict()


def _write_local(
    root: Path,
    run_id: str,
    *,
    account_key: str = ACCOUNT,
    created_at: str | None = None,
    **records: Any,
) -> None:
    analysis = root / run_id / "analysis"
    analysis.mkdir(parents=True)
    (analysis / "run-authorization.json").write_text(
        json.dumps(_local_authorization(run_id, account_key))
    )
    if created_at is not None:
        (analysis / "storage-preflight.json").write_text(
            json.dumps({"run_id": run_id, "created_at": created_at})
        )
    for name, items in records.items():
        body = json.dumps([i.to_dict() for i in items]) + "\n"
        (analysis / f"{name}.json").write_text(body)


def test_local_layout_gives_the_same_shape(tmp_path: Path) -> None:
    base, j42 = runs()
    case, finding = standalone_case()
    _write_local(tmp_path, BASE_RUN, observations=base.observations)
    _write_local(
        tmp_path,
        J42_RUN,
        observations=j42.observations,
        findings=j42.findings,
        actions=j42.actions,
    )
    _write_local(tmp_path, CASE_RUN, findings=(finding,), cases=(case,))
    _write_local(tmp_path, CURRENT_RUN, observations=j42.observations)
    (tmp_path / "notes").mkdir()

    prior = load_prior_local(
        (tmp_path,), account_key=ACCOUNT, workspace_id=WS, exclude_run_id=CURRENT_RUN
    )
    assert prior.unavailable == ()
    assert {c.observation for c in prior.observations} == {
        *base.observations,
        *j42.observations,
    }
    assert {c.registration_id for c in prior.observations} == {
        registration_id(BASE_RUN),
        registration_id(J42_RUN),
    }
    assert set(prior.findings) == {*j42.findings, finding}
    assert prior.cases == (case,)
    assert prior.actions == j42.actions


def test_local_corrupt_record_is_unavailable(tmp_path: Path) -> None:
    base, _ = runs()
    _write_local(tmp_path, BASE_RUN, observations=base.observations)
    (tmp_path / BASE_RUN / "analysis" / "findings.json").write_text("{not json")
    prior = load_prior_local(
        (tmp_path,), account_key=ACCOUNT, workspace_id=WS, exclude_run_id=CURRENT_RUN
    )
    assert {c.observation for c in prior.observations} == set(base.observations)
    (gone,) = prior.unavailable
    assert gone.records == ("findings",) and gone.object_id == BASE_RUN


def test_observation_list_may_be_wrapped(tmp_path: Path) -> None:
    base, _ = runs()
    _write_local(tmp_path, BASE_RUN)
    analysis = tmp_path / BASE_RUN / "analysis"
    (analysis / "observations.json").write_bytes(
        encode_json({"observations": [o.to_dict() for o in base.observations]})
    )
    prior = load_prior_local(
        (tmp_path,), account_key=ACCOUNT, workspace_id=WS, exclude_run_id=CURRENT_RUN
    )
    assert {c.observation for c in prior.observations} == set(base.observations)
    assert all(isinstance(c.observation, Observation) for c in prior.observations)


def test_local_prior_reads_every_case_root_of_the_account(tmp_path: Path) -> None:
    """D4-16: a sibling task root's records (a later finding revision, a case) count."""
    base, j42 = runs()
    health = tmp_path / "health_check" / "ws-123"
    trouble = tmp_path / "troubleshooting" / "job-42"
    _write_local(health, BASE_RUN, observations=base.observations)
    _write_local(health, J42_RUN, observations=j42.observations, findings=j42.findings)
    detected = j42.findings[0]
    nxt = detected.revision + 1
    revised = replace(
        detected,
        revision=nxt,
        revisions=(*detected.revisions, replace(detected.revisions[-1], revision=nxt)),
    )
    case, finding = standalone_case()
    _write_local(trouble, CASE_RUN, findings=(revised, finding), cases=(case,))

    prior = load_prior_local(
        (health, trouble, tmp_path / "discovery" / "gone"),
        account_key=ACCOUNT,
        workspace_id=WS,
        exclude_run_id=CURRENT_RUN,
    )
    assert prior.unavailable == ()
    by_key = {f.finding_key: f for f in prior.findings}
    assert by_key[detected.finding_key].revision == detected.revision + 1
    assert finding in prior.findings and prior.cases == (case,)
    assert {c.registration_id for c in prior.observations} == {
        registration_id(BASE_RUN),
        registration_id(J42_RUN),
    }


def test_local_prior_skips_the_current_run_in_any_case_root(tmp_path: Path) -> None:
    _, j42 = runs()
    _write_local(tmp_path / "a" / "x", CURRENT_RUN, observations=j42.observations)
    prior = load_prior_local(
        (tmp_path / "a" / "x",),
        account_key=ACCOUNT,
        workspace_id=WS,
        exclude_run_id=CURRENT_RUN,
    )
    assert prior == PriorRecords()


OTHER_ACCOUNT = "AR-000000002"


def test_local_prior_reads_only_runs_this_account_owns(tmp_path: Path) -> None:
    """D4-16 sec-M1: a run of another account under the same slug root is skipped
    whole, silently: its records (even ones claiming this account) and its unreadable
    files leave no record, no gap and no trace of its run id."""
    base, j42 = runs()
    _write_local(tmp_path, BASE_RUN, observations=base.observations)
    _write_local(
        tmp_path,
        J42_RUN,
        account_key=OTHER_ACCOUNT,
        observations=j42.observations,
        findings=j42.findings,
    )
    (tmp_path / J42_RUN / "analysis" / "cases.json").write_text("{secret-not-json")
    notes: list[str] = []
    prior = load_prior_local(
        (tmp_path,),
        account_key=ACCOUNT,
        workspace_id=WS,
        exclude_run_id=CURRENT_RUN,
        warnings=notes,
    )
    assert {c.observation for c in prior.observations} == set(base.observations)
    assert prior.findings == () and prior.unavailable == () and notes == []
    assert J42_RUN not in repr(prior) and "secret" not in repr(prior)


@pytest.mark.parametrize(
    "authorization", ["missing", "{not json", json.dumps({"run_id": "x"})]
)
def test_local_run_without_a_readable_authorization_is_skipped(
    tmp_path: Path, authorization: str
) -> None:
    base, _ = runs()
    _write_local(tmp_path, BASE_RUN, observations=base.observations)
    (tmp_path / BASE_RUN / "analysis" / "findings.json").write_text("{not json")
    desc = tmp_path / BASE_RUN / "analysis" / "run-authorization.json"
    if authorization == "missing":
        desc.unlink()
    else:
        desc.write_text(authorization)
    prior = load_prior_local(
        (tmp_path,), account_key=ACCOUNT, workspace_id=WS, exclude_run_id=CURRENT_RUN
    )
    assert prior == PriorRecords()


def test_local_prior_does_not_follow_a_symlinked_run_dir(tmp_path: Path) -> None:
    base, _ = runs()
    elsewhere = tmp_path / "elsewhere"
    _write_local(elsewhere, BASE_RUN, observations=base.observations)
    case_root = tmp_path / "case"
    case_root.mkdir()
    (case_root / BASE_RUN).symlink_to(elsewhere / BASE_RUN, target_is_directory=True)
    prior = load_prior_local(
        (case_root,), account_key=ACCOUNT, workspace_id=WS, exclude_run_id=CURRENT_RUN
    )
    assert prior == PriorRecords()


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a chmod 000 dir")
def test_unreadable_case_root_is_a_warning_not_a_crash(tmp_path: Path) -> None:
    base, _ = runs()
    good, locked = tmp_path / "good", tmp_path / "locked"
    _write_local(good, BASE_RUN, observations=base.observations)
    _write_local(locked, J42_RUN, observations=base.observations)
    locked.chmod(0)
    notes: list[str] = []
    try:
        prior = load_prior_local(
            (good, locked),
            account_key=ACCOUNT,
            workspace_id=WS,
            exclude_run_id=CURRENT_RUN,
            warnings=notes,
        )
    finally:
        locked.chmod(0o755)
    assert {c.registration_id for c in prior.observations} == {
        registration_id(BASE_RUN)
    }
    assert prior.unavailable == ()
    assert len(notes) == 1 and str(locked) in notes[0] and "not readable" in notes[0]


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a chmod 000 dir")
def test_unreadable_record_of_an_owned_run_is_unavailable(tmp_path: Path) -> None:
    base, _ = runs()
    _write_local(tmp_path, BASE_RUN, observations=base.observations)
    rec = tmp_path / BASE_RUN / "analysis" / "observations.json"
    rec.chmod(0)
    try:
        prior = load_prior_local(
            (tmp_path,),
            account_key=ACCOUNT,
            workspace_id=WS,
            exclude_run_id=CURRENT_RUN,
        )
    finally:
        rec.chmod(0o644)
    (gone,) = prior.unavailable
    assert gone.object_id == BASE_RUN and gone.records == ("observations",)


def test_same_day_runs_rank_by_created_at_not_run_id(tmp_path: Path) -> None:
    """Two same-day runs in different task roots: the later by ``created_at`` wins,
    whichever run ID sorts first."""
    case, _finding = standalone_case()
    early_id = "20261008_f2345678-1234-4234-8234-123456789abc"
    late_id = "20261008_02345678-1234-4234-8234-123456789abc"
    assert late_id < early_id
    earlier, later = replace(case, run_id=early_id), replace(case, run_id=late_id)
    _write_local(
        tmp_path / "health_check" / "ws-123",
        early_id,
        created_at="2026-10-08T09:00:00+00:00",
        cases=(earlier,),
    )
    _write_local(
        tmp_path / "troubleshooting" / "job-42",
        late_id,
        created_at="2026-10-08T17:00:00+00:00",
        cases=(later,),
    )
    prior = load_prior_local(
        (tmp_path / "health_check" / "ws-123", tmp_path / "troubleshooting" / "job-42"),
        account_key=ACCOUNT,
        workspace_id=WS,
        exclude_run_id=CURRENT_RUN,
    )
    assert prior.cases == (later,)


# ---- run-4 A1: candidates carry their run's task and findings-manifest presence ------


def test_drive_candidates_carry_task_and_manifest_presence() -> None:
    store, base, _ = history_store()
    prior = load(store)
    by_run = {c.observation.run_id: c for c in prior.observations}
    assert by_run[BASE_RUN].run_task == "workspace"
    # commit_run commits no findings-manifest.json in refs.
    assert by_run[BASE_RUN].run_manifest is False


def test_local_candidates_carry_task_and_manifest_presence(tmp_path: Path) -> None:
    base, j42 = runs()
    _write_local(tmp_path, BASE_RUN, observations=base.observations)
    _write_local(tmp_path, J42_RUN, observations=j42.observations)
    (tmp_path / J42_RUN / "findings-manifest.json").write_text("{}")
    prior = load_prior_local(
        (tmp_path,), account_key=ACCOUNT, workspace_id=WS, exclude_run_id=CURRENT_RUN
    )
    meta = {(c.observation.run_id, c.run_task, c.run_manifest) for c in prior.observations}
    assert meta == {(BASE_RUN, "health_check", False), (J42_RUN, "health_check", True)}
