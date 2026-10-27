"""``run recur --run-folder``: registry-backed baseline selection written to Drive."""

from __future__ import annotations

import json
import re

import pytest
from starboard_core.engagement.write_guard import sandbox_diff

from .conftest import (
    commit_manifest,
    covered_ok,
    drive_files,
    evidence,
    make_drive_run,
    put_files,
    run_main,
)

PRIOR = "20260908_12345678-1234-4234-8234-000000000001"
TROUBLE = "20260920_12345678-1234-4234-8234-000000000002"  # newer, no findings-manifest
_OUTPUTS = (
    "analysis/observations.json", "analysis/findings.json", "analysis/health.json",
    "analysis/plays.json", "analysis/changes.json", "analysis/cases.json",
    "analysis/actions.json", "analysis/baseline-selection.json", "analysis/recur-result.json",
    "README.md",
)


def _finding(rule: str, entity: str, dbu: float | None) -> dict:
    return {
        "id": f"{rule}::{entity}", "rule_id": rule, "category": "warehouse",
        "severity": "high", "score": 1.0, "entity_id": entity,
        "evidence_dbu_estimate": dbu, "composite_key": f"{rule}::{entity}",
    }


def _manifest(
    start: str, end: str, findings: list[dict], run_date: str, *, degraded: bool = False
) -> str:
    return json.dumps({
        "snapshot_version": "2.0",
        "run_date": run_date,
        "workspace": "123",
        "facts_window": {"start": start, "end": end},
        "findings": findings,
        "degraded": degraded,
    })


def _current(run, window: tuple[str, str] = ("2026-09-08", "2026-10-07")) -> None:
    put_files(run, {"findings-manifest.json": _manifest(
        *window,
        [_finding("W-IDLE", "wh-1", 30.0), _finding("Q-SLOW", "q-1", 5.0)], "2026-10-08",
    )})


def _sized(opp: str, tier: str, value: float) -> dict:
    return {"id": opp, "target": "job:1", "tier": tier, "confidence": 7,
            "sizing": {"kind": "perf_metric", "metric": "pct", "value": value, "unit": "%",
                       "formula": "x"}}


def _backlog(*items: dict) -> dict:
    return {"workspace_id": "123", "generated_at": "2026-10-08T00:00:00Z", "items": list(items)}


_BACKLOG_PRIOR = _backlog(_sized("OPP-JOB-OVERLAP", "act_now", 80.0), _sized("OPP-GONE", "investigate", 5.0))
_BACKLOG_CURRENT = _backlog(_sized("OPP-JOB-OVERLAP", "act_now", 20.0), _sized("OPP-NEW", "not_now", 1.0))
_REVIEW = {"data": {"cost_delta": {
    "prior_run_date": "2026-09-08", "current_run_date": "2026-10-08",
    "improved": [{"composite_key": "W-IDLE::wh-1", "rule_id": "W-IDLE", "entity_id": "wh-1",
                  "prior_dbu": 40.0, "current_dbu": 30.0, "dbu_delta": -10.0, "dbu_delta_pct": -0.25}],
    "regressed": [], "newly_expensive": [], "persisting": [], "new_low_cost": [],
}}}


def _recur(run, capsys, *extra: str) -> tuple[int, str]:
    return run_main(["run", "recur", "--run-folder", run.folder_id, *extra], capsys)


