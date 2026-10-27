"""Run-5 group E5: the Drive discovery stdout summary is small and leads with the verdict.

A 30-pack discovery wrote a >15 KB "bounded" summary (refs with revision/md5 for every
object dominate) and a ``tail`` of it lost the top-level ``status``. The summary now
carries compact refs, stays under a small bound and puts ``ok``/``status``/``counts``
first.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from starboard.cli.cli import main as cli_main
from starboard.discovery.engine import EngineResult
from starboard_core.domain.models.discovery.query import PackResult, QueryResult

from tests.unit.cli._engagement_support import covered_env, drive_run
from tests.unit.cli.test_phase2_discover_sink import _args, _Client, _discover
from tests.unit.cli.test_phase2_public_golden import discover_config

SUMMARY_BUDGET = 8_000
N_PACKS = 30


class _BigEngine:
    """Many packs, one skipped query each: a layout with dozens of objects."""

    def __init__(
        self, sql_executor: Any, llm_client: Any, config: Any, **_kw: Any
    ) -> None:
        self.config = config

    async def run(self, on_progress: Any = None) -> EngineResult:
        packs = []
        for i in range(N_PACKS):
            ok = QueryResult(
                query_id=f"P{i}-01",
                domain=f"pack{i}",
                data=pl.DataFrame({"x": [1, 2]}),
                row_count=2,
            )
            skipped = QueryResult(
                query_id=f"P{i}-02",
                domain=f"pack{i}",
                data=None,
                error="SKIPPED: no table",
            )
            packs.append(
                PackResult(pack_id=f"pack{i}", domain=f"pack{i}", results=(ok, skipped))
            )
        return EngineResult(trace_id="t", pack_results=packs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_drive_summary_is_small_and_verdict_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store, folder = drive_run()
    covered_env(monkeypatch, tmp_path, store, cli_main)
    monkeypatch.setattr("starboard.bootstrap.DiscoveryEngine", _BigEngine)
    monkeypatch.setattr("starboard.bootstrap.AsyncSQLExecutor", lambda _c: object())
    monkeypatch.setattr(cli_main, "AsyncDatabricksClient", _Client)

    code = await _discover(
        _args(run_folder=folder, out_dir="discovery"), discover_config()
    )

    assert code == 0
    out = capsys.readouterr().out
    assert len(out.encode()) <= SUMMARY_BUDGET
    payload = json.loads(out)
    # The verdict leads, and the whole line fits a 15 KB `tail`.
    assert list(payload)[:5] == ["ok", "status", "domain", "command", "counts"]
    assert payload["status"] in {"ok", "partial", "no_evidence"}
    refs = payload["refs"]
    # Run 7: per-pack refs give way before the facts and are counted. At this
    # budget summary.packs is cut too (marked), and manifest.json lists every pack.
    assert len(refs) + payload.get("pack_refs_omitted", 0) >= N_PACKS
    packs = payload["summary"]["packs"]
    assert len(packs) + payload.get("omitted", {}).get("summary.packs", 0) == N_PACKS
    assert all(p["path"] for p in packs)
    assert all(set(r) <= {"path", "object_id", "size"} for r in refs)
    assert {"discovery/discovery.json", "discovery/manifest.json"} <= {
        r["path"] for r in refs
    }
