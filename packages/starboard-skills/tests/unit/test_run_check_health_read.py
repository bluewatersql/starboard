"""``run check`` item ``health_read`` (D3-7): the latest report reflects the health read.

On a run with ``analysis/health.json`` the newest ``reports/health-read/rev-*.json`` body
carries the literal ``Insufficient evidence`` line when that is the verdict, and its
``Unknowns`` section names every unknown family as ``- <family>: unknown``.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from starboard_skills.helpers import contract
from starboard_skills.helpers.run import cmd_check

from .conftest import drive_files, make_drive_run, run_main
from .test_run_check import _make_run

_FAMILIES = ("consumption_trajectory", "efficiency", "reliability")
_BODY = "deliverables/report.md"


def _health(verdict: str, unknown: tuple[str, ...]) -> dict:
    return {
        "verdict": verdict,
        "families": [
            {"family": f, "assessment": "unknown" if f in unknown else "assessed"}
            for f in _FAMILIES
        ],
    }


def _report(
    rd: Path,
    body: str,
    *,
    revision: int = 1,
    at: str = "2026-10-08T10:00:00Z",
    report_id: str = "health-read",
    path: str = _BODY,
) -> None:
    (rd / path).parent.mkdir(parents=True, exist_ok=True)
    (rd / path).write_text(body)
    rev = rd / "reports" / report_id / f"rev-{revision:06d}.json"
    rev.parent.mkdir(parents=True, exist_ok=True)
    rev.write_text(
        json.dumps(
            {
                "report_id": report_id,
                "revision": revision,
                "created_at": at,
                "object_ref": {"path": path},
            }
        )
    )


def _check(rd: Path, capsys) -> tuple[int, dict]:
    with pytest.raises(SystemExit) as exc:
        cmd_check(SimpleNamespace(run_dir=str(rd), internal=False, format="json"))
    out = capsys.readouterr().out
    return int(exc.value.code), {**json.loads(out)["data"], "_raw": out}


def _health_failure(data: dict) -> str | None:
    return next(
        (f["reason"] for f in data["failed"] if f["item"] == "health_read"), None
    )


@pytest.fixture
def rd(tmp_path: Path) -> Path:
    return _make_run(tmp_path)


def _with_health(rd: Path, verdict: str, unknown: tuple[str, ...] = ()) -> Path:
    (rd / "analysis" / "health.json").write_text(json.dumps(_health(verdict, unknown)))
    return rd


_GOOD = (
    "# Acme health read\n\nInsufficient evidence\n\n## Unknowns\n"
    "- efficiency: unknown\n- reliability: unknown\n\n## Next\n- capture facts\n"
)


@pytest.mark.unit
class TestHealthRead:
    def test_no_health_read_passes(self, rd, capsys):
        code, data = _check(rd, capsys)
        assert code == 0 and "health_read" in data["passed"]

    def test_report_reflecting_the_read_passes(self, rd, capsys):
        _report(
            _with_health(rd, "insufficient_evidence", ("efficiency", "reliability")),
            _GOOD,
        )
        code, data = _check(rd, capsys)
        assert code == 0, data["failed"]
        assert "health_read" in data["passed"]

    def test_missing_insufficient_evidence_line_fails(self, rd, capsys):
        body = _GOOD.replace("Insufficient evidence\n", "All good.\n")
        _report(_with_health(rd, "insufficient_evidence", ("efficiency",)), body)
        code, data = _check(rd, capsys)
        assert code == 1
        assert "Insufficient evidence" in (_health_failure(data) or "")

    def test_unknown_family_missing_from_unknowns_fails(self, rd, capsys):
        body = "# Read\n\n## Unknowns\n- efficiency: unknown\n\n## Summary\n- reliability: unknown\n"
        _report(_with_health(rd, "health_read", ("efficiency", "reliability")), body)
        code, data = _check(rd, capsys)
        assert code == 1
        reason = _health_failure(data) or ""
        assert "reliability" in reason and "efficiency" not in reason

    def test_only_the_latest_revision_counts(self, rd, capsys):
        _with_health(rd, "health_read", ("efficiency",))
        _report(rd, "## Unknowns\n- efficiency: unknown\n", path="deliverables/old.md")
        _report(rd, "## Unknowns\n", revision=2, at="2026-10-09T10:00:00Z")
        code, data = _check(rd, capsys)
        assert code == 1 and "efficiency" in (_health_failure(data) or "")

    def test_non_integer_revision_counts_as_zero(self, rd, capsys):
        _with_health(rd, "health_read", ("efficiency",))
        _report(rd, "## Unknowns\n- efficiency: unknown\n")
        bad = rd / "reports" / "health-read" / "rev-000002.json"
        bad.write_text(
            json.dumps(
                {
                    "revision": "two",
                    "created_at": "2026-10-08T10:00:00Z",
                    "object_ref": {"path": "deliverables/other.md"},
                }
            )
        )
        code, data = _check(rd, capsys)
        assert code == 0, data["failed"]
        assert "health_read" in data["passed"]

    def test_a_later_report_of_another_id_is_not_the_health_read(self, rd, capsys):
        _with_health(rd, "health_read", ("efficiency",))
        _report(rd, "## Unknowns\n- efficiency: unknown\n")
        _report(
            rd,
            "# Executive summary\n",
            report_id="exec-summary",
            at="2026-10-09T10:00:00Z",
            path="deliverables/exec-summary.md",
        )
        code, data = _check(rd, capsys)
        assert code == 0, data["failed"]
        assert "health_read" in data["passed"]

    def test_only_another_report_id_is_no_report_yet(self, rd, capsys):
        _with_health(rd, "health_read", ("efficiency",))
        _report(rd, "# Executive summary\n", report_id="exec-summary")
        code, data = _check(rd, capsys)
        assert code == 0 and "health_read" in data["passed"]
        assert "has no report yet" not in data["_raw"]  # local: a warning that never clears

    def test_missing_report_body_fails(self, rd, capsys):
        _report(_with_health(rd, "health_read"), "x")
        (rd / _BODY).unlink()
        code, data = _check(rd, capsys)
        assert code == 1 and "not found" in (_health_failure(data) or "")

    def test_no_report_yet_passes_without_a_warning_locally(self, rd, capsys):
        """A local run never registers a report, so the warning could never clear there."""
        _with_health(rd, "insufficient_evidence", ("efficiency",))
        code, data = _check(rd, capsys)
        assert code == 0 and "health_read" in data["passed"]
        assert "has no report yet" not in data["_raw"]


@pytest.mark.unit
def test_drive_run_reads_the_analyzed_health(covered_env, monkeypatch, capsys):
    """A Drive run's health.json (from ``engagement analyze``) is checked via the sink."""
    drive_run = make_drive_run(intent="action_plan")
    monkeypatch.setattr(contract, "_load_storage", lambda: drive_run.store)
    code, out = run_main(
        ["engagement", "analyze", "--run-folder", drive_run.folder_id], capsys
    )
    assert code == 0, out
    assert "analysis/health.json" in drive_files(drive_run)
    code, out = run_main(["run", "check", "--run-folder", drive_run.folder_id], capsys)
    data = json.loads(out)["data"]
    assert "health_read" in data["passed"]
    assert "has no report yet" in out