def _registered_prior(
    drive_run, capsys, *, register: bool = True,
    window: tuple[str, str] = ("2026-08-08", "2026-09-07"),
    backlog: dict | None = None,
    run_id: str = PRIOR,
    task: str = "review",
    with_manifest: bool = True,
):
    """A committed prior run (Aug window) in the same store, optionally registered.

    ``task`` is the committed manifest's task; ``with_manifest=False`` commits no
    ``findings-manifest.json`` (e.g. a troubleshooting run): never a delta prior."""
    from starboard_core.engagement.policy import SourceMode, StoragePolicy
    from starboard_core.engagement.records import Registration, registration_id
    from starboard_core.engagement.registry import ensure_registry
    from starboard_core.engagement.registry import register as reg_put

    prior = make_drive_run(run_id=run_id, store=drive_run.store)
    put_files(prior, {"findings-manifest.json": _manifest(
        *window,
        [_finding("W-IDLE", "wh-1", 40.0), _finding("J-FAIL", "job-1", None)],
        f"{run_id[:4]}-{run_id[4:6]}-{run_id[6:8]}",
    )})
    code, _ = _recur(prior, capsys)
    assert code == 0
    files = drive_files(prior)
    refs = put_files(prior, {
        **({"findings-manifest.json": files["findings-manifest.json"]} if with_manifest else {}),
        "analysis/observations.json": files["analysis/observations.json"],
        "analysis/findings.json": files["analysis/findings.json"],
        **({"analysis/backlog.json": json.dumps(backlog)} if backlog else {}),
    })
    commit_manifest(  # a real commit lists every artifact of the run in its refs
        prior,
        refs=tuple(refs.values()),
        observation_refs=(refs["analysis/observations.json"],),
        findings_ref=refs["analysis/findings.json"],
        task=task,
    )
    if register:
        (handle,) = ensure_registry(drive_run.store, "acme", account_name="Acme")
        reg_put(drive_run.store, handle, Registration(
            registration_id=registration_id(run_id), kind="run", run_id=run_id,
            engagement_id=f"acme/{task}/ws-123", account_key="acme", task=task,
            task_name="ws-123", route="account", source_mode=SourceMode.CUSTOMER_WORKSPACE,
            storage_policy=StoragePolicy.DRIVE_REQUIRED, run_folder_id=prior.folder_id,
            descriptor_ref=None, observation_summary_ref=None,
            acl_classification="restricted", principal_id="perm-1",
            registered_at=f"{run_id[:4]}-{run_id[4:6]}-{run_id[6:8]}T10:00:00+00:00",
            provenance={"origin": "drive_run"},
        ))
    return prior


def _records(run) -> dict[str, dict]:
    """``analysis/findings.json`` (FindingRecord v1) of ``run``, keyed by rule ID."""
    from starboard_core.engagement.records import FindingRecord

    items = json.loads(drive_files(run)["analysis/findings.json"])
    assert isinstance(items, list)
    out = {}
    for item in items:
        FindingRecord.from_dict(item)  # schema-valid
        assert item["finding_key"].startswith("ck1|acme|123|")
        assert item["rule_id"] not in out, "one record per finding key"
        out[item["rule_id"]] = item
    return out


def _finding_obs(files: dict) -> list[dict]:
    from starboard_core.engagement.observations import FINDINGS_METHOD

    obs = json.loads(files["analysis/observations.json"])
    return [o for o in obs if o["method_version"] == FINDINGS_METHOD]


