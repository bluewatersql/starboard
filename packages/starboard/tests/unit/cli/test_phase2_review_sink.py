# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Phase 2 (P2-G1/G3/G12): ``starboard review --run-folder`` reads and writes the run.

* Covered run against ``InMemoryEngagementStorage``: the run's discovery output is the
  evidence; ``analysis/review.json``, ``analysis/review.md`` and
  ``findings-manifest.json`` land in the run with EvidenceRefs; empty sandbox diff;
  bounded compact stdout.
* ``--from-discovery`` / ``--since`` take run-relative paths or ``drive:<id>``.
* Refusal of each local path flag on a covered run, and of an overlay review
  without ``--run-folder`` (unless ``--run-dir`` is an internal-only local run).

The public bytes are pinned by ``test_phase2_public_golden.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console
from starboard.cli.cli import main as cli_main
from starboard.cli.cli import review_command
from starboard.cli.cli.review_command import run_review
from starboard_core.engagement.evidence import record_evidence
from starboard_core.engagement.write_guard import active

from tests.unit.cli._engagement_support import (
    STDOUT_BUDGET,
    WS,
    covered_env,
    diff,
    drive_run,
    evidence,
    local_run_dir,
    overlay_on,
    sink_for,
    snapshot,
    written,
)
from tests.unit.cli.test_phase2_public_golden import (
    GoldenEngine,
    discover_args,
    discover_config,
)

REVIEW_OUTPUTS = {
    "analysis/review.json",
    "analysis/review.md",
    "findings-manifest.json",
}


class _Client:
    def __init__(self, *a: object, **k: object) -> None:
        pass

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *a: object) -> bool:
        return False

    async def get_workspace_id(self) -> str:
        return WS


@pytest.fixture(autouse=True)
def _restore_logging() -> Any:
    """The CLI pins structlog/stdlib logging to the (captured) stderr; undo it."""
    import logging

    import structlog

    saved = structlog.get_config()
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    structlog.configure(**saved)
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.fixture(autouse=True)
def _no_guard_leak() -> Any:
    assert not active()
    yield
    assert not active()


def _covered_with_discovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> tuple[Any, str, dict[str, Path]]:
    """A covered Drive run that already holds a discovery layout at its root."""
    import asyncio

    store, folder = drive_run()
    sandbox = covered_env(monkeypatch, tmp_path, store, cli_main, review_command)
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", GoldenEngine)
    monkeypatch.setattr("starboard.bootstrap.AsyncSQLExecutor", lambda _c: object())
    monkeypatch.setattr(cli_main, "AsyncDatabricksClient", _Client)
    asyncio.run(
        cli_main.run_discovery_mode(
            discover_args(internal_workspace_id=None, json=False, run_folder=folder),
            discover_config(),
            Console(stderr=True),
        )
    )
    capsys.readouterr()
    return store, folder, sandbox


@pytest.mark.unit
def test_covered_review_reads_run_discovery_and_writes_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, folder, sandbox = _covered_with_discovery(monkeypatch, tmp_path, capsys)
    before = snapshot(sandbox)

    code = run_review(["--run-folder", folder])

    out = capsys.readouterr().out
    assert code == 0, out
    assert len(out.encode()) <= STDOUT_BUDGET
    assert out.count("\n") == 1
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["run_folder_id"] == folder
    assert payload["summary"]["review_path"] == "analysis/review.json"
    assert diff(sandbox, before) == []
    sink = sink_for(store, folder)
    assert written(sink) >= REVIEW_OUTPUTS
    review = json.loads(sink.get_bytes("analysis/review.json"))
    assert review["ok"] is True
    assert review["data"]["evidence_source"]["kind"] == "discovery"
    assert review["data"]["evidence_source"]["path"] == "."  # run root
    assert sink.get_bytes("analysis/review.md").startswith(b"# Workload Review")
    manifest = json.loads(sink.get_bytes("findings-manifest.json"))
    assert manifest["snapshot_version"]
    review_refs = [r for r in evidence(sink) if r.storage_ref.path in REVIEW_OUTPUTS]
    assert {r.storage_ref.path for r in review_refs} == REVIEW_OUTPUTS
    for ref in review_refs:
        assert ref.scope_workspace_ids == (WS,)
        assert ref.producer.startswith("review:")


