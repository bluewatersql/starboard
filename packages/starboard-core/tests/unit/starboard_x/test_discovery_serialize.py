# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Envelope honesty for the shared discovery serializer (F9).

``truncated`` means "the serializer dropped rows past its own safety cap".
A query capped by its own SQL ``LIMIT {result_limit}`` is reported separately via
``limit_reached`` / ``row_limit`` so a host doesn't read exactly-N rows as complete.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from starboard_x.discovery._serialize import serialize_result, write_result_files


class _Df:
    """Minimal polars-like duck type (``to_dicts`` / ``columns``)."""

    def __init__(self, n: int) -> None:
        self.columns = ["x"]
        self._n = n

    def to_dicts(self) -> list[dict[str, int]]:
        return [{"x": i} for i in range(self._n)]


def _qr(query_id: str, n: int, result_limit: int | None) -> SimpleNamespace:
    return SimpleNamespace(
        query_id=query_id,
        domain="d",
        data=_Df(n),
        error=None,
        row_count=n,
        succeeded=True,
        skipped=False,
        result_limit=result_limit,
    )


def _result(*qrs: SimpleNamespace) -> SimpleNamespace:
    pack = SimpleNamespace(pack_id="p", domain="d", results=list(qrs))
    return SimpleNamespace(pack_results=[pack], errors=[], trace_id="t", elapsed_ms=1.0)


def _by_id(env: dict) -> dict:
    return {q["query_id"]: q for q in env["packs"][0]["results"]}


@pytest.mark.unit
def test_limit_reached_when_rows_equal_sql_limit() -> None:
    out = _by_id(serialize_result(_result(_qr("A", 50, 50))))["A"]
    assert out["limit_reached"] is True
    assert out["row_limit"] == 50
    # `truncated` keeps its meaning: the serializer itself dropped nothing.
    assert out["truncated"] is False


@pytest.mark.unit
def test_limit_not_reached_below_sql_limit() -> None:
    out = _by_id(serialize_result(_result(_qr("A", 49, 50))))["A"]
    assert out["limit_reached"] is False
    assert out["row_limit"] == 50


@pytest.mark.unit
def test_no_templated_limit_is_never_limit_reached() -> None:
    out = _by_id(serialize_result(_result(_qr("A", 50, None))))["A"]
    assert out["limit_reached"] is False
    assert out["row_limit"] is None


@pytest.mark.unit
def test_duck_typed_fake_without_result_limit_is_backward_compatible() -> None:
    fake = SimpleNamespace(
        query_id="A", domain="d", data=_Df(3), error=None, row_count=3, succeeded=True
    )
    out = _by_id(serialize_result(_result(fake)))["A"]
    assert out["limit_reached"] is False
    assert out["row_limit"] is None
    assert out["rows"] == [{"x": 0}, {"x": 1}, {"x": 2}]


@pytest.mark.unit
def test_write_result_files_manifest_flags_limit_reached(tmp_path) -> None:
    manifest = write_result_files(_result(_qr("A", 50, 50)), str(tmp_path))["manifest"]
    assert manifest[0]["limit_reached"] is True
    assert manifest[0]["truncated"] is False


# ---------------------------------------------------------------------------
# W21 — per-query lookback_days in the serialized output
# ---------------------------------------------------------------------------


def _qr_with_lookback(query_id: str, n: int, lookback: int | None) -> SimpleNamespace:
    """Query result carrying an explicit ``lookback_days`` field."""
    return SimpleNamespace(
        query_id=query_id,
        domain="d",
        data=_Df(n),
        error=None,
        row_count=n,
        succeeded=True,
        skipped=False,
        result_limit=None,
        lookback_days=lookback,
    )


@pytest.mark.unit
def test_serialize_query_carries_lookback_days() -> None:
    """Per-query lookback_days is emitted so per-query windows are visible."""
    out = _by_id(serialize_result(_result(_qr_with_lookback("A", 5, 14))))["A"]
    assert out["lookback_days"] == 14


@pytest.mark.unit
def test_serialize_query_lookback_days_none_when_absent() -> None:
    """Backward-compatible: a fake without lookback_days gets None, not an error."""
    fake = SimpleNamespace(
        query_id="A", domain="d", data=_Df(3), error=None, row_count=3, succeeded=True
    )
    out = _by_id(serialize_result(_result(fake)))["A"]
    assert out["lookback_days"] is None


@pytest.mark.unit
def test_serialize_query_lookback_days_90_override() -> None:
    """A query with a per-query override (e.g. 90 d) is stamped as 90."""
    out = _by_id(serialize_result(_result(_qr_with_lookback("B", 2, 90))))["B"]
    assert out["lookback_days"] == 90