@pytest.mark.unit
class TestCoveredRecur:
    def test_first_run_is_baseline(self, covered_env, drive_run, capsys):
        _current(drive_run)
        before = covered_env.snapshot()
        code, out = _recur(drive_run, capsys)
        doc = covered_ok(covered_env, before, out)
        assert code == 0, doc
        data = doc["data"]
        assert data["baseline"] is True and data["candidates"] == 0
        assert data["run_folder_id"] == drive_run.folder_id
        assert sorted(r["path"] for r in data["refs"]) == sorted(_OUTPUTS)
        files = drive_files(drive_run)
        for rel in _OUTPUTS:
            assert rel in files
        rr = json.loads(files["analysis/recur-result.json"])
        assert rr["ok"] is True and rr["baseline"] is True
        assert rr["interval"] == {"start": "2026-09-08", "end": "2026-10-07"}
        assert rr["workspace_id"] == "123"
        assert len(_finding_obs(files)) == 4  # 2 present + 2 DBU estimates
        sel = json.loads(files["analysis/baseline-selection.json"])
        assert all(not r.get("baseline_observation_id") for r in sel["selected"])
        assert evidence(drive_run) == []  # derived artifacts, not acquired evidence
        # run-5 D5: a baseline compares nothing
        assert rr["comparable"] is False and rr["not_comparable_reason"] == "baseline"
        assert rr["prior_runs"] == []
        readme = files["README.md"].decode()
        assert "## Recur" in readme and "baseline — no prior run" in readme

    def test_window_mismatch_is_not_comparable(self, covered_env, drive_run, capsys):
        _registered_prior(drive_run, capsys, window=("2026-08-09", "2026-09-07"))
        _current(drive_run, ("2026-10-01", "2026-10-07"))
        code, out = _recur(drive_run, capsys)
        assert code == 0, out
        doc = json.loads(out)
        files = drive_files(drive_run)
        rr = json.loads(files["analysis/recur-result.json"])
        assert rr["baseline"] is False and rr["candidates"] > 0
        assert rr["comparable"] is False
        assert rr["not_comparable_reason"] == "window_mismatch"
        assert rr["window"] == {
            "comparable": False, "reason": "window_mismatch", "prior_run_id": PRIOR,
            "prior_lookback_days": 30, "current_lookback_days": 7,
        }
        assert rr["prior_runs"] == [
            {"run_id": PRIOR, "interval": {"start": "2026-08-09", "end": "2026-09-07"},
             "task": "review", "skipped_reason": None}
        ]
        assert any(w.startswith("window_mismatch:") for w in rr["warnings"])
        assert doc["data"]["summary"]["comparable"] is False
        sel = json.loads(files["analysis/baseline-selection.json"])
        assert all(not r.get("baseline_observation_id") for r in sel["selected"])
        assert sel["rejected"] and {r["candidate_run_id"] for r in sel["rejected"]} == {PRIOR}
        readme = files["README.md"].decode()
        recur_section = readme.split("## Recur\n", 1)[1]
        assert recur_section.startswith(
            "not comparable (window_mismatch) — windows differ: the prior run covers 30 days, "
            "this run 7"
        )
        assert PRIOR in readme and "baseline — no prior run" not in readme
        assert rr["delta_skipped_reason"] is None
        delta_md = files[rr["delta_path"]].decode()
        assert delta_md.split("\n\n", 2)[1].startswith("> **not comparable (window_mismatch)**")
        assert "## Capture repeatability (not a change)" in delta_md
        assert "### Persisting" not in delta_md and "### Improved" not in delta_md
        assert "![" not in delta_md  # no image embeds on Drive

    def test_comparable_recur_readme_names_the_prior(self, covered_env, drive_run, capsys):
        _registered_prior(drive_run, capsys, window=("2026-08-09", "2026-09-07"))
        _current(drive_run)
        code, out = _recur(drive_run, capsys)
        assert code == 0, out
        files = drive_files(drive_run)
        rr = json.loads(files["analysis/recur-result.json"])
        assert rr["comparable"] is True and rr["baseline"] is False
        assert [p["run_id"] for p in rr["prior_runs"]] == [PRIOR]
        assert f"delta vs `{PRIOR}` (per-observation baselines)" in files["README.md"].decode()

    def test_overlapping_prior_is_not_comparable(self, covered_env, drive_run, capsys):
        """Same-length but overlapping windows: no baseline, so the README and the
        recur result name the real reason, not window_mismatch."""
        _registered_prior(drive_run, capsys, window=("2026-08-20", "2026-09-18"))
        _current(drive_run)
        code, out = _recur(drive_run, capsys)
        assert code == 0, out
        files = drive_files(drive_run)
        rr = json.loads(files["analysis/recur-result.json"])
        assert rr["baseline"] is False and rr["comparable"] is False
        assert rr["not_comparable_reason"] == "interval_overlap"
        assert rr["window"]["prior_run_id"] == PRIOR
        readme = files["README.md"].decode()
        assert readme.split("## Recur\n", 1)[1].startswith("not comparable (interval_overlap):")
        assert "window_mismatch" not in readme
        assert rr["window"]["reason"] == "interval_overlap"

    def test_drive_delta_matches_local(self, covered_env, drive_run, capsys, tmp_path, monkeypatch):
        """Drive recur writes the same ``delta-vs-<prior>.md`` and delta fields as a local
        recur over the same manifests, backlogs and review."""
        from types import SimpleNamespace

        from starboard_skills.helpers import run as run_mod

        prior = _registered_prior(drive_run, capsys, backlog=_BACKLOG_PRIOR)
        _current(drive_run)
        put_files(drive_run, {"analysis/backlog.json": json.dumps(_BACKLOG_CURRENT),
                              "analysis/review.json": json.dumps(_REVIEW)})
        code, out = _recur(drive_run, capsys)
        assert code == 0, out
        files = drive_files(drive_run)
        rr = json.loads(files["analysis/recur-result.json"])
        assert rr["warnings"] == []
        assert rr["delta_path"] == "analysis/delta-vs-2026-09-08.md"
        assert rr["delta_path"] in rr["outputs"]
        drive_md = files["analysis/delta-vs-2026-09-08.md"].decode()
        assert "- Delta: `analysis/delta-vs-2026-09-08.md`" in files["README.md"].decode()

        case = tmp_path / "starboard-reports" / "acme" / "review" / "ws-123"
        for run, backlog, extra in (
            (prior, _BACKLOG_PRIOR, {}),
            (drive_run, _BACKLOG_CURRENT, {"analysis/review.json": json.dumps(_REVIEW)}),
        ):
            rd = case / run.run_id
            (rd / "analysis").mkdir(parents=True)
            (rd / "findings-manifest.json").write_bytes(drive_files(run)["findings-manifest.json"])
            (rd / "analysis" / "backlog.json").write_text(json.dumps(backlog))
            for rel, text in extra.items():
                (rd / rel).write_text(text)
        monkeypatch.setattr(run_mod, "_render_available", lambda: False)
        local = run_mod._recur(case / drive_run.run_id, SimpleNamespace(
            run_dir=str(case / drive_run.run_id), workspace_root=str(case),
            prior=str(case / PRIOR), baseline=False,
        ))
        local_md = (case / drive_run.run_id / "analysis" / "delta-vs-2026-09-08.md").read_text()
        assert "![" not in drive_md  # Drive files carry no relative image embeds
        assert drive_md == re.sub(r"(?m)^!\[[^\n]*\n", "", local_md).replace("\n\n\n", "\n\n")
        for key in ("prior_run_date", "delta_counts", "backlog_delta", "backlog_sizing"):
            assert rr[key] == local[key], key
        for key in ("total_dbu_estimate", "dbu_per_day", "act_now", "backlog_items"):
            assert rr["history_entry"].get(key) == local["entry"].get(key), key
        assert rr["prior_entry"]["run"] == PRIOR

    def test_a_newer_run_without_a_findings_manifest_is_never_the_prior(
        self, covered_env, drive_run, capsys
    ):
        """A1: a newer troubleshooting run (no findings-manifest.json) is listed with
        its skip reason; the older review run is the compared prior and the delta is
        written."""
        _registered_prior(drive_run, capsys)
        _registered_prior(drive_run, capsys, run_id=TROUBLE, task="troubleshooting",
                          with_manifest=False)
        _current(drive_run)
        code, out = _recur(drive_run, capsys)
        assert code == 0, out
        rr = json.loads(drive_files(drive_run)["analysis/recur-result.json"])
        assert rr["comparable"] is True and rr["not_comparable_reason"] is None
        assert rr["window"]["prior_run_id"] == PRIOR
        assert rr["delta_path"] == "analysis/delta-vs-2026-09-08.md"
        assert rr["delta_skipped_reason"] is None
        runs = {p["run_id"]: p for p in rr["prior_runs"]}
        assert runs[PRIOR]["skipped_reason"] is None
        # other_task once the caller passes the run's task; no_findings_manifest without
        assert runs[TROUBLE]["skipped_reason"] in ("other_task", "no_findings_manifest")
        assert runs[TROUBLE]["task"] == "troubleshooting"
        readme = drive_files(drive_run)["README.md"].decode()
        assert f"delta vs `{PRIOR}` (per-observation baselines)" in readme
        assert f"Skipped prior run(s): `{TROUBLE}` (" in readme

    def test_no_eligible_prior_skips_the_delta(self, covered_env, drive_run, capsys):
        """A10: only a run without a findings-manifest exists — no delta, and the
        envelope says why."""
        _registered_prior(drive_run, capsys, run_id=TROUBLE, task="troubleshooting",
                          with_manifest=False)
        _current(drive_run)
        code, out = _recur(drive_run, capsys)
        assert code == 0, out
        doc = json.loads(out)
        rr = json.loads(drive_files(drive_run)["analysis/recur-result.json"])
        assert rr["delta_path"] is None
        assert rr["delta_skipped_reason"] == "no_eligible_prior"
        assert doc["data"]["summary"]["delta_skipped_reason"] == "no_eligible_prior"
        assert rr["comparable"] is False and rr["not_comparable_reason"] == "no_eligible_prior"
        assert doc["data"]["summary"]["not_comparable_reason"] == "no_eligible_prior"
        assert drive_files(drive_run)["README.md"].decode().split("## Recur\n", 1)[1].startswith(
            "not comparable (no_eligible_prior):"
        )

    def test_explicit_prior_without_a_findings_manifest_skips_the_delta(
        self, covered_env, drive_run, capsys
    ):
        """A10: ``--prior`` names a run that committed no findings-manifest.json."""
        trouble = _registered_prior(drive_run, capsys, run_id=TROUBLE, task="troubleshooting",
                                    with_manifest=False)
        _current(drive_run)
        code, out = _recur(drive_run, capsys, "--prior", f"drive:{trouble.folder_id}")
        assert code == 0, out
        rr = json.loads(drive_files(drive_run)["analysis/recur-result.json"])
        assert rr["delta_path"] is None
        assert rr["delta_skipped_reason"] == "prior_no_findings_manifest"
        assert json.loads(out)["data"]["summary"]["delta_skipped_reason"] == (
            "prior_no_findings_manifest"
        )

    def test_a_health_check_recur_says_nothing_about_a_backlog(
        self, covered_env, drive_run, capsys, monkeypatch
    ):
        """A health check builds no backlog: no backlog warning or delta sections."""
        from starboard_skills.helpers import contract

        _registered_prior(drive_run, capsys, task="health_check")
        health = make_drive_run(
            run_id="20261008_12345678-1234-4234-8234-0000000000aa",
            store=drive_run.store, intent="health_check",
        )
        monkeypatch.setattr(contract, "_load_storage", lambda: health.store)
        _current(health)
        put_files(health, {"analysis/review.json": json.dumps(_REVIEW)})
        code, out = _recur(health, capsys)
        assert code == 0, out
        files = drive_files(health)
        rr = json.loads(files["analysis/recur-result.json"])
        assert rr["delta_path"] == "analysis/delta-vs-2026-09-08.md"
        assert [w for w in rr["warnings"] if "backlog" in w.lower()] == []
        assert rr["backlog_delta"] == {  # run-5 D4: empty, not null
            "new": [], "resolved": [], "tier_changed": [], "confidence_changed": [], "unchanged": [],
        }
        assert rr["backlog_sizing"] == []
        delta_md = files["analysis/delta-vs-2026-09-08.md"].decode()
        assert "backlog" not in delta_md.lower()
        assert "## Review findings cost delta\n" in delta_md
        assert "backlog" not in files["README.md"].decode().lower()

    def test_a_health_check_without_a_review_gives_no_since_advice(
        self, covered_env, drive_run, capsys, monkeypatch
    ):
        """A4: a health check (no backlog) never asks for a ``--since`` review re-run."""
        from starboard_skills.helpers import contract

        _registered_prior(drive_run, capsys, task="health_check")
        health = make_drive_run(
            run_id="20261008_12345678-1234-4234-8234-0000000000aa",
            store=drive_run.store, intent="health_check",
        )
        monkeypatch.setattr(contract, "_load_storage", lambda: health.store)
        _current(health)
        code, out = _recur(health, capsys)
        assert code == 0, out
        files = drive_files(health)
        rr = json.loads(files["analysis/recur-result.json"])
        assert [w for w in rr["warnings"] if "--since" in w or "review.json" in w] == []
        delta_md = files[rr["delta_path"]].decode()
        assert "--since" not in delta_md
        assert "No review findings cost delta (`analysis/review.json` carries none)." in delta_md

    def test_not_comparable_recur_gives_no_since_advice(self, covered_env, drive_run, capsys):
        """A4: no ``--since`` re-run advice when the runs are not comparable."""
        _registered_prior(drive_run, capsys, window=("2026-08-09", "2026-09-07"))
        _current(drive_run, ("2026-10-01", "2026-10-07"))
        code, out = _recur(drive_run, capsys)
        assert code == 0, out
        rr = json.loads(drive_files(drive_run)["analysis/recur-result.json"])
        assert rr["comparable"] is False
        assert [w for w in rr["warnings"] if "--since" in w or "review.json" in w] == []
        assert "--since" not in drive_files(drive_run)[rr["delta_path"]].decode()

    def test_rerun_replaces_the_recur_section(self, covered_env, drive_run, capsys):
        _current(drive_run)
        assert _recur(drive_run, capsys)[0] == 0
        assert _recur(drive_run, capsys)[0] == 0
        assert drive_files(drive_run)["README.md"].count(b"## Recur") == 1

    def test_registered_prior_is_compared(self, covered_env, drive_run, capsys):
        prior = _registered_prior(drive_run, capsys)
        _current(drive_run)
        before = covered_env.snapshot()
        code, out = _recur(drive_run, capsys)
        doc = covered_ok(covered_env, before, out)
        assert code == 0, doc
        rr = json.loads(drive_files(drive_run)["analysis/recur-result.json"])
        assert rr["baseline"] is False
        held = json.loads(drive_files(prior)["analysis/observations.json"])
        assert rr["unavailable"] == 0 and rr["candidates"] == len(held)
        assert rr["comparisons"]
        sel = json.loads(drive_files(drive_run)["analysis/baseline-selection.json"])
        assert any(r.get("baseline_observation_id") for r in sel["selected"])
        obs = _finding_obs(drive_files(drive_run))
        cleared = [o for o in obs if "J-FAIL" in json.dumps(o) and o.get("value") == 0.0]
        assert cleared, "a prior finding absent now yields a clear observation"

    def test_first_run_records_active_findings(self, covered_env, drive_run, capsys):
        _current(drive_run)
        code, _ = _recur(drive_run, capsys)
        assert code == 0
        records = _records(drive_run)
        assert set(records) == {"W-IDLE", "Q-SLOW"}
        for rec in records.values():
            assert rec["state"] == "active" and rec["last_confirmed_severity"] == "serious"
            assert rec["run_id"] == drive_run.run_id and rec["observation_ids"]
        rr = json.loads(drive_files(drive_run)["analysis/recur-result.json"])
        assert rr["finding_states"] == {"active": 2}

    def test_cleared_finding_recovers_and_continuing_keeps_episode(
        self, covered_env, drive_run, capsys
    ):
        prior = _registered_prior(drive_run, capsys)
        held = _records(prior)
        _current(drive_run)
        code, _ = _recur(drive_run, capsys)
        assert code == 0
        records = _records(drive_run)
        assert records["J-FAIL"]["state"] == "recovered"
        assert records["W-IDLE"]["state"] == "active"
        assert records["W-IDLE"]["episode_id"] == held["W-IDLE"]["episode_id"]
        assert records["Q-SLOW"]["episode_id"] != held["W-IDLE"]["episode_id"]
        rr = json.loads(drive_files(drive_run)["analysis/recur-result.json"])
        assert rr["finding_states"] == {"active": 2, "recovered": 1}

    def test_lost_current_evidence_is_unknown_current(self, covered_env, drive_run, capsys):
        """A degraded current run that no longer sees a prior finding cannot clear it:
        the record turns unknown_current and keeps the last confirmed severity."""
        prior = _registered_prior(drive_run, capsys)
        put_files(drive_run, {"findings-manifest.json": _manifest(
            "2026-09-08", "2026-10-07", [_finding("Q-SLOW", "q-1", 5.0)], "2026-10-08",
            degraded=True,
        )})
        before = covered_env.snapshot()
        code, out = _recur(drive_run, capsys)
        doc = covered_ok(covered_env, before, out)
        assert code == 0, doc
        records = _records(drive_run)
        held = _records(prior)
        for key in ("J-FAIL", "W-IDLE"):
            assert records[key]["state"] == "unknown_current"
            assert records[key]["last_confirmed_severity"] == "serious"
            assert records[key]["episode_id"] == held[key]["episode_id"]
            assert records[key]["run_id"] == drive_run.run_id
        assert records["Q-SLOW"]["state"] == "active"
        sel = json.loads(drive_files(drive_run)["analysis/baseline-selection.json"])
        assert {r["comparison"] for r in sel["selected"]} >= {"missing_current_evidence"}

    def test_explicit_registered_prior(self, covered_env, drive_run, capsys):
        prior = _registered_prior(drive_run, capsys, backlog=_BACKLOG_PRIOR)
        _current(drive_run)
        put_files(drive_run, {"analysis/backlog.json": json.dumps(_BACKLOG_CURRENT),
                              "analysis/review.json": json.dumps(_REVIEW)})
        code, _ = _recur(drive_run, capsys, "--prior", f"drive:{prior.folder_id}")
        assert code == 0
        rr = json.loads(drive_files(drive_run)["analysis/recur-result.json"])
        assert rr["prior_run_folder"] == prior.folder_id and rr["baseline"] is False
        assert rr["warnings"] == []

    def test_explicit_unregistered_prior_read_directly(self, covered_env, drive_run, capsys):
        prior = _registered_prior(drive_run, capsys, register=False)
        _current(drive_run)
        code, _ = _recur(drive_run, capsys, "--prior", f"drive:{prior.folder_id}")
        assert code == 0
        rr = json.loads(drive_files(drive_run)["analysis/recur-result.json"])
        held = json.loads(drive_files(prior)["analysis/observations.json"])
        assert rr["baseline"] is False and rr["candidates"] == len(held)
        assert any("not in the account registry" in w for w in rr["warnings"])

    def test_baseline_flag_ignores_registry(self, covered_env, drive_run, capsys):
        _registered_prior(drive_run, capsys)
        _current(drive_run)
        code, _ = _recur(drive_run, capsys, "--baseline")
        assert code == 0
        rr = json.loads(drive_files(drive_run)["analysis/recur-result.json"])
        assert rr["baseline"] is True and rr["candidates"] == 0 and rr["unavailable"] == 0

    def test_prior_from_other_account_refused(self, covered_env, drive_run, capsys):
        other = make_drive_run(account_key="other", run_id=PRIOR, store=drive_run.store)
        _current(drive_run)
        code, out = _recur(drive_run, capsys, "--prior", f"drive:{other.folder_id}")
        assert code == 4 and "another account" in out

    def test_bad_prior_is_reported_before_a_missing_manifest(
        self, covered_env, drive_run, capsys
    ):
        code, out = _recur(drive_run, capsys, "--prior", "drive:no-such-folder")
        assert code == 4 and "no-such-folder" in out
        assert "not a readable run folder" in out
        assert "findings-manifest.json" not in out
        assert "analysis/recur-result.json" not in drive_files(drive_run)

    def test_bad_prior_exits_4(self, covered_env, drive_run, capsys):
        _current(drive_run)
        before = drive_files(drive_run)
        code, out = _recur(drive_run, capsys, "--prior", "drive:no-such-folder")
        assert code == 4 and "not a readable run folder" in out
        assert drive_files(drive_run) == before  # a refusal writes nothing, not even ok:false
        assert "analysis/recur-result.json" not in before

    @pytest.mark.parametrize("how", ["other_account", "same_folder", "with_baseline"])
    def test_every_prior_refusal_writes_nothing(self, covered_env, drive_run, capsys, how):
        _current(drive_run)
        other = make_drive_run(
            account_key="other", run_id=PRIOR, store=drive_run.store
        )
        extra = {
            "other_account": ["--prior", f"drive:{other.folder_id}"],
            "same_folder": ["--prior", f"drive:{drive_run.folder_id}"],
            "with_baseline": ["--prior", f"drive:{other.folder_id}", "--baseline"],
        }[how]
        before = covered_env.snapshot()
        files = drive_files(drive_run)
        code, out = _recur(drive_run, capsys, *extra)
        assert code == 4, out
        assert drive_files(drive_run) == files
        assert sandbox_diff(before, covered_env.snapshot()) == []

    def test_unreadable_prior_records_are_refused_before_any_write(
        self, covered_env, drive_run, capsys, monkeypatch
    ):
        """assess refuses an explicit prior whose records cannot be read: still no write."""
        from starboard_skills.helpers.contract import ArgError
        from starboard_skills.helpers.engagement import analysis_cmds

        prior = _registered_prior(drive_run, capsys)
        _current(drive_run)

        def refuse(*_a, **kw):
            raise ArgError(f"--prior drive:{kw['only_folder']}: history_unavailable")

        monkeypatch.setattr(analysis_cmds, "assess", refuse)
        files = drive_files(drive_run)
        code, out = _recur(drive_run, capsys, "--prior", f"drive:{prior.folder_id}")
        assert code == 4 and "history_unavailable" in out
        assert drive_files(drive_run) == files

    def test_registry_conflict_is_a_storage_error(
        self, covered_env, drive_run, capsys, monkeypatch
    ):
        from starboard_core.engagement.folders import FolderConflictError
        from starboard_skills.helpers.engagement import analysis_cmds

        def conflict(*_a, **_k):
            raise FolderConflictError(
                "ambiguous", parent_id="p", name="Acme", identity_key="account:acme",
                object_ids=("obj-1", "obj-2"),
            )

        monkeypatch.setattr(analysis_cmds.OpenRun, "prior", conflict)
        _current(drive_run)
        code, out = _recur(drive_run, capsys)
        assert code == 7, out
        assert "STORAGE_ERROR" in out

    def test_identity_conflict_in_the_registry_is_history_unavailable(
        self, covered_env, drive_run, capsys
    ):
        from starboard_core.engagement.folders import IDENTITY_PROPERTY

        store = drive_run.store
        root = store.root_folder_id()
        for identity in ("segment:starboard", "segment:other"):
            store.add_folder(root, "starboard", properties={IDENTITY_PROPERTY: identity})
        _current(drive_run)
        code, out = _recur(drive_run, capsys)
        assert code == 0, out
        rr = json.loads(drive_files(drive_run)["analysis/recur-result.json"])
        assert rr["unavailable"] >= 1 and rr["baseline"] is True

    def test_missing_manifest_writes_failure_result(self, covered_env, drive_run, capsys):
        before = covered_env.snapshot()
        code, out = _recur(drive_run, capsys)
        assert code == 4 and "findings-manifest.json" in out
        assert sandbox_diff(before, covered_env.snapshot()) == []
        rr = json.loads(drive_files(drive_run)["analysis/recur-result.json"])
        assert rr["ok"] is False and rr["errors"]


