"""E10 Public-local boundaries (``public_local`` plus covered; spec §H.10, D4-5, B7).

* A covered run dir stays ``LOCAL_STORAGE_REFUSED`` (including a Drive
  descriptor copied into a local dir) and writes nothing.
* A public run dir without a descriptor: ``analyze`` is exit 4 with the
  preflight hint; ``run recur`` stays trend-only with the ``kernel records
  skipped`` warning.
* ``--workspace-root`` other than the case root on ``analyze`` is
  ``OUTSIDE_RUN_DIR``.
* ``run recur`` with the trend root elsewhere writes the trend there, reads the
  prior from the case root and warns.
* A run dir not named by its run id warns.
* A public ``--out`` elsewhere is unchanged.

D4-15 (the internal-only scope, declared at preflight):

* ``engagement preflight --internal-workspace-id`` with any source mode other
  than ``internal_only`` is usage exit 2 and opens no run.
* ``route`` copies it into the descriptor: ``authorized_scope.workspace_ids ==
  [WS]`` with ``basis == "declared"``; a customer leg's basis is ``verified``.
* A Drive ``internal_only`` verify slice on another ``--internal-workspace-id``
  is refused as outside the scope (which names ``WS``); the declared one passes.
* Without the flag the scope stays empty and ``case open --clue`` fails with an
  error that names ``--internal-workspace-id``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from . import _fixtures
from ._support import (
    FACTS,
    MANIFEST,
    QUESTION,
    WS,
    Ctx,
    Run,
    all_warnings,
    eng,
    error_code,
    error_text,
    finding,
    helper,
    local_files,
    new_run,
    preflight_argv,
    records,
    run_recur,
    verify_slice,
    write_inputs,
)

PUBLIC = pytest.mark.parametrize("mode", ["public_local"])
DRIVE = pytest.mark.parametrize("mode", ["drive_backed"])

DESCRIPTOR = "analysis/run-authorization.json"
RECORDS = (
    "analysis/observations.json",
    "analysis/findings.json",
    "analysis/health.json",
    "analysis/plays.json",
    "analysis/changes.json",
    "analysis/cases.json",
    "analysis/actions.json",
    "analysis/baseline-selection.json",
)
PREFLIGHT_HINT = "run engagement preflight --storage local and route first"
SKIPPED = "no run authorization: kernel records skipped"
NOT_RUN_ID = "run dir name is not its run id; later runs will not find these records"


def _analyze_argv(run_dir: Path, workspace_root: Path) -> list[str]:
    return [
        "analyze",
        "--run-dir",
        str(run_dir),
        "--workspace-root",
        str(workspace_root),
        "--manifest",
        MANIFEST,
        "--facts",
        FACTS,
        "--interval-start",
        _fixtures.CURRENT[0],
        "--interval-end",
        _fixtures.CURRENT[1],
    ]


def _bare_run_dir(base: Path, name: str = "run-1") -> Path:
    """A hand-made public run dir (no run authorization) with review inputs."""
    rd = base / "case" / name
    (rd / "discovery").mkdir(parents=True)
    (rd / MANIFEST).write_text(json.dumps(_fixtures.review_manifest()))
    (rd / FACTS).write_text(json.dumps(_fixtures.current_facts()))
    return rd


def _captured(ctx: Ctx, *, facts: dict[str, Any]) -> Run:
    """A routed health_check run with the S1 + S2 slices (as E2's first run)."""
    run = new_run(ctx, task="health_check")
    write_inputs(ctx, run, facts=facts, review=_fixtures.review_manifest())
    verify_slice(ctx, run, _fixtures.S1, _fixtures.s1_rows(), suffix="s1")
    verify_slice(ctx, run, _fixtures.S2, _fixtures.s2_rows(), suffix="s2")
    return run


# --------------------------------------------------------------------------- #
# Covered runs stay refused
# --------------------------------------------------------------------------- #
@DRIVE
def test_a_drive_descriptor_copied_locally_is_refused(ctx: Ctx) -> None:
    from starboard_core.engagement.commit import read_descriptor

    run = new_run(ctx, task="health_check")
    assert run.rf
    auth = read_descriptor(ctx.store, run.rf)[0]
    rd = ctx.tmp_path / "copy" / "case" / auth.run_id
    (rd / "analysis").mkdir(parents=True)
    (rd / DESCRIPTOR).write_text(json.dumps(auth.to_dict()))
    (rd / MANIFEST).write_text(json.dumps(_fixtures.review_manifest()))

    code, env, raw = eng(ctx.capsys, *_analyze_argv(rd, rd.parent))
    assert code == 2, raw
    assert error_code(env) == "LOCAL_STORAGE_REFUSED"
    code, env, raw = helper(
        ctx.capsys,
        "run",
        "recur",
        str(rd),
        "--workspace-root",
        str(rd.parent),
        "--baseline",
    )
    assert code != 0, raw
    assert "LOCAL_STORAGE_REFUSED" in raw
    assert sorted(p.name for p in (rd / "analysis").iterdir()) == [
        "run-authorization.json"
    ]
    assert not (rd.parent / "trend").exists()


@DRIVE
def test_a_public_local_descriptor_on_a_covered_install_is_refused(ctx: Ctx) -> None:
    """The overlay is on: a customer-workspace LOCAL descriptor cannot write locally."""
    from starboard_core.engagement.policy import SourceMode, StoragePolicy
    from starboard_core.engagement.records import AccountRef, RunAuthorization

    run_id = "20261001_12345678-1234-4234-8234-123456789abc"
    auth = RunAuthorization(
        engagement_id=f"{_fixtures.ACCOUNT}/health_check/ws-123",
        run_id=run_id,
        intent="health_check",
        task="health_check",
        account=AccountRef(
            id=_fixtures.ACCOUNT, display_name="Acme", verifier="operator"
        ),
        requested_scope={"workspace_ids": [_fixtures.WS]},
        authorized_scope={
            "account_key": _fixtures.ACCOUNT,
            "workspace_ids": [_fixtures.WS],
        },
        reporting_interval="P30D",
        timezone="UTC",
        source_mode=SourceMode.CUSTOMER_WORKSPACE,
        storage_policy=StoragePolicy.LOCAL,
        audience="customer",
        methodology_version="m1",
        drive=None,
    )
    rd = ctx.tmp_path / "covered" / "case" / run_id
    (rd / "analysis").mkdir(parents=True)
    (rd / DESCRIPTOR).write_text(json.dumps(auth.to_dict()))
    (rd / MANIFEST).write_text(json.dumps(_fixtures.review_manifest()))
    code, env, raw = eng(ctx.capsys, *_analyze_argv(rd, rd.parent))
    assert code == 2, raw
    assert error_code(env) == "LOCAL_STORAGE_REFUSED"
    assert sorted(p.name for p in (rd / "analysis").iterdir()) == [
        "run-authorization.json"
    ]


# --------------------------------------------------------------------------- #
# A public run dir without a descriptor
# --------------------------------------------------------------------------- #
@PUBLIC
def test_analyze_without_a_descriptor_names_the_preflight_step(ctx: Ctx) -> None:
    rd = _bare_run_dir(ctx.tmp_path)
    before = sorted(local_files(rd))
    code, _env, raw = eng(ctx.capsys, *_analyze_argv(rd, rd.parent))
    assert code == 4, raw
    assert PREFLIGHT_HINT in raw
    assert sorted(local_files(rd)) == before


@PUBLIC
def test_recur_without_a_descriptor_stays_trend_only_and_warns(ctx: Ctx) -> None:
    rd = _bare_run_dir(ctx.tmp_path)
    code, env, raw = helper(
        ctx.capsys,
        "run",
        "recur",
        str(rd),
        "--workspace-root",
        str(rd.parent),
        "--baseline",
    )
    assert code == 0, raw
    assert (rd.parent / "trend" / "history.json").is_file()
    for rel in RECORDS:
        assert not (rd / rel).exists(), rel
    assert SKIPPED in all_warnings(env.get("data") or {})


# --------------------------------------------------------------------------- #
# Roots
# --------------------------------------------------------------------------- #
@PUBLIC
def test_analyze_outside_the_case_root_is_refused(ctx: Ctx) -> None:
    run = _captured(ctx, facts=_fixtures.current_facts())
    assert run.run_dir and run.case_root
    elsewhere = ctx.tmp_path / "elsewhere"
    elsewhere.mkdir()
    code, env, raw = eng(ctx.capsys, *_analyze_argv(run.run_dir, elsewhere))
    assert code == 2, raw
    assert error_code(env) == "OUTSIDE_RUN_DIR"
    assert list(elsewhere.iterdir()) == []
    for rel in RECORDS:
        assert not (run.run_dir / rel).exists(), rel


@PUBLIC
def test_recur_with_the_trend_elsewhere_reads_the_case_root_and_warns(
    ctx: Ctx,
) -> None:
    first = _captured(ctx, facts=_fixtures.current_facts())
    code, _data, raw = run_recur(ctx, first, baseline=True)
    assert code == 0, raw
    fid = _fixtures.finding_id_j42()
    detected = finding(records(ctx, first), fid)

    second = _captured(ctx, facts=_fixtures.current_facts())
    assert second.case_root == first.case_root
    elsewhere = ctx.tmp_path / "elsewhere"
    code, data, raw = run_recur(ctx, second, workspace_root=elsewhere)
    assert code == 0, raw
    assert (elsewhere / "trend" / "history.json").is_file()
    account_root = second.case_root.parent.parent
    expected = (
        f"analysis prior read from the account root {account_root}; "
        f"trend written under {elsewhere}"
    )
    assert expected in all_warnings(data), all_warnings(data)
    carried = finding(records(ctx, second), fid)
    assert carried["episode_id"] == detected["episode_id"]


@PUBLIC
def test_a_run_dir_not_named_by_its_run_id_warns(ctx: Ctx) -> None:
    run = _captured(ctx, facts=_fixtures.current_facts())
    assert run.run_dir and run.case_root
    renamed = run.case_root / "my-review"
    shutil.move(str(run.run_dir), str(renamed))
    code, env, raw = helper(
        ctx.capsys,
        "run",
        "recur",
        str(renamed),
        "--workspace-root",
        str(run.case_root),
        "--baseline",
    )
    assert code == 0, raw
    assert NOT_RUN_ID in all_warnings(env.get("data") or {})


@PUBLIC
def test_a_public_out_elsewhere_is_unchanged(ctx: Ctx) -> None:
    run = new_run(ctx, task="health_check")
    assert run.run_dir
    anywhere = ctx.tmp_path / "anywhere" / "verify"
    ctx.seams.sql = {
        "columns": list(_fixtures.RUN_COLUMNS),
        "rows": [dict(r) for r in _fixtures.s2_rows()],
        "limit_reached": False,
    }
    code, _env, raw = helper(
        ctx.capsys,
        "verify",
        "run",
        "vt-job-run-states",
        "--ws",
        _fixtures.WS,
        "--warehouse-id",
        "wh-1",
        "--start",
        _fixtures.S2[0],
        "--end",
        _fixtures.S2[1],
        "--job-ids",
        _fixtures.JOB,
        "--limit",
        "20000",
        "--suffix",
        "x",
        "--out",
        str(anywhere),
    )
    assert code == 0, raw
    assert (anywhere / "vt-job-run-states-x.json").is_file()


# --------------------------------------------------------------------------- #
# D4-15: an internal_only run declares its one workspace at preflight
# --------------------------------------------------------------------------- #
OTHER_WS = "999"
SCOPE_FLAG = "--internal-workspace-id"


def _descriptor(ctx: Ctx, run: Run) -> dict[str, Any]:
    """The run's immutable descriptor (Drive: ``read_descriptor``; local: the file)."""
    if run.drive:
        from starboard_core.engagement.commit import read_descriptor

        assert run.rf
        return dict(read_descriptor(ctx.store, run.rf)[0].to_dict())
    assert run.run_dir
    return dict(json.loads((run.run_dir / DESCRIPTOR).read_text()))


@pytest.mark.parametrize(
    ("mode", "source_mode"),
    [
        ("drive_backed", "customer_workspace"),
        ("drive_backed", "hybrid"),
        ("public_local", "customer_workspace"),
    ],
)
def test_the_preflight_scope_flag_is_internal_only(ctx: Ctx, source_mode: str) -> None:
    before = ctx.sandbox.snapshot()
    objects = ctx.store.object_count
    argv = preflight_argv(
        ctx,
        task="troubleshooting",
        task_name="job-42",
        source_mode=source_mode,
        internal_scope=WS,
    )
    code, env, raw = eng(ctx.capsys, *argv)
    assert code == 2, raw
    text = error_text(env, raw)
    # A usage refusal that names the one allowed source mode (not argparse's
    # "unrecognized arguments").
    assert "internal_only" in text, text[:2000]
    assert ctx.store.object_count == objects
    assert local_files(ctx.reports) == []
    assert ctx.sandbox.snapshot() == before


@pytest.mark.parametrize(
    ("mode", "source_mode", "basis"),
    [
        ("internal_local", "internal_only", "declared"),
        ("drive_backed", "internal_only", "declared"),
        ("drive_backed", "customer_workspace", "verified"),
    ],
)
def test_route_records_the_scope_and_its_basis(
    ctx: Ctx, source_mode: str, basis: str
) -> None:
    run = new_run(
        ctx, task="troubleshooting", task_name="job-42", source_mode=source_mode
    )
    scope = _descriptor(ctx, run).get("authorized_scope") or {}
    assert scope.get("workspace_ids") == [WS], scope
    assert scope.get("basis") == basis, scope


def _verify_argv(run: Run, workspace_id: str) -> list[str]:
    assert run.rf
    return [
        "verify",
        "run",
        "vt-job-run-states",
        SCOPE_FLAG,
        workspace_id,
        "--start",
        _fixtures.S2[0],
        "--end",
        _fixtures.S2[1],
        "--job-ids",
        _fixtures.JOB,
        "--limit",
        "20000",
        "--suffix",
        "other",
        "--run-folder",
        run.rf,
    ]


@DRIVE
def test_a_drive_internal_slice_on_another_workspace_is_refused(ctx: Ctx) -> None:
    run = new_run(
        ctx, task="troubleshooting", task_name="job-42", source_mode="internal_only"
    )
    ctx.seams.sql = {
        "columns": list(_fixtures.RUN_COLUMNS),
        "rows": _fixtures.s2_rows(),
        "limit_reached": False,
    }
    before = ctx.sandbox.snapshot()
    objects = ctx.store.object_count
    code, env, raw = helper(ctx.capsys, *_verify_argv(run, OTHER_WS))
    assert code == 2, raw
    text = error_text(env, raw)
    assert "outside the run's authorized scope" in text, text[:2000]
    assert f"({WS})" in text, text[:2000]
    assert ctx.store.object_count == objects
    assert ctx.sandbox.snapshot() == before
    # The declared workspace passes the same scope check.
    rel = verify_slice(ctx, run, _fixtures.S2, _fixtures.s2_rows(), suffix="s2")
    assert rel.endswith("-s2.json")


@pytest.mark.parametrize("mode", ["internal_local", "drive_backed"])
def test_without_the_flag_case_open_names_it(
    ctx: Ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Preflight now refuses an internal_only run without the flag; a run preflighted
    # before that still has an empty scope, and case open names the flag for it.
    from starboard_skills.helpers.engagement import setup

    monkeypatch.setattr(setup, "_check_internal_workspace_id", lambda args, mode: None)
    run = new_run(
        ctx,
        task="troubleshooting",
        task_name="job-42",
        source_mode="internal_only",
        internal_scope=None,
    )
    code, env, raw = eng(
        ctx.capsys,
        "case",
        "open",
        *run.flags(),
        "--clue",
        f"job:{_fixtures.JOB}",
        "--question",
        QUESTION,
    )
    assert code == 2, raw
    assert SCOPE_FLAG in error_text(env, raw), raw[:2000]
