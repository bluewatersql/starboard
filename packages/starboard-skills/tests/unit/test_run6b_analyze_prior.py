"""Run-6b: ``engagement analyze`` takes the same ``--prior`` / ``--baseline`` as recur.

A health review runs ``analyze`` before ``run recur``; when recur pins its prior
with ``--prior drive:<id>`` and analyze cannot, the two compare different runs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .conftest import drive_files, run_main
from .test_internal_only_local_bound import _internal_run
from .test_run_recur_drive import (
    PRIOR,
    _current,
    _finding,
    _manifest,
    _recur,
    _registered_prior,
)

OLDER = "20260808_12345678-1234-4234-8234-000000000002"


def _analyze(run, capsys, *extra: str) -> tuple[int, str]:
    return run_main(
        ["engagement", "analyze", "--run-folder", run.folder_id, *extra], capsys
    )


def _two_priors(drive_run, capsys):
    older = _registered_prior(
        drive_run, capsys, window=("2026-07-09", "2026-08-07"), run_id=OLDER
    )
    newer = _registered_prior(drive_run, capsys)
    _current(drive_run)
    return older, newer


@pytest.mark.unit
class TestAnalyzePrior:
    def test_default_compares_the_newest_prior(self, covered_env, drive_run, capsys):
        _two_priors(drive_run, capsys)
        code, out = _analyze(drive_run, capsys)
        assert code == 0, out
        assert json.loads(out)["data"]["window"]["prior_run_id"] == PRIOR

    def test_prior_pins_the_same_run_as_recur(self, covered_env, drive_run, capsys):
        older, _ = _two_priors(drive_run, capsys)
        code, out = _analyze(drive_run, capsys, "--prior", f"drive:{older.folder_id}")
        assert code == 0, out
        assert json.loads(out)["data"]["window"]["prior_run_id"] == OLDER
        code, out = _recur(drive_run, capsys, "--prior", f"drive:{older.folder_id}")
        assert code == 0, out
        rr = json.loads(drive_files(drive_run)["analysis/recur-result.json"])
        assert rr["window"]["prior_run_id"] == OLDER

    def test_baseline_compares_nothing(self, covered_env, drive_run, capsys):
        _two_priors(drive_run, capsys)
        code, out = _analyze(drive_run, capsys, "--baseline")
        assert code == 0, out
        data = json.loads(out)["data"]
        assert data["baseline"] is True and data["counts"]["prior_candidates"] == 0

    @pytest.mark.parametrize(
        "how", ["no_prefix", "same_folder", "unreadable", "with_baseline"]
    )
    def test_bad_prior_is_refused_before_anything_is_written(
        self, covered_env, drive_run, capsys, how
    ):
        _current(drive_run)
        before = set(drive_files(drive_run))
        flags = {
            "no_prefix": ["--prior", drive_run.folder_id],
            "same_folder": ["--prior", f"drive:{drive_run.folder_id}"],
            "unreadable": ["--prior", "drive:no-such"],
            "with_baseline": ["--prior", "drive:no-such", "--baseline"],
        }[how]
        code, out = _analyze(drive_run, capsys, *flags)
        assert code != 0, out
        assert "--prior" in out
        assert set(drive_files(drive_run)) == before


@pytest.mark.unit
def test_local_prior_is_a_warning_like_local_recur(covered_env, capsys):
    """A local analysis reads every prior run of its root, as local recur does."""
    rd = _internal_run(Path.cwd())
    (rd / "findings-manifest.json").write_text(
        _manifest(
            "2026-09-08", "2026-10-07", [_finding("W-IDLE", "wh-1", 40.0)], "2026-10-08"
        )
    )
    code, out = run_main(
        [
            "engagement",
            "analyze",
            "--run-dir",
            str(rd),
            "--workspace-root",
            str(rd.parent),
            "--prior",
            str(rd.parent / "older"),
        ],
        capsys,
    )
    assert code == 0, out
    warnings = json.loads(out)["data"]["warnings"]
    assert any(w.startswith("--prior picks the trend delta only") for w in warnings)