@pytest.mark.unit
class TestRecurRefusals:
    def test_stdout_refused_on_covered_run(self, covered_env, drive_run, capsys):
        _current(drive_run)
        code, out = _recur(drive_run, capsys, "--stdout")
        assert code == 2 and "LOCAL_STORAGE_REFUSED" in out
        assert "analysis/recur-result.json" not in drive_files(drive_run)

    def test_workspace_root_with_run_folder(self, tmp_path, covered_env, drive_run, capsys):
        code, out = _recur(drive_run, capsys, "--workspace-root", str(tmp_path))
        assert code == 4 and "--run-folder replaces" in out

    def test_local_prior_with_run_folder(self, tmp_path, covered_env, drive_run, capsys):
        code, out = _recur(drive_run, capsys, "--prior", str(tmp_path))
        assert code == 4 and "drive:<run_folder_id>" in out

    def test_prior_is_current_folder(self, covered_env, drive_run, capsys):
        _current(drive_run)
        code, out = _recur(drive_run, capsys, "--prior", f"drive:{drive_run.folder_id}")
        assert code == 4 and "different run folder" in out

    def test_unwritable_failure_result_warns_and_keeps_the_error(
        self, covered_env, drive_run, capsys, monkeypatch
    ):
        from starboard_core.ports.engagement_storage import StoragePermissionError
        from starboard_skills.helpers import __main__ as cli
        from starboard_skills.helpers.contract import HelperRun

        def refuse(*_a, **_k):
            raise StoragePermissionError("no write access")

        monkeypatch.setattr(HelperRun, "write_record", refuse)
        with pytest.raises(SystemExit) as exc:
            cli.main(["run", "recur", "--run-folder", drive_run.folder_id])
        captured = capsys.readouterr()
        assert exc.value.code == 4 and "findings-manifest.json" in captured.out
        assert "analysis/recur-result.json not written: no write access" in captured.err

    def test_local_requires_workspace_root(self, tmp_path, capsys):
        code, out = run_main(["run", "recur", str(tmp_path)], capsys)
        assert code == 4 and "--workspace-root" in out


