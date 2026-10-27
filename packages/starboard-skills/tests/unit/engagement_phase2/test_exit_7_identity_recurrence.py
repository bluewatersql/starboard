"""P2-G14 exit test 7 - identity and recurrence.

* Two same-day runs get distinct run IDs and run folders.
* health (account route) -> case (ticket route) -> health (override route): each
  comparison key's baseline is the last eligible observation across all three
  folders, whatever route registered it.
* A late run that measured an older window does not displace the selection.
* A corrupted registry index is ignored and rebuilt from the registrations listing.
* An inaccessible other-operator registration is ``history_unavailable``.
* Lost current evidence is ``missing_current_evidence``, which the kernel
  ``finding_states`` turns into ``unknown_current`` keeping the last severity.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from starboard_core.engagement import finding_states
from starboard_core.engagement.records import (
    BaselineSelection,
    FindingRecord,
    FindingRevision,
    concern_key,
    episode_id,
    finding_id,
    registration_id,
)
from starboard_core.engagement.registry import (
    ensure_registry,
    list_registrations,
    read_index,
    register,
)
from starboard_core.engagement.run_id import new_run_id
from starboard_core.ports.engagement_storage import Grant
from starboard_skills.helpers import engagement

from ._support import (
    ACCOUNT,
    INTERNAL,
    PREFLIGHT,
    WIDE,
    WS,
    observation,
    ok,
    sink_put,
)

AUG = ("2026-08-01", "2026-08-31")
SEP = ("2026-09-01", "2026-09-30")
JUL = ("2026-07-01", "2026-07-31")
OCT = ("2026-10-01", "2026-10-31")


def _preflight(task: str = "health_check", task_name: str = "ws-123") -> tuple[str, ...]:
    argv = list(PREFLIGHT)
    argv[argv.index("--task") + 1] = task
    argv[argv.index("--task-name") + 1] = task_name
    return tuple(argv)


def _run(capsys: Any, *route_flags: str, task: str = "health_check",
         task_name: str = "ws-123") -> tuple[str, str, dict[str, Any]]:
    """preflight -> verify-identity -> route; returns ``(run_id, run_folder_id, route)``."""
    pre = ok(capsys, *_preflight(task, task_name))
    ok(capsys, "verify-identity", "--run-id", pre["run_id"], "--profile", "acme",
       "--expected-workspace-id", WS)
    route = ok(capsys, "route", "--run-id", pre["run_id"], *route_flags)
    return pre["run_id"], route["run_folder_id"], route


def _observe(capsys: Any, store: Any, run_id: str, rf: str, *obs: Any) -> None:
    """Write the run's observations through its sink and commit the analysis stage."""
    sink_put(store, rf, {engagement.OBSERVATIONS_PATH: [o.to_dict() for o in obs]})
    ok(capsys, "commit", "--run-folder", rf, "--stage", "analysis")


def _history(capsys: Any, rf: str, start: str, end: str) -> dict[str, Any]:
    return ok(capsys, "history", "--run-folder", rf, "--interval-start", start,
              "--interval-end", end)


