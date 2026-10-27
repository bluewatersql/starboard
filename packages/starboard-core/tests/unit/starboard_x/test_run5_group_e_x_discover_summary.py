"""Run-5 group E5 (starboard_x): the ``discovery run --run-folder`` stdout summary is small.

Same contract as ``starboard --discover --run-folder``: verdict keys first, compact refs
(``path``, ``object_id``, ``size``) last, and an 8 KB budget instead of 24 KB.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.unit.starboard_x._writer_support import Df, drive_run
from tests.unit.starboard_x.test_discovery_writer_sink import _covered, _run_main

SUMMARY_BUDGET = 8_000
N_PACKS = 30


def _many_packs() -> Any:
    packs = []
    for i in range(N_PACKS):
        qr = SimpleNamespace(
            query_id=f"Q-{i}",
            domain="d",
            data=Df([{"x": n} for n in range(3)]),
            error=None,
            row_count=3,
            succeeded=True,
            skipped=False,
            result_limit=None,
        )
        packs.append(SimpleNamespace(pack_id=f"pack-{i}", domain="d", results=[qr]))
    return SimpleNamespace(
        trace_id="t",
        elapsed_ms=1.0,
        errors=[],
        audit_result=None,
        pack_results=packs,
        domain_analyses=[],
    )


@pytest.mark.unit
def test_drive_summary_is_small_verdict_first_with_compact_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store, folder = drive_run()
    _covered(monkeypatch, tmp_path, store, _many_packs())

    code, env, raw = _run_main(["run", "--data-only", "--run-folder", folder], capsys)

    assert code == 0, env
    assert len(raw.encode()) <= SUMMARY_BUDGET
    data = env["data"]
    assert list(data)[:2] == ["counts", "errors"]
    assert data["counts"]["packs"] == N_PACKS
    refs = data["refs"]
    # Run 7: per-pack refs give way before the facts; every pack's path stays in
    # summary.packs and the dropped refs are counted.
    assert len(refs) + data.get("pack_refs_omitted", 0) >= N_PACKS
    assert len(data["summary"]["packs"]) == N_PACKS
    assert all(p["path"] for p in data["summary"]["packs"])
    assert all(set(r) <= {"path", "object_id", "size"} for r in refs)
    assert {"discovery.json", "manifest.json"} <= {r["path"] for r in refs}
