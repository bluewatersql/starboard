"""``engagement analyze``: the run's record sets, the run flags, prior history.

``run recur --run-folder`` runs the same assessment, so both must write the same
findings; the legacy recur helpers it replaced are gone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starboard_core.engagement.write_guard import sandbox_diff
from starboard_skills.helpers.engagement import analysis_cmds as ac

from .conftest import covered_ok, drive_files, make_drive_run, put_files, run_main
from .test_internal_only_local_bound import _internal_run
from .test_run_recur_drive import _current, _finding, _manifest, _registered_prior

_SETS = (
    "analysis/observations.json",
    "analysis/findings.json",
    "analysis/health.json",
    "analysis/plays.json",
    "analysis/changes.json",
    "analysis/cases.json",
    "analysis/actions.json",
    "analysis/baseline-selection.json",
)


def _analyze(run, capsys, *extra: str) -> tuple[int, str]:
    return run_main(
        ["engagement", "analyze", "--run-folder", run.folder_id, *extra], capsys
    )


def _findings(run) -> list[dict]:
    return json.loads(drive_files(run)["analysis/findings.json"])


@pytest.mark.unit
class TestAnalyze:
    def test_writes_every_record_set_and_nothing_local(
        self, covered_env, drive_run, capsys
    ):
        _current(drive_run)
        before = covered_env.snapshot()
        code, out = _analyze(drive_run, capsys)
        assert code == 0, out
        data = covered_ok(covered_env, before, out)["data"]
        assert sandbox_diff(before, covered_env.snapshot()) == []
        assert set(_SETS) <= set(drive_files(drive_run))
        assert data["outputs"] == list(_SETS)
        assert data["baseline"] is True and data["workspace_id"] == "123"
        assert data["interval"] == {"start": "2026-09-08", "end": "2026-10-07"}

    def test_findings_are_v1_records_keyed_ck1(self, covered_env, drive_run, capsys):
        _current(drive_run)
        assert _analyze(drive_run, capsys)[0] == 0
        found = {f["rule_id"]: f for f in _findings(drive_run)}
        assert set(found) == {"W-IDLE", "Q-SLOW"}
        for f in found.values():
            assert f["finding_key"].startswith("ck1|acme|123|")
            assert f["state"] == "active" and f["severity"] == "serious"
            assert (
                f["revision"] == 1 and f["episode_started_run_id"] == drive_run.run_id
            )

    def test_interval_flags_override_the_manifest_window(
        self, covered_env, drive_run, capsys
    ):
        _current(drive_run)
        code, out = _analyze(
            drive_run,
            capsys,
            "--interval-start",
            "2026-09-01",
            "--interval-end",
            "2026-09-30",
        )
        assert code == 0, out
        assert json.loads(out)["data"]["interval"] == {
            "start": "2026-09-01",
            "end": "2026-09-30",
        }

    def test_backlog_facts_window_is_the_fallback(self, covered_env, drive_run, capsys):
        doc = json.loads(
            _manifest("x", "y", [_finding("W-IDLE", "wh-1", 1.0)], "2026-10-08")
        )
        del doc["facts_window"]
        put_files(
            drive_run,
            {
                "findings-manifest.json": json.dumps(doc),
                "analysis/backlog.json": json.dumps(
                    {"facts_window": {"start": "2026-08-01", "end": "2026-08-31"}}
                ),
            },
        )
        code, out = _analyze(drive_run, capsys)
        assert code == 0, out
        assert json.loads(out)["data"]["interval"] == {
            "start": "2026-08-01",
            "end": "2026-08-31",
        }

    def test_recur_writes_the_same_findings_as_analyze(
        self, covered_env, drive_run, capsys
    ):
        _current(drive_run)
        assert _analyze(drive_run, capsys)[0] == 0
        analyzed = _findings(drive_run)
        code, out = run_main(
            ["run", "recur", "--run-folder", drive_run.folder_id], capsys
        )
        assert code == 0, out
        assert _findings(drive_run) == analyzed

    def test_no_inputs_is_insufficient_evidence_exit_0(
        self, covered_env, drive_run, capsys
    ):
        code, out = _analyze(drive_run, capsys)
        assert code == 0, out
        data = json.loads(out)["data"]
        assert data["verdict"] == "insufficient_evidence"
        assert data["counts"]["findings"] == 0


def _raw(*statuses: str) -> dict[str, str]:
    """A ``discovery/raw/jobs.json`` capture with one result per status."""
    results = [
        {"query_id": f"C-J0{i}", "status": s, "succeeded": s == "succeeded", "rows": []}
        for i, s in enumerate(statuses, 1)
    ]
    return {
        "discovery/raw/jobs.json": json.dumps(
            {"pack": "jobs", "domain": "jobs", "results": results}
        )
    }


def _reviewed(run) -> None:
    """A manifest whose review covered jobs/sql/warehouse: families assess."""
    doc = json.loads(
        _manifest(
            "2026-09-08",
            "2026-10-07",
            [_finding("warehouse_auto_stop_disabled", "wh-1", 30.0)],
            "2026-10-08",
        )
    )
    doc["reviewed_domains"] = ["jobs", "sql", "warehouse"]
    put_files(run, {"findings-manifest.json": json.dumps(doc)})


@pytest.mark.unit
class TestNoEvidenceCapture:
    def test_zero_successful_queries_is_insufficient_evidence(
        self, covered_env, drive_run, capsys
    ):
        _reviewed(drive_run)
        put_files(drive_run, _raw("failed", "failed", "skipped"))
        code, out = _analyze(drive_run, capsys)
        assert code == 0, out
        doc = json.loads(out)
        data = doc["data"]
        assert data["verdict"] == "insufficient_evidence"
        assert all(f["assessment"] == "unknown" for f in data["families"])
        assert any("0 of 3 queries" in w for w in doc["warnings"])
        health = json.loads(drive_files(drive_run)["analysis/health.json"])
        assert health["assessed_count"] == 0
        for f in health["families"]:
            assert (
                f["unknown_reason"] == "no_evidence:discovery_0_of_3_queries_succeeded"
            )
            assert f["acquisition_request"]["missing"] == ["C-J01", "C-J02", "C-J03"]

    def test_one_successful_query_is_not_gated(self, covered_env, drive_run, capsys):
        _reviewed(drive_run)
        assert _analyze(drive_run, capsys)[0] == 0
        ungated = json.loads(drive_files(drive_run)["analysis/health.json"])
        assert ungated["verdict"] != "insufficient_evidence"
        put_files(drive_run, _raw("failed", "succeeded"))
        code, out = _analyze(drive_run, capsys)
        assert code == 0, out
        assert json.loads(drive_files(drive_run)["analysis/health.json"]) == ungated
        assert not any("queries successfully" in w for w in json.loads(out)["warnings"])


@pytest.mark.unit
class TestRunFlags:
    def test_neither_run_flag_exits_2(self, covered_env, capsys):
        code, out = run_main(["engagement", "analyze"], capsys)
        assert code == 2, out

    def test_both_run_flags_exit_2(self, tmp_path, covered_env, drive_run, capsys):
        code, out = run_main(
            [
                "engagement",
                "analyze",
                "--run-folder",
                drive_run.folder_id,
                "--run-dir",
                str(tmp_path),
            ],
            capsys,
        )
        assert code == 2, out

    def test_run_dir_without_workspace_root_exits_2(
        self, tmp_path, covered_env, capsys
    ):
        code, out = run_main(
            ["engagement", "analyze", "--run-dir", str(tmp_path)], capsys
        )
        assert code == 2 and "--workspace-root" in out, out

    def test_run_dir_on_a_drive_required_run_exits_2(
        self, tmp_path, covered_env, capsys
    ):
        from starboard_core.engagement.commit import read_descriptor

        drive = make_drive_run()
        auth = read_descriptor(drive.store, drive.folder_id)[0]
        rd = tmp_path / "case" / "run-1"
        (rd / "analysis").mkdir(parents=True)
        (rd / "analysis" / "run-authorization.json").write_text(
            json.dumps(auth.to_dict())
        )
        code, out = run_main(
            [
                "engagement",
                "analyze",
                "--run-dir",
                str(rd),
                "--workspace-root",
                str(rd.parent),
            ],
            capsys,
        )
        assert code == 2, out
        (error,) = json.loads(out)["errors"]
        assert error["code"] == "LOCAL_STORAGE_REFUSED", out
        assert sorted(p.name for p in (rd / "analysis").iterdir()) == [
            "run-authorization.json"
        ]

    def test_workspace_root_other_than_the_case_root_exits_2(self, covered_env, capsys):
        rd = _internal_run(Path.cwd())
        elsewhere = Path.cwd() / "elsewhere"
        elsewhere.mkdir()
        code, out = run_main(
            [
                "engagement",
                "analyze",
                "--run-dir",
                str(rd),
                "--workspace-root",
                str(elsewhere),
            ],
            capsys,
        )
        assert code == 2, out
        (error,) = json.loads(out)["errors"]
        assert error["code"] == "OUTSIDE_RUN_DIR", out
        assert sorted(p.name for p in (rd / "analysis").iterdir()) == [
            "run-authorization.json"
        ]


@pytest.mark.unit
class TestPriorHistory:
    def test_unreadable_explicit_prior_is_an_arg_error(
        self, covered_env, drive_run, capsys
    ):
        _current(drive_run)
        code, out = run_main(
            [
                "run",
                "recur",
                "--run-folder",
                drive_run.folder_id,
                "--prior",
                "drive:no-such",
            ],
            capsys,
        )
        assert code == 4 and "--prior drive:no-such" in out, out

    def test_corrupt_registry_is_history_unavailable(
        self, covered_env, drive_run, capsys
    ):
        from starboard_core.engagement.registry import ensure_registry

        _registered_prior(drive_run, capsys)
        (handle,) = ensure_registry(drive_run.store, "acme")
        corrupted = 0
        for folder in (handle.registrations_folder_id, handle.index_folder_id):
            for obj in drive_run.store.list_children(folder):
                if not obj.is_folder:
                    drive_run.store.corrupt_object(obj.id)
                    corrupted += 1
        assert corrupted >= 1
        _current(drive_run)
        code, out = _analyze(drive_run, capsys)
        assert code == 0, out
        data = json.loads(out)["data"]
        assert data["baseline"] is True
        assert data["counts"]["prior_unavailable"] >= 1
        assert data["counts"]["prior_candidates"] == 0  # the registered prior is unread
        assert "history_unavailable" in " ".join(data["warnings"])


@pytest.mark.unit
def test_legacy_recur_helpers_are_gone() -> None:
    from starboard_skills.helpers import run
    from starboard_skills.helpers.engagement import lifecycle

    legacy = (
        "_candidates_from",
        "_committed_findings",
        "_severities",
        "_finding_records",
        "_prior_records",
        "_evidence_ids",
        "_recur_workspace",
        "_recur_interval",
    )
    assert [n for n in legacy if hasattr(run, n)] == []
    assert not hasattr(lifecycle, "_prior_observations")


@pytest.mark.unit
def test_other_account_run_is_not_read_as_prior(covered_env, drive_run, capsys):
    other = make_drive_run(
        account_key="globex",
        run_id="20260908_12345678-1234-4234-8234-0000000000aa",
        store=drive_run.store,
    )
    put_files(
        other,
        {
            "findings-manifest.json": _manifest(
                "2026-08-08",
                "2026-09-07",
                [_finding("W-IDLE", "wh-1", 40.0)],
                "2026-09-08",
            )
        },
    )
    _current(drive_run)
    code, out = _analyze(drive_run, capsys)
    assert code == 0, out
    assert json.loads(out)["data"]["counts"]["prior_candidates"] == 0


def _play(pid: str, host_rank: int | None = None):
    from types import SimpleNamespace

    return SimpleNamespace(play_id=pid, host_rank=host_rank)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("plays", "expected"),
    [
        ([_play("a"), _play("b"), _play("c")], ["a", "b", "c"]),
        # Host-ranked plays first by host_rank, then the rest in computed order.
        ([_play("a"), _play("b"), _play("c", 1)], ["c", "a", "b"]),
        ([_play("a", 2), _play("b"), _play("c", 1)], ["c", "a", "b"]),
        # A host-rank tie keeps the computed order: still a total order.
        ([_play("a"), _play("b", 1), _play("c", 1)], ["b", "c", "a"]),
    ],
)
def test_effective_order_is_host_rank_then_computed(plays, expected) -> None:
    from starboard_skills.helpers.engagement.analysis_cmds import effective_order

    ranked = effective_order(plays)
    assert [r for r, _ in ranked] == list(range(1, len(plays) + 1))
    assert [p.play_id for _, p in ranked] == expected


@pytest.mark.unit
def test_analyze_digest_lists_plays_in_effective_order(covered_env, drive_run, capsys):
    from starboard_core.engagement.stdout_budget import DEFAULT_MAX_BYTES

    _current(drive_run)
    code, out = _analyze(drive_run, capsys)
    assert code == 0, out
    plays = json.loads(drive_files(drive_run)["analysis/plays.json"])
    assert len(plays) >= 2
    last = plays[-1]["play_id"]
    code, out = run_main(
        [
            "engagement", "play", "rank", "--run-folder", drive_run.folder_id,
            "--play-id", last, "--rank", "1", "--reason", "owner asked first",
        ],
        capsys,
    )
    assert code == 0, out
    code, out = _analyze(drive_run, capsys)
    assert code == 0, out
    assert len(out.encode("utf-8")) <= DEFAULT_MAX_BYTES
    env = json.loads(out)
    assert not env.get("truncated"), env.get("omitted")
    data = env["data"]
    top = data["top_plays"]
    assert top[0]["play_id"] == last and top[0]["host_rank"] == 1
    # One entry per entity target (workspace-grain plays one each), in effective order.
    ordered = [by for by in plays if by["play_id"] == last] + [
        by for by in plays if by["play_id"] != last
    ]
    leads: dict[str, list[str]] = {}
    for p in ordered:
        target = f"{p['target_entity_kind']}:{p['target_entity_id']}"
        key = p["play_id"] if p["target_entity_kind"] == "workspace" else target
        leads.setdefault(key, []).append(p["play_id"])
    expected = list(leads.values())[: len(top)]
    assert [p["play_id"] for p in top] == [ids[0] for ids in expected]
    assert [[s["play_id"] for s in p["same_target_plays"]] for p in top] == [
        ids[1:] for ids in expected
    ]
    rank = {p["play_id"]: i for i, p in enumerate(ordered, 1)}
    assert [p["effective_rank"] for p in top] == [rank[p["play_id"]] for p in top]
    by_id = {p["play_id"]: p for p in plays}
    actions = json.loads(drive_files(drive_run)["analysis/actions.json"])
    action_of = {a["play_id"]: a["action_id"] for a in actions if a.get("play_id")}
    for digest in top:
        assert digest["action_id"] == action_of.get(digest["play_id"])
        assert digest["placeholders"] == by_id[digest["play_id"]]["placeholders"]
        for command in digest["next_commands"]:
            # Runnable as printed: the run's folder; only the warehouse placeholder.
            if command.startswith(("starboard-helper verify run", "starboard review")):
                assert f"--run-folder {drive_run.folder_id}" in command
            assert "<" not in command.replace("<warehouse_id>", "")
        record = by_id[digest["play_id"]]
        assert digest["exposure"] == record["exposure"]
        assert digest["next_commands"] == record["next_commands"]
        assert digest["play_code"] == record["play_code"]
        assert digest["target"] == (
            f"{record['target_entity_kind']}:{record['target_entity_id']}"
        )
    by_code = data["plays_by_code"]
    assert sum(v["count"] for v in by_code.values()) == data["counts"]["plays"]
    for code, v in by_code.items():
        assert v["play_ids"] == [
            p["play_id"] for p in ordered if p["play_code"] == code
        ][:25]
    families = {f["family"]: f["coverage"] for f in data["families"]}
    assert {
        fam: cov for cov, fams in data["coverage"].items() for fam in fams
    } == families
    assert sum(data["observations_by_family"].values()) == data["counts"]["observations"]
    manifest = json.loads(drive_files(drive_run)["findings-manifest.json"])
    assert data["findings_by_rule"] == ac.findings_by_rule(manifest)
    assert sum(v["findings"] for v in data["findings_by_rule"].values()) == sum(
        1 for f in manifest["findings"] if f.get("rule_id")
    )


@pytest.mark.unit
def test_play_rank_effective_rank_agrees_with_analyze_top_plays(
    covered_env, drive_run, capsys
):
    _current(drive_run)
    code, out = _analyze(drive_run, capsys)
    assert code == 0, out
    plays = json.loads(drive_files(drive_run)["analysis/plays.json"])
    assert len(plays) >= 2
    first, last = plays[0]["play_id"], plays[-1]["play_id"]
    seen: dict[str, int] = {}
    # Host rank 5 on the first play and 1 on the last: a host rank is a sort key,
    # not a position, so the first play's effective rank is 2.
    for play_id, host_rank in ((first, 5), (last, 1)):
        code, out = run_main(
            [
                "engagement", "play", "rank", "--run-folder", drive_run.folder_id,
                "--play-id", play_id, "--rank", str(host_rank), "--reason", "owner",
            ],
            capsys,
        )
        assert code == 0, out
        data = json.loads(out)["data"]
        assert data["host_rank"] == host_rank
        seen[play_id] = data["effective_rank"]
    assert seen[last] == 1
    code, out = _analyze(drive_run, capsys)
    assert code == 0, out
    top = {p["play_id"]: p for p in json.loads(out)["data"]["top_plays"]}
    assert top[last]["effective_rank"] == 1
    assert top[first]["effective_rank"] == 2
    # play rank reported the first play's rank before the last was ranked: re-rank
    # it and the two outputs agree.
    code, out = run_main(
        [
            "engagement", "play", "rank", "--run-folder", drive_run.folder_id,
            "--play-id", first, "--rank", "5", "--reason", "owner",
        ],
        capsys,
    )
    assert json.loads(out)["data"]["effective_rank"] == top[first]["effective_rank"]