def _by_entity(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Selected entries keyed by entity ID (the comparison key carries it)."""
    out: dict[str, dict[str, Any]] = {}
    for entry in data["selected"]:
        entity = next(p for p in entry["key"] if p.startswith("job-"))
        out[entity] = entry
    return out


def _ticket_flags(store: Any, tmp_path: Path) -> tuple[str, ...]:
    shared = store.add_shared_drive(
        "asqs-root", "ASQs", drive_id="d1",
        grants=(Grant("group", "fileOrganizer", "databricks.com"),),
    ).id
    ticket = tmp_path / "ticket.json"
    ticket.write_text(json.dumps({"ticket_ref": {
        "schema_version": "1", "ar_key": "AR-000000001", "title": "Cost review",
        "account_id": ACCOUNT, "account_name": "Acme Corp", "resolution": "validated",
    }}))
    return ("--ticket-ref", str(ticket), "--shared-root-id", shared,
            "--internal-domain", "databricks.com")


def _override_flags(store: Any) -> tuple[str, ...]:
    folder = store.create_folder(store.root_folder_id(), "Override", {})
    store.set_access(folder.id, grants=INTERNAL)
    return ("--override-folder-id", folder.id, "--internal-domain", "databricks.com")


@pytest.fixture
def three_routes(capsys, store, tmp_path) -> dict[str, Any]:
    """health(account, Aug: job-1 + job-2) -> case(ticket, Sep: job-1) -> health(override)."""
    h1, rf1, r1 = _run(capsys)
    _observe(capsys, store, h1, rf1,
             observation(h1, "job-1", value=10.0, start=AUG[0], end=AUG[1],
                         as_of="2026-09-01T00:00:00+00:00"),
             observation(h1, "job-2", value=20.0, start=AUG[0], end=AUG[1],
                         as_of="2026-09-01T00:00:00+00:00"))
    c2, rf2, r2 = _run(capsys, *_ticket_flags(store, tmp_path),
                       task="troubleshooting", task_name="slow-job")
    _observe(capsys, store, c2, rf2,
             observation(c2, "job-1", value=11.0, start=SEP[0], end=SEP[1],
                         as_of="2026-10-01T00:00:00+00:00"))
    h3, rf3, r3 = _run(capsys, *_override_flags(store))
    sink_put(store, rf3, {engagement.OBSERVATIONS_PATH: [
        observation(h3, "job-1", value=12.0, start=OCT[0], end=OCT[1]).to_dict(),
        observation(h3, "job-2", value=21.0, start=OCT[0], end=OCT[1]).to_dict(),
    ]})
    assert (r1["route"], r2["route"], r3["route"]) == ("account", "ticket", "override")
    return {
        "h1": h1, "rf1": rf1, "c2": c2, "rf2": rf2, "h3": h3, "rf3": rf3,
        "aug": {e: observation(h1, e, start=AUG[0], end=AUG[1]).observation_id
                for e in ("job-1", "job-2")},
        "sep": observation(c2, "job-1", start=SEP[0], end=SEP[1]).observation_id,
    }


@pytest.mark.unit
class TestIdentity:
    """Spec P2-G14 item 7: run identity."""

    def test_two_same_day_runs_get_distinct_ids_and_folders(self, capsys) -> None:
        a, rf_a, _ = _run(capsys)
        b, rf_b, _ = _run(capsys)
        assert a != b and rf_a != rf_b
        assert a.split("_")[0] == b.split("_")[0]  # same UTC date prefix
        assert ok(capsys, "status", "--run-id", a)["run_folder_id"] == rf_a
        assert ok(capsys, "status", "--run-id", b)["run_folder_id"] == rf_b


@pytest.mark.unit
class TestRecurrence:
    """Spec P2-G14 item 7: per-key baselines across routes and folders."""

    def test_each_key_takes_the_last_eligible_observation_across_folders(
        self, capsys, three_routes
    ) -> None:
        t = three_routes
        data = _history(capsys, t["rf3"], *OCT)
        assert data["candidates"] == 3 and data["unavailable"] == []
        picked = _by_entity(data)
        assert picked["job-1"]["baseline_observation_id"] == t["sep"]  # case run
        assert picked["job-2"]["baseline_observation_id"] == t["aug"]["job-2"]  # health run
        assert {e["comparison"] for e in picked.values()} == {"continuing"}

    def test_late_run_with_an_older_window_does_not_displace_the_baseline(
        self, capsys, store, three_routes
    ) -> None:
        t = three_routes
        late, rf_late, _ = _run(capsys, task_name="ws-123-backfill")
        _observe(capsys, store, late, rf_late,
                 observation(late, "job-1", value=99.0, start=JUL[0], end=JUL[1],
                             as_of="2026-10-15T00:00:00+00:00"))
        data = _history(capsys, t["rf3"], *OCT)
        assert data["candidates"] == 4
        picked = _by_entity(data)
        assert picked["job-1"]["baseline_observation_id"] == t["sep"]
        assert picked["job-2"]["baseline_observation_id"] == t["aug"]["job-2"]


@pytest.mark.unit
class TestRegistryRecovery:
    """Spec P2-G14 item 7: the index is a cache; the listing is the truth."""

    def test_corrupted_index_is_recovered_from_the_listing(
        self, capsys, store, three_routes
    ) -> None:
        built = ok(capsys, "rebuild-index", "--account-key", ACCOUNT)
        assert built["entries"] == 3
        handle = ensure_registry(store, ACCOUNT)[0]
        index_objects = [c for c in store.list_children(handle.index_folder_id)
                         if not c.is_folder]
        assert index_objects
        for obj in index_objects:
            store.corrupt_object(obj.id)
        assert read_index(store, handle) is None  # corrupt cache is not trusted

        picked = _by_entity(_history(capsys, three_routes["rf3"], *OCT))
        assert picked["job-1"]["baseline_observation_id"] == three_routes["sep"]

        rebuilt = ok(capsys, "rebuild-index", "--account-key", ACCOUNT)
        assert rebuilt["entries"] == 3
        assert rebuilt["index_revision"] > built["index_revision"]
        recovered = read_index(store, handle)
        assert recovered is not None and len(recovered) == 3

    def test_inaccessible_other_operator_registration_is_history_unavailable(
        self, capsys, store
    ) -> None:
        mine, rf, _ = _run(capsys)
        handle = ensure_registry(store, ACCOUNT)[0]
        own = next(v.registration for v in list_registrations(
            store, (handle,), account_key=ACCOUNT) if v.registration is not None)
        other_run = new_run_id()
        # Another operator's run: its folder is not visible to this principal
        # (Drive answers 404 for folders you cannot see).
        register(store, handle, replace(
            own, registration_id=registration_id(other_run), run_id=other_run,
            run_folder_id="folder-of-another-operator", principal_id="perm-other-0002",
        ))
        sink_put(store, rf, {engagement.OBSERVATIONS_PATH: [
            observation(mine, "job-1", start=OCT[0], end=OCT[1]).to_dict()]})

        data = _history(capsys, rf, *OCT)
        assert data["candidates"] == 0
        assert [u["registration_id"] for u in data["unavailable"]] == [
            registration_id(other_run)]
        assert _by_entity(data)["job-1"]["comparison"] == "history_unavailable"

    def test_prior_run_whose_sharing_changed_is_history_unavailable(
        self, capsys, store
    ) -> None:
        prior, rf_prior, _ = _run(capsys)
        _observe(capsys, store, prior, rf_prior,
                 observation(prior, "job-1", start=SEP[0], end=SEP[1]))
        store.set_access(rf_prior, grants=WIDE)
        mine, rf, _ = _run(capsys)
        sink_put(store, rf, {engagement.OBSERVATIONS_PATH: [
            observation(mine, "job-1", start=OCT[0], end=OCT[1]).to_dict()]})

        data = _history(capsys, rf, *OCT)
        assert data["candidates"] == 0
        assert [u["registration_id"] for u in data["unavailable"]] == [
            registration_id(prior)]
        assert _by_entity(data)["job-1"]["comparison"] == "history_unavailable"


@pytest.mark.unit
class TestLostEvidence:
    """Spec P2-G14 item 7: lost current evidence keeps the last severity."""

    def test_lost_current_evidence_is_unknown_current_with_the_last_severity(
        self, capsys, store
    ) -> None:
        prior, rf_prior, _ = _run(capsys)
        base = observation(prior, "job-1", start=SEP[0], end=SEP[1])
        _observe(capsys, store, prior, rf_prior, base)
        mine, rf, _ = _run(capsys)
        lost = observation(mine, "job-1", start=OCT[0], end=OCT[1], state="unknown")
        sink_put(store, rf, {engagement.OBSERVATIONS_PATH: [lost.to_dict()]})

        data = _history(capsys, rf, *OCT)
        entry = _by_entity(data)["job-1"]
        assert entry["comparison"] == "missing_current_evidence"
        assert entry["baseline_observation_id"] == base.observation_id

        # Drive the kernel with the selection the CLI just persisted (``run recur
        # --run-folder`` applies the same call; see test_run_recur_drive).
        payload = drive_json(store, rf, engagement.BASELINE_PATH)
        selection = BaselineSelection.from_dict(payload)
        held = _finding(prior, base.observation_id, "serious")
        (state,) = finding_states([held], selection, [])  # no current measurement
        assert state.state == "unknown_current"
        assert state.last_confirmed_severity == "serious"
        assert state.episode_id == held.episode_id and state.run_id == mine


def _finding(run_id: str, obs_id: str, severity: str) -> FindingRecord:
    """A FindingRecord v1 for job-1 written by ``run_id`` (one ``detected`` revision)."""
    key = concern_key(ACCOUNT, WS, "job", "job-1", "rule:job_dbus")
    fid = finding_id(key)
    revision = FindingRevision(
        revision=1,
        run_id=run_id,
        reason="detected",
        severity=severity,
        symptom_confidence="confirmed",
        cause_confidence="unassessed",
        observation_ids=(obs_id,),
    )
    return FindingRecord(
        finding_id=fid,
        finding_key=key,
        concern_code="rule:job_dbus",
        family="unclassified",
        account_key=ACCOUNT,
        workspace_id=WS,
        entity_kind="job",
        entity_id="job-1",
        episode_id=episode_id(fid, run_id),
        episode_started_run_id=run_id,
        state="active",
        severity=severity,
        last_confirmed_severity=severity,
        symptom_confidence="confirmed",
        cause_confidence="unassessed",
        rule_id="job_dbus",
        rule_version=1,
        revision=1,
        revisions=(revision,),
        observation_ids=(obs_id,),
        run_id=run_id,
    )


def drive_json(store: Any, rf: str, rel: str) -> Any:
    from ._support import run_sink

    return json.loads(run_sink(store, rf).get_bytes(rel))


@pytest.mark.unit
class TestHistoryReadBudget:
    """History reads the prior runs' observations only, never findings."""

    def test_history_downloads_no_findings_from_prior_runs(self, capsys, store) -> None:
        names: list[str] = []
        for i in range(3):
            rid, rf, _ = _run(capsys)
            sink_put(store, rf, {
                engagement.OBSERVATIONS_PATH: [
                    observation(rid, "job-1", value=10.0 + i, start=AUG[0],
                                end=AUG[1]).to_dict()
                ],
                "analysis/findings.json": [],
            })
            ok(capsys, "commit", "--run-folder", rf, "--stage", "analysis")
        cur, rf_cur, _ = _run(capsys)
        sink_put(store, rf_cur, {engagement.OBSERVATIONS_PATH: [
            observation(cur, "job-1", value=12.0, start=SEP[0], end=SEP[1]).to_dict()
        ]})
        get_stream = store.get_stream

        def counted(object_id: str, *args: Any, **kwargs: Any) -> Any:
            names.append(store.get(object_id).name)
            return get_stream(object_id, *args, **kwargs)

        store.get_stream = counted
        data = _history(capsys, rf_cur, *SEP)
        assert data["candidates"] >= 3
        assert names.count("observations.json") >= 3, names
        assert "findings.json" not in names, names
