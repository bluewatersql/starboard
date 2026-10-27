"""Run-5 Group B fix B7: routing a local run creates ``<run-dir>/deliverables/``,
so the first deliverable write into it does not fail."""

from __future__ import annotations

from . import test_engagement_helper_phase2 as phase2
from .test_engagement_helper_phase2 import _internal_local_run

store, ws, sandbox = phase2.store, phase2.ws, phase2.sandbox


def test_local_route_creates_the_deliverables_dir(capsys, store):
    run_dir = _internal_local_run(capsys)
    assert (run_dir / "deliverables").is_dir()
    (run_dir / "deliverables" / "report.md").write_text("# report\n", encoding="utf-8")
