"""Live customer run (2026-10-21): an internal discovery run can pass ``run check``.

The ``discovery`` profile checks items 12/16 (``.clean`` siblings, sanitized prose) on
an internal run, but a discovery run has no ``deliverables/`` (item 9 is not in its
profile): nothing leaves the run folder, so there is nothing to sanitize. Both items
failed "deliverables/ missing — see item 9" and the run could never exit 0.
"""

from __future__ import annotations

import json
import shutil
from types import SimpleNamespace

import pytest
from starboard_skills.helpers.run import cmd_check

from .test_run_check_profiles import _ids, _run

pytestmark = pytest.mark.unit


def _check_internal(rd, capsys):
    args = SimpleNamespace(run_dir=str(rd), internal=True, format="json")
    with pytest.raises(SystemExit) as exc:
        cmd_check(args)
    return int(exc.value.code or 0), json.loads(capsys.readouterr().out)["data"]


def test_internal_discovery_without_deliverables_passes_12_and_16(tmp_path, capsys):
    rd = _run(tmp_path, "discovery")
    shutil.rmtree(rd / "deliverables")
    code, data = _check_internal(rd, capsys)
    assert code == 0, data["failed"]
    assert {"12", "16"} <= _ids(data["passed"])


def test_an_action_plan_still_needs_its_deliverables(tmp_path, capsys):
    rd = _run(tmp_path, "action_plan")
    shutil.rmtree(rd / "deliverables")
    code, data = _check_internal(rd, capsys)
    assert code != 0
    assert "12" in _ids(data["failed"])


def test_a_health_check_run_without_deliverables_still_fails_12(tmp_path, capsys):
    # Only discovery publishes nothing; a health read is published, so it is sanitized.
    rd = _run(tmp_path, "health_check")
    shutil.rmtree(rd / "deliverables")
    code, data = _check_internal(rd, capsys)
    assert code != 0
    assert "12" in _ids(data["failed"])


def test_an_empty_deliverables_dir_shares_nothing(tmp_path, capsys):
    # A local route always creates deliverables/ (empty on a discovery run).
    rd = _run(tmp_path, "discovery")
    shutil.rmtree(rd / "deliverables")
    (rd / "deliverables").mkdir()
    code, data = _check_internal(rd, capsys)
    assert code == 0, data["failed"]
    assert {"12", "16"} <= _ids(data["passed"])


def test_internal_discovery_on_drive_passes_12_and_16(
    tmp_path, covered_env, monkeypatch, capsys
):
    # The customer run was a Drive run (the default storage): the remote branch reads
    # the run through a SinkPath and must apply the same discovery exemption.
    from starboard_skills.helpers import contract

    from .conftest import drive_files, make_drive_run, run_main, upload_tree
    from .test_run_check import _make_run

    run = make_drive_run(intent="discovery")
    monkeypatch.setattr(contract, "_load_storage", lambda: run.store)
    src = tmp_path / "src"
    src.mkdir()
    rd = _make_run(src, internal=True)
    (rd / "analysis" / "run-authorization.json").unlink(missing_ok=True)
    shutil.rmtree(rd / "deliverables")
    upload_tree(run, rd)
    code, out = run_main(
        ["run", "check", "--run-folder", run.folder_id, "--internal"], capsys
    )
    stored = json.loads(drive_files(run)["analysis/run-check.json"])
    assert code == 0, stored["data"]["failed"]
    assert {"12", "16"} <= _ids(stored["data"]["passed"])
