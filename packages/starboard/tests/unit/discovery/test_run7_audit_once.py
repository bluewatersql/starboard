# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Run 7: the audit query runs once per discovery.

``audit`` is an always-run pack, so phase 2's pack selection picks it again after
phase 1 ran it. It ran twice on the warehouse (or, on a capture, was "reused" from
the same run: ``resumed.queries_reused: 1`` on a brand-new run folder). Phase 2
now keeps phase 1's audit result instead of running the pack again.
"""

from __future__ import annotations

from typing import Any

import pytest
from starboard.discovery.query_packs.audit import AUDIT_PACK
from starboard_core.domain.models.discovery.query import PackResult, QueryPack
from starboard_core.engagement.sink import MemorySink

from .test_run6b_capture_resume import _engine, _Exec, _Registry, _results


class _RealSelection(_Registry):
    """Phase 2 selects the audit pack too, as the default registry does."""

    def get_packs_for_products(self, *a: Any, **k: Any) -> list[QueryPack]:
        return [AUDIT_PACK, self.pack]


@pytest.mark.unit
async def test_a_fresh_capture_runs_the_audit_once_and_reuses_nothing() -> None:
    executor = _Exec()
    result = await _engine(
        executor, MemorySink(run_id="r"), registry=_RealSelection()
    ).run()
    assert executor.calls.count("P-AUDIT01") == 1
    assert result.resumed == {"queries_reused": 0}
    audit_packs = [pr for pr in result.pack_results if pr.pack_id == "audit"]
    assert len(audit_packs) == 1
    assert _results(result)["P-AUDIT01"].succeeded


@pytest.mark.unit
async def test_the_audit_pack_is_reported_done_once_in_phase_two() -> None:
    done: list[str] = []

    def on_progress(event: str, data: dict[str, Any]) -> None:
        if event == "pack_done":
            done.append(data["pack_id"])

    engine = _engine(_Exec(), MemorySink(run_id="r"), registry=_RealSelection())
    await engine.run(on_progress=on_progress)
    assert sorted(done) == ["audit", "billing"]


@pytest.mark.unit
async def test_a_resumed_capture_still_reuses_every_query() -> None:
    sink = MemorySink(run_id="r")
    await _engine(_Exec(), sink, registry=_RealSelection()).run()
    again = _Exec()
    second = await _engine(again, sink, registry=_RealSelection()).run()
    assert again.calls == []
    assert second.resumed == {"queries_reused": 4}
    assert isinstance(second.pack_results[0], PackResult)