@pytest.mark.unit
def test_since_relpath_and_drive_object_inputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, folder, sandbox = _covered_with_discovery(monkeypatch, tmp_path, capsys)
    assert run_review(["--run-folder", folder]) == 0
    capsys.readouterr()
    sink = sink_for(store, folder)
    envelope_id = next(
        r for r in evidence(sink) if r.storage_ref.path == "discovery.json"
    )
    before = snapshot(sandbox)

    code = run_review(
        [
            "--run-folder",
            folder,
            "--from-discovery",
            f"drive:{envelope_id.storage_ref.object_id}",
            "--since",
            "findings-manifest.json",
            "--out",
            "analysis/review-2.json",
            "--manifest-out",
            "analysis/manifest-2.json",
            "--snapshot-out",
            "analysis/snapshot-2.json",
        ]
    )

    out = capsys.readouterr().out
    assert code == 0, out
    assert json.loads(out)["summary"]["markdown_path"] == "analysis/review-2.md"
    review = json.loads(sink_for(store, folder).get_bytes("analysis/review-2.json"))
    assert "cost_delta" in review["data"]
    assert {
        "analysis/review-2.json",
        "analysis/review-2.md",
        "analysis/manifest-2.json",
        "analysis/snapshot-2.json",
    } <= written(sink_for(store, folder))
    assert diff(sandbox, before) == []


def _review_kinds(store: Any, folder: str) -> set[tuple[str, str]]:
    return {
        (r.source_kind, r.audience_class)
        for r in evidence(sink_for(store, folder))
        if r.producer.startswith("review:")
    }


@pytest.mark.unit
def test_review_of_customer_discovery_is_customer_shareable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, folder, _ = _covered_with_discovery(monkeypatch, tmp_path, capsys)
    assert run_review(["--run-folder", folder]) == 0
    capsys.readouterr()
    assert _review_kinds(store, folder) == {("customer_workspace", "customer_shareable")}


@pytest.mark.unit
def test_review_over_an_internal_mirror_input_is_internal_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """arch H4: the audience comes from the inputs; one internal-mirror pack wins."""
    store, folder, _ = _covered_with_discovery(monkeypatch, tmp_path, capsys)
    sink = sink_for(store, folder)
    rows = {"results": [{"query_id": "zz-internal", "status": "succeeded", "rows": []}]}
    ref = sink.put_bytes("raw/zz-internal.json", json.dumps(rows).encode(), "application/json")
    record_evidence(
        sink,
        [(ref, "discovery:zz-internal", 0, False)],
        source_kind="internal_mirror",
        scope=(WS,),
        method_version="m1",
    )
    assert run_review(["--run-folder", folder]) == 0
    capsys.readouterr()
    assert _review_kinds(store, folder) == {("internal_mirror", "internal_only")}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("extra", "flag"),
    [
        (["--out", "/tmp/review.json"], "--out"),
        (["--manifest-out", "../m.json"], "--manifest-out"),
        (["--snapshot-out", "~/s.json"], "--snapshot-out"),
        (["--since", "/tmp/prior.json"], "--since"),
        (["--from-discovery", "/tmp/discovery"], "--from-discovery"),
        (["--run-dir", "/tmp/local-run"], "--run-dir"),
    ],
)
def test_covered_review_refuses_local_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    extra: list[str],
    flag: str,
) -> None:
    store, folder = drive_run()
    sandbox = covered_env(monkeypatch, tmp_path, store, review_command)
    before = snapshot(sandbox)

    code = run_review(["--run-folder", folder, *extra])

    assert code == 2
    env = json.loads(capsys.readouterr().out)
    assert env["ok"] is False
    assert env["error"].startswith("LOCAL_STORAGE_REFUSED"), env["error"]
    assert flag in env["error"]
    assert written(sink_for(store, folder)) == set()
    assert diff(sandbox, before) == []


@pytest.mark.unit
def test_overlay_review_without_run_folder_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    overlay_on(monkeypatch, review_command)
    out_file = tmp_path / "review.json"

    code = run_review(
        ["--from-discovery", str(tmp_path), "--out", str(out_file), "--json"]
    )

    assert code == 2
    env = json.loads(capsys.readouterr().out)
    assert env["error"].startswith("LOCAL_STORAGE_REFUSED")
    assert "--run-folder" in env["error"]
    assert not out_file.exists()


@pytest.mark.unit
def test_bare_internal_with_run_folder_is_arg_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, folder = drive_run()
    covered_env(monkeypatch, tmp_path, store, review_command)

    code = run_review(["--run-folder", folder, "--internal"])

    assert code == 4
    assert "--from-discovery" in json.loads(capsys.readouterr().out)["error"]


def _saved_discovery(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    out_dir: Path,
    *,
    source: str | None,
) -> Path:
    """A saved discovery output at ``out_dir``, its envelope ``data.source`` set."""
    import asyncio

    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", GoldenEngine)
    asyncio.run(
        cli_main.run_discovery_mode(
            discover_args(out_dir=str(out_dir)),
            discover_config(),
            Console(stderr=True),
        )
    )
    capsys.readouterr()
    envelope_file = out_dir / "discovery.json"
    payload = json.loads(envelope_file.read_text())
    payload["data"]["source"] = source
    envelope_file.write_text(json.dumps(payload))
    return out_dir


