# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""F8: the ``queries_start`` banner count must equal what actually executes.

Root cause of the old mismatch ("61 queries" banner vs ``counts.total=52``): the
banner summed ``len(pack.queries)`` over the selected packs, but the executor drops
queries whose ``discovery_mode`` (DEEP_DIVE under GENERAL) isn't enabled, so the
banner over-counted by exactly the filtered deep-dive queries.
"""

from __future__ import annotations

import polars as pl
import pytest
from starboard.discovery.engine import DiscoveryEngine, EngineConfig
from starboard_core.domain.models.discovery.query import (
    DiscoveryMode,
    QueryPack,
    QueryResult,
    SystemQuery,
)


class _Exec:
    async def execute_sql(self, sql: str) -> pl.DataFrame:  # noqa: ARG002
        return pl.DataFrame({"n": [1]})


def _q(qid: str, mode: DiscoveryMode = DiscoveryMode.GENERAL) -> SystemQuery:
    return SystemQuery(
        query_id=qid,
        name=qid,
        description="t",
        sql_template="SELECT 1 LIMIT {result_limit}",
        required_tables=("system.t",),
        domain="d",
        discovery_mode=mode,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_banner_counts_only_eligible_queries_and_reports_filtered(monkeypatch):
    pack = QueryPack(
        pack_id="p",
        domain="d",
        name="p",
        description="t",
        queries=(_q("G1"), _q("G2"), _q("D1", DiscoveryMode.DEEP_DIVE)),
    )
    eng = DiscoveryEngine(sql_executor=_Exec(), config=EngineConfig(data_only=True))

    async def _audit(_trace: str) -> QueryResult:
        return QueryResult(query_id="A", domain="audit", data=None, error="x")

    monkeypatch.setattr(eng, "_run_audit", _audit)
    monkeypatch.setattr(
        eng._query_registry, "get_packs_for_products", lambda **_kw: [pack]
    )

    events: list[tuple[str, dict]] = []
    result = await eng.run(on_progress=lambda ph, info: events.append((ph, info)))

    start = next(info for ph, info in events if ph == "queries_start")
    executed = sum(len(pr.results) for pr in result.pack_results)
    assert start["query_count"] == executed == 2
    assert start["filtered_count"] == 1
    assert result.filtered_queries == 1
    # The deep-dive query never ran, so it is absent from the results.
    assert {qr.query_id for pr in result.pack_results for qr in pr.results} == {"G1", "G2"}
    # Rendered SQL LIMIT is carried on each result for the envelope's limit_reached.
    assert all(
        qr.result_limit == 50 for pr in result.pack_results for qr in pr.results
    )


@pytest.mark.unit
def test_envelope_counts_expose_filtered_bucket():
    from starboard.cli.cli.main import _discovery_json_envelope
    from starboard.discovery.engine import EngineResult

    env = _discovery_json_envelope(EngineResult(filtered_queries=9), "internal", None, ())
    counts = env["data"]["counts"]
    assert counts["filtered"] == 9
    assert counts["total"] == counts["succeeded"] + counts["skipped"] + counts["failed"]


# ---------------------------------------------------------------------------
# W28 — --include-deep-dive enables DEEP_DIVE queries in the engine
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_deep_dive_mode_runs_deep_dive_queries(monkeypatch):
    """When EngineConfig(discovery_mode=DEEP_DIVE), DEEP_DIVE queries run too."""
    pack = QueryPack(
        pack_id="p",
        domain="d",
        name="p",
        description="t",
        queries=(_q("G1"), _q("G2"), _q("D1", DiscoveryMode.DEEP_DIVE)),
    )
    eng = DiscoveryEngine(
        sql_executor=_Exec(),
        config=EngineConfig(data_only=True, discovery_mode=DiscoveryMode.DEEP_DIVE),
    )

    async def _audit(_trace: str) -> QueryResult:
        return QueryResult(query_id="A", domain="audit", data=None, error="x")

    monkeypatch.setattr(eng, "_run_audit", _audit)
    monkeypatch.setattr(
        eng._query_registry, "get_packs_for_products", lambda **_kw: [pack]
    )

    result = await eng.run()

    executed_ids = {qr.query_id for pr in result.pack_results for qr in pr.results}
    # All three queries run (two GENERAL + one DEEP_DIVE).
    assert executed_ids == {"G1", "G2", "D1"}
    assert result.filtered_queries == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_general_mode_still_filters_deep_dive_queries(monkeypatch):
    """Default GENERAL mode keeps filtering DEEP_DIVE queries — no regression."""
    pack = QueryPack(
        pack_id="p",
        domain="d",
        name="p",
        description="t",
        queries=(_q("G1"), _q("D1", DiscoveryMode.DEEP_DIVE)),
    )
    eng = DiscoveryEngine(
        sql_executor=_Exec(),
        config=EngineConfig(data_only=True),  # default = GENERAL
    )

    async def _audit(_trace: str) -> QueryResult:
        return QueryResult(query_id="A", domain="audit", data=None, error="x")

    monkeypatch.setattr(eng, "_run_audit", _audit)
    monkeypatch.setattr(
        eng._query_registry, "get_packs_for_products", lambda **_kw: [pack]
    )

    result = await eng.run()

    executed_ids = {qr.query_id for pr in result.pack_results for qr in pr.results}
    assert executed_ids == {"G1"}
    assert result.filtered_queries == 1
