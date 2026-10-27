"""Run-5 Group B fixes to ``engagement analyze`` / ``play rank`` records (B4, B5, B8, B10).

* B4: ``analysis/plays.json`` carries the digest's ``target`` (``kind:id``),
  ``effective_rank`` and ``action_id`` per play, kept current by ``play rank``.
* B5: ``prior_runs`` lists a prior run that left records but no observations
  (e.g. a troubleshooting run's case), with ``skipped_reason`` like recur.
* B8: ``plays_by_code[<code>].samples`` carry each sample play's reason,
  target and exposure, so a host can rank without slicing ``plays.json``.
* B10: a baseline analysis is ``comparable: false`` with reason ``baseline``,
  the same contract as ``run recur``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from starboard_skills.helpers.engagement import analysis_cmds as ac

from .conftest import commit_manifest, drive_files, make_drive_run, put_files, run_main
from .test_engagement_run4_b import _play
from .test_run_recur_drive import PRIOR, _current

_QUESTION = "Why does job 42 fail every night?"


def _eng(run, capsys, *argv: str) -> dict[str, Any]:
    code, out = run_main(["engagement", *argv, "--run-folder", run.folder_id], capsys)
    assert code == 0, out
    return json.loads(out)["data"]


def _plays(run) -> list[dict[str, Any]]:
    return json.loads(drive_files(run)["analysis/plays.json"])


@pytest.mark.unit
class TestPlaysJsonDigestFields:
    def test_analyze_persists_target_rank_and_action(
        self, covered_env, drive_run, capsys
    ):
        _current(drive_run)
        data = _eng(drive_run, capsys, "analyze")
        plays = _plays(drive_run)
        assert len(plays) >= 2
        actions = json.loads(drive_files(drive_run)["analysis/actions.json"])
        action_of = {a["play_id"]: a["action_id"] for a in actions if a.get("play_id")}
        for rank, p in enumerate(plays, 1):
            assert p["target"] == f"{p['target_entity_kind']}:{p['target_entity_id']}"
            assert p["effective_rank"] == rank
            assert p["action_id"] == action_of.get(p["play_id"])
        by_id = {p["play_id"]: p for p in plays}
        for digest in data["top_plays"]:
            record = by_id[digest["play_id"]]
            assert record["effective_rank"] == digest["effective_rank"]
            assert record["action_id"] == digest["action_id"]
            assert record["target"] == digest["target"]

    def test_play_rank_rewrites_every_effective_rank(
        self, covered_env, drive_run, capsys
    ):
        _current(drive_run)
        _eng(drive_run, capsys, "analyze")
        first, last = _plays(drive_run)[0]["play_id"], _plays(drive_run)[-1]["play_id"]
        _eng(
            drive_run,
            capsys,
            "play",
            "rank",
            "--play-id",
            last,
            "--rank",
            "1",
            "--reason",
            "owner asked first",
        )
        by_id = {p["play_id"]: p for p in _plays(drive_run)}
        assert by_id[last]["effective_rank"] == 1 and by_id[last]["host_rank"] == 1
        assert by_id[first]["effective_rank"] == 2
        assert sorted(p["effective_rank"] for p in by_id.values()) == list(
            range(1, len(by_id) + 1)
        )


def _cases_only_prior(drive_run, capsys) -> None:
    """A registered troubleshooting run whose commit holds a case, no observations."""
    from starboard_core.engagement.policy import SourceMode, StoragePolicy
    from starboard_core.engagement.records import Registration, registration_id
    from starboard_core.engagement.registry import ensure_registry
    from starboard_core.engagement.registry import register as reg_put

    prior = make_drive_run(
        run_id=PRIOR, store=drive_run.store, intent="troubleshooting"
    )
    _current(prior)
    _eng(prior, capsys, "analyze")
    _eng(prior, capsys, "case", "open", "--clue", "job:42", "--question", _QUESTION)
    files = drive_files(prior)
    refs = put_files(prior, {"analysis/cases.json": files["analysis/cases.json"]})
    commit_manifest(
        prior,
        refs=tuple(refs.values()),
        observation_refs=(),
        cases_ref=refs["analysis/cases.json"],
        task="troubleshooting",
    )
    (handle,) = ensure_registry(drive_run.store, "acme", account_name="Acme")
    reg_put(
        drive_run.store,
        handle,
        Registration(
            registration_id=registration_id(PRIOR),
            kind="run",
            run_id=PRIOR,
            engagement_id="acme/troubleshooting/ws-123",
            account_key="acme",
            task="troubleshooting",
            task_name="ws-123",
            route="account",
            source_mode=SourceMode.CUSTOMER_WORKSPACE,
            storage_policy=StoragePolicy.DRIVE_REQUIRED,
            run_folder_id=prior.folder_id,
            descriptor_ref=None,
            observation_summary_ref=None,
            acl_classification="restricted",
            principal_id="perm-1",
            registered_at="2026-09-08T10:00:00+00:00",
            provenance={"origin": "drive_run"},
        ),
    )


@pytest.mark.unit
def test_prior_runs_lists_a_records_only_other_task_run(covered_env, drive_run, capsys):
    _cases_only_prior(drive_run, capsys)
    _current(drive_run)
    data = _eng(drive_run, capsys, "analyze")
    assert data["counts"]["prior_candidates"] == 0
    assert data["prior_runs"] == [
        {
            "run_id": PRIOR,
            "interval": None,
            "task": "troubleshooting",
            "skipped_reason": "other_task",
        }
    ]
    # A run that is never compared does not make this run a recurrence.
    assert data["baseline"] is True


@pytest.mark.unit
def test_baseline_analysis_is_not_comparable(covered_env, drive_run, capsys):
    _current(drive_run)
    data = _eng(drive_run, capsys, "analyze")
    assert data["baseline"] is True
    assert data["comparable"] is False
    assert data["not_comparable_reason"] == "baseline"
    assert data["window"]["comparable"] is False
    assert data["window"]["reason"] == "baseline"


@pytest.mark.unit
def test_plays_by_code_samples_carry_reason_target_exposure() -> None:
    plays = [_play(f"p{i}", "c", "job", str(i), reason=f"why {i}") for i in range(5)]
    out = ac.plays_by_code(plays)
    entry = out["c"]
    assert entry["count"] == 5 and entry["play_ids"] == [f"p{i}" for i in range(5)]
    assert entry["samples"] == [
        {
            "play_id": f"p{i}",
            "effective_rank": i + 1,
            "target": f"job:{i}",
            "reason": f"why {i}",
            "exposure": dict(plays[i].exposure),
        }
        for i in range(ac._PLAYS_BY_CODE_SAMPLES)
    ]
