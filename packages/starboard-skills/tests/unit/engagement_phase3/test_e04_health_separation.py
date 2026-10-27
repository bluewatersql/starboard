"""E4: unavailable governance is unknown, never averaged into the J-42 read (D3-6..D3-10)."""

from __future__ import annotations

from . import _j42
from ._support import Ctx, baseline_run, current_run, family, records


def test_health_separation(mode, capsys, store, sandbox, seams, tmp_path) -> None:
    ctx = Ctx(capsys, store, sandbox, seams, tmp_path, mode)
    baseline_run(ctx)
    recs = records(ctx, current_run(ctx))
    fid = _j42.finding_id_j42()

    gov = family(recs, "governance")
    assert gov["assessment"] == "unknown"
    assert gov["unknown_reason"].startswith("not_reviewed:")  # review ran no uc domain
    assert gov["acquisition_request"]["command"]

    assert recs.health["verdict"] == "health_read"
    assert recs.health["top_concern_finding_ids"][0] == fid

    acting = [p for p in recs.plays if p["play_code"] != "acquire_family_evidence"]
    assert len(acting) == 1, [p["play_code"] for p in recs.plays]
    play = acting[0]
    assert play["play_code"] == "job_reliability_session"
    assert play["owner_role"] == "job_owner"
    assert play["finding_ids"] == [fid]
    assert play["next_commands"]
    verify_cmds = [c for c in play["next_commands"] if " verify run " in f" {c} "]
    assert verify_cmds
    for cmd in verify_cmds:
        assert "--limit" in cmd.split()
        assert "--start" in cmd.split() and "--end" in cmd.split()
    # A health run never fetches one entity (B1-9); an internal-only run lists the
    # mirror verify form, a customer-workspace run the public one.
    assert not any(" fetch " in c or " runs " in c or "run-output" in c
                   for p in recs.plays for c in p["next_commands"])
    if mode == "internal_local":
        assert all("--internal-workspace-id" in c.split() and "--ws" not in c.split()
                   for c in verify_cmds)
    else:
        assert all("--ws" in c.split() and "--templates" not in c.split()
                   for c in verify_cmds)
    assert play["follow_up_check"]["template"] == "vt-job-runs"
    assert "1.0% → 8.0% (+7.0 pp)" in play["reason"]

    # The governance gap surfaces as an acquisition play, not a concern.
    acquire = [p for p in recs.plays if p["play_code"] == "acquire_family_evidence"]
    assert any(
        p["next_commands"] == [gov["acquisition_request"]["command"]] for p in acquire
    )

    actions = [a for a in recs.actions if a["finding_id"] == fid]
    assert len(actions) == 1
    assert actions[0]["play_id"] == play["play_id"]
    assert actions[0]["proposal_state"] == "proposed"
    assert actions[0]["acceptance_state"] == "pending"
    assert actions[0]["execution_state"] == "not_started"