@pytest.mark.unit
def test_internal_only_local_run_dir_keeps_local_review(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """D-11: on an overlay install, ``--run-dir`` naming an internal-only local run
    keeps the unchanged local review path over internal discovery inside it."""
    run_dir = local_run_dir(tmp_path)
    disc = _saved_discovery(monkeypatch, capsys, run_dir / "disc", source="internal")
    overlay_on(monkeypatch, review_command)
    out_file = run_dir / "analysis" / "review.json"

    code = run_review(
        ["--from-discovery", str(disc), "--run-dir", str(run_dir), "--out", str(out_file)]
    )

    assert code == 0, capsys.readouterr().out
    assert json.loads(out_file.read_text())["ok"] is True


@pytest.mark.unit
@pytest.mark.parametrize(
    ("inside", "source"),
    [(False, "internal"), (True, "external"), (True, None)],
    ids=["outside-run-dir", "customer-source", "no-source"],
)
def test_internal_only_local_run_dir_refuses_other_discovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    inside: bool,
    source: str | None,
) -> None:
    """An internal-only ``--run-dir`` review reads only internal discovery saved
    inside the run dir; anything else is ``LOCAL_FILE_INTAKE_REFUSED`` (exit 2)."""
    run_dir = local_run_dir(tmp_path)
    where = run_dir / "disc" if inside else tmp_path / "disc"
    disc = _saved_discovery(monkeypatch, capsys, where, source=source)
    overlay_on(monkeypatch, review_command)
    out_file = run_dir / "analysis" / "review.json"

    code = run_review(
        [
            "--from-discovery",
            str(disc),
            "--run-dir",
            str(run_dir),
            "--out",
            str(out_file),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert code == 2
    assert captured.err.startswith("LOCAL_FILE_INTAKE_REFUSED")
    assert json.loads(captured.out.strip().splitlines()[-1])["ok"] is False
    assert not out_file.exists()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("inside", "discovery_source"),
    [(False, None), (True, "external")],
    ids=["outside-run-dir", "customer-source"],
)
def test_internal_only_local_run_dir_refuses_other_since(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    inside: bool,
    discovery_source: str | None,
) -> None:
    run_dir = local_run_dir(tmp_path)
    disc = _saved_discovery(monkeypatch, capsys, run_dir / "disc", source="internal")
    since = (run_dir if inside else tmp_path) / "prior.json"
    since.write_text(
        json.dumps(
            {
                "snapshot_version": "1",
                "finding_ids": [],
                "evidence_source": {"discovery_source": discovery_source},
            }
        )
    )
    overlay_on(monkeypatch, review_command)
    out_file = run_dir / "analysis" / "review.json"

    code = run_review(
        [
            "--from-discovery",
            str(disc),
            "--since",
            str(since),
            "--run-dir",
            str(run_dir),
            "--out",
            str(out_file),
        ]
    )

    assert code == 2
    last = capsys.readouterr().err.strip().splitlines()[-1]
    assert last.startswith("LOCAL_FILE_INTAKE_REFUSED")
    assert not out_file.exists()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("authorized", "name", "ok"),
    [
        (True, "findings-manifest.json", True),
        (False, "findings-manifest.json", False),
        (True, "prior.json", False),
    ],
    ids=["internal-prior-manifest", "unauthorized-sibling", "other-file"],
)
def test_internal_only_local_run_dir_since_reads_a_prior_run_of_the_case(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    authorized: bool,
    name: str,
    ok: bool,
) -> None:
    """``--since <case root>/<prior run>/findings-manifest.json`` (what ``run recur``
    hints) is read when the prior run is itself an internal-only local run."""
    case = tmp_path / "case"
    run_dir = local_run_dir(case)
    prior = case / "prior-run"
    (prior / "analysis").mkdir(parents=True)
    if authorized:
        auth = run_dir / "analysis" / "run-authorization.json"
        (prior / "analysis" / "run-authorization.json").write_text(auth.read_text())
    since = prior / name
    since.write_text(
        json.dumps(
            {
                "snapshot_version": "1",
                "finding_ids": [],
                "evidence_source": {"discovery_source": "internal"},
            }
        )
    )
    disc = _saved_discovery(monkeypatch, capsys, run_dir / "disc", source="internal")
    overlay_on(monkeypatch, review_command)
    out_file = run_dir / "analysis" / "review.json"

    code = run_review(
        [
            "--from-discovery",
            str(disc),
            "--since",
            str(since),
            "--run-dir",
            str(run_dir),
            "--out",
            str(out_file),
        ]
    )

    err = capsys.readouterr().err
    if ok:
        assert code == 0, err
        assert json.loads(out_file.read_text())["ok"] is True
    else:
        assert code == 2
        assert err.strip().splitlines()[-1].startswith("LOCAL_FILE_INTAKE_REFUSED")
        assert not out_file.exists()