def _local_recur_dir(base) -> object:
    """A local run dir (no descriptor) holding a findings manifest, under ``base``."""
    rd = base / "case" / "run-1"
    (rd / "analysis").mkdir(parents=True)
    (rd / "findings-manifest.json").write_text(_manifest(
        "2026-09-08", "2026-10-07", [_finding("W-IDLE", "wh-1", 30.0)], "2026-10-08",
    ))
    return rd


def _internal_local_descriptor(rd) -> None:
    from starboard_core.engagement.policy import SourceMode, StoragePolicy
    from starboard_core.engagement.records import AccountRef, RunAuthorization

    auth = RunAuthorization(
        engagement_id="acme/workspace/ws-123",
        run_id="20261008_12345678-1234-4234-8234-123456789abc",
        intent="discovery",
        task="workspace",
        account=AccountRef(id="acme", display_name="Acme", verifier="operator"),
        requested_scope={"workspace_ids": ["123"]},
        authorized_scope={"account_key": "acme", "workspace_ids": ["123"]},
        reporting_interval="P30D",
        timezone="UTC",
        source_mode=SourceMode.INTERNAL_ONLY,
        storage_policy=StoragePolicy.INTERNAL_ONLY_LOCAL,
        audience="internal",
        methodology_version="m1",
        drive=None,
    )
    (rd / "analysis" / "run-authorization.json").write_text(json.dumps(auth.to_dict()))