@pytest.mark.unit
def test_serialize_query_carries_attempt_metadata() -> None:
    from starboard_x.discovery._serialize import _serialize_query

    qr = _qr("Q1", 1, None)
    qr.execution_time_ms = 1234.567
    qr.attempts = 2
    qr.attempt_elapsed_ms = (300000.04, 1234.5)
    out = _serialize_query(qr)
    assert out["attempts"] == 2
    assert out["attempt_elapsed_ms"] == [300000.0, 1234.5]
    assert out["execution_time_ms"] == 1234.6


@pytest.mark.unit
def test_serialize_query_attempts_absent_on_duck_typed_fake() -> None:
    from types import SimpleNamespace

    from starboard_x.discovery._serialize import _serialize_query

    out = _serialize_query(SimpleNamespace(query_id="Q", succeeded=False, error="x"))
    assert out["attempts"] is None
    assert out["attempt_elapsed_ms"] == []
    assert out["execution_time_ms"] is None


@pytest.mark.unit
def test_write_pack_file_and_facts_file_incrementally(tmp_path) -> None:
    import json
    from types import SimpleNamespace

    from starboard_x.discovery._serialize import write_facts_file, write_pack_file

    pr = SimpleNamespace(pack_id="warehouse", domain="warehouse", results=[_qr("W-W01", 3, 50)])
    entry, serialized = write_pack_file(pr, str(tmp_path))
    assert entry["path"] == "raw/warehouse.json"
    assert entry["rows_total"] == 3
    raw = json.loads((tmp_path / "raw" / "warehouse.json").read_text())
    assert raw["results"][0]["query_id"] == "W-W01"
    assert serialized[0]["query_id"] == "W-W01"

    facts = write_facts_file([], str(tmp_path))
    assert json.loads((tmp_path / "facts.json").read_text()) == json.loads(
        json.dumps(facts, default=str)
    )


# --- data-only domain_analyses: deterministic per-domain summary (round-7) ---


def _status_qr(query_id: str, n: int, status: str, domain: str = "d") -> SimpleNamespace:
    return SimpleNamespace(
        query_id=query_id,
        domain=domain,
        data=_Df(n) if status == "succeeded" else None,
        error=None if status == "succeeded" else "x",
        row_count=n,
        status=status,
        succeeded=status == "succeeded",
        skipped=status == "skipped",
        result_limit=50,
    )


def test_data_only_domain_analyses_is_deterministic_per_domain_summary() -> None:
    packs = [
        SimpleNamespace(
            pack_id="warehouse",
            domain="warehouse",
            results=[
                _status_qr("W-W01", 3, "succeeded", "warehouse"),
                _status_qr("W-W02", 0, "succeeded", "warehouse"),
                _status_qr("W-W03", 0, "skipped", "warehouse"),
            ],
        ),
        SimpleNamespace(
            pack_id="Query Performance",
            domain="query",
            results=[_status_qr("C-Q01", 50, "succeeded", "query")],
        ),
        SimpleNamespace(
            pack_id="warehouse_extra",
            domain="warehouse",
            results=[_status_qr("W-X01", 0, "failed", "warehouse")],
        ),
    ]
    result = SimpleNamespace(pack_results=packs, errors=[], trace_id="t", elapsed_ms=1.0)
    analyses = serialize_result(result)["domain_analyses"]

    assert [a["domain"] for a in analyses] == ["warehouse", "query"]
    wh, q = analyses
    assert wh["kind"] == "data_only_summary"
    assert wh["packs"] == ["warehouse", "warehouse_extra"]
    assert (wh["queries"], wh["succeeded"], wh["skipped"], wh["failed"]) == (4, 2, 1, 1)
    assert wh["rows_total"] == 3
    assert wh["nonempty_query_ids"] == ["W-W01"]
    assert wh["query_row_counts"] == {"W-W01": 3, "W-W02": 0, "W-W03": 0, "W-X01": 0}
    assert wh["data_paths"] == ["data.packs[0]", "data.packs[2]"]
    assert wh["raw_paths"] == ["raw/warehouse.json", "raw/warehouse_extra.json"]
    # raw path matches the file write_pack_file actually writes.
    assert q["raw_paths"] == ["raw/query_performance.json"]
    assert q["limit_reached_ids"] == ["C-Q01"]
    # No judgement on the data-only path: counts and pointers only.
    for a in analyses:
        assert not {"grade", "findings", "summary", "recommended_actions"} & a.keys()


def test_llm_domain_analyses_pass_through_unchanged() -> None:
    result = _result(_qr("A", 1, None))
    result.domain_analyses = [{"domain": "d", "grade": "B"}]
    assert serialize_result(result)["domain_analyses"] == [{"domain": "d", "grade": "B"}]


def test_no_packs_yields_empty_domain_analyses() -> None:
    result = SimpleNamespace(pack_results=[], errors=[], trace_id="t", elapsed_ms=1.0)
    assert serialize_result(result)["domain_analyses"] == []