@pytest.mark.unit
class TestLocalRecurPolicy:
    """Local ``run recur`` (no ``--run-folder``) decides storage like every writer."""

    def _files(self, rd) -> set[str]:
        return {p.relative_to(rd.parent).as_posix() for p in rd.parent.rglob("*") if p.is_file()}

    def test_overlay_without_descriptor_refused(self, covered_env, capsys):
        from pathlib import Path

        rd = _local_recur_dir(Path.cwd())
        before_files = self._files(rd)
        before = covered_env.snapshot()
        code, out = run_main(
            ["run", "recur", str(rd), "--workspace-root", str(rd.parent), "--baseline"], capsys
        )
        assert code == 2 and "LOCAL_STORAGE_REFUSED" in json.loads(out)["error"]
        assert sandbox_diff(before, covered_env.snapshot()) == []
        assert self._files(rd) == before_files

    def test_overlay_internal_only_local_descriptor_proceeds(self, covered_env, capsys):
        from pathlib import Path

        rd = _local_recur_dir(Path.cwd())
        _internal_local_descriptor(rd)
        code, out = run_main(
            ["run", "recur", str(rd), "--workspace-root", str(rd.parent), "--baseline"], capsys
        )
        assert code == 0, out
        assert (rd / "analysis" / "recur-result.json").is_file()
        assert (rd.parent / "trend" / "history.json").is_file()

    def test_public_local_recur_unchanged(self, tmp_path, capsys):
        rd = _local_recur_dir(tmp_path)
        code, out = run_main(
            ["run", "recur", str(rd), "--workspace-root", str(rd.parent), "--baseline"], capsys
        )
        assert code == 0, out
        assert json.loads(out)["ok"] is True
        assert (rd / "analysis" / "recur-result.json").is_file()
        assert (rd / "README.md").is_file()
