# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Deterministic ``data.facts`` builder (convergence contract §1, item B1)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from starboard_x.discovery._facts import build_facts, detect_step_change
from starboard_x.discovery._serialize import serialize_result, write_result_files

TODAY = date(2026, 10, 1)
W_START, W_END = "2026-09-01", "2026-09-30"
WS = "123"


def _q(query_id: str, rows: list[dict[str, Any]], status: str = "succeeded",
       error: str | None = None) -> dict[str, Any]:
    return {"query_id": query_id, "status": status, "error": error, "rows": rows,
            "truncated": False}


def _f01(rows: list[tuple[str, str, Any]]) -> dict[str, Any]:
    return _q("F-01", [
        {"workspace_id": WS, "billing_origin_product": p, "usage_unit": u,
         "window_start": W_START, "window_end": W_END, "usage_quantity": v}
        for p, u, v in rows
    ])


def _daily(values: dict[str, float]) -> dict[str, Any]:
    return _q("F-03", [{"workspace_id": WS, "usage_date": d, "dbus": v}
                       for d, v in values.items()])


def _series(start: str, end: str, value: float) -> dict[str, float]:
    d, last, out = date.fromisoformat(start), date.fromisoformat(end), {}
    while d <= last:
        out[d.isoformat()] = value
        d += timedelta(days=1)
    return out


def _full_set() -> list[dict[str, Any]]:
    daily = _series("2026-08-25", "2026-09-13", 100.0)
    daily.update(_series("2026-09-14", W_END, 300.0))
    return [
        _f01([("JOBS", "DBU", "600"), ("SQL", "DBU", Decimal("300")),
              ("DLT", "DBU", 100.0), ("LAKEBASE", "DSU", 40)]),
        _q("F-02", [
            {"workspace_id": WS, "usage_month": "2026-08", "last_full_month": "2026-09",
             "prior_full_month": "2026-08", "dbus": 800},
            {"workspace_id": WS, "usage_month": "2026-09", "last_full_month": "2026-09",
             "prior_full_month": "2026-08", "dbus": 1000},
        ]),
        _daily(daily),
        _q("F-04", [{"workspace_id": WS, "job_id": str(i), "job_name": f"j{i}",
                     "dbus": 100 - i, "job_rank": i} for i in range(1, 13)]),
        _q("F-05", [{"workspace_id": WS, "pipeline_id": "p1", "pipeline_name": None,
                     "dbus": 50, "pipeline_rank": 1}]),
        _q("F-06", [{"workspace_id": WS, "runs": 200, "failed_runs": 3,
                     "cancelled_runs": 1}]),
        _q("F-07", [
            {"workspace_id": WS, "billing_origin_product": "JOBS",
             "performance_target": "PERFORMANCE_OPTIMIZED", "dbus": 300},
            {"workspace_id": WS, "billing_origin_product": "DLT",
             "performance_target": "STANDARD", "dbus": 100},
        ]),
        _q("F-08", [{"workspace_id": WS, "is_serverless": "false", "dbus": 200},
                    {"workspace_id": WS, "is_serverless": True, "dbus": 100}]),
        _q("F-09", [{"workspace_id": WS, "warehouse_count": 4}]),
        _q("F-10", [{"workspace_id": WS, "warehouse_id": "w1",
                     "change_time": "2026-09-30T10:00:00", "change": "max_clusters 2 -> 4"}]),
        _q("F-11", [{"workspace_id": WS, "warehouse_id": "w2", "warehouse_name": "bi",
                     "dbus": 200, "warehouse_rank": 1},
                    {"workspace_id": WS, "warehouse_id": "w1", "warehouse_name": None,
                     "dbus": 100, "warehouse_rank": 2}]),
    ]


@pytest.mark.unit
class TestBuildFacts:
    def test_full_schema_and_values(self) -> None:
        f = build_facts(_full_set(), today=TODAY)
        assert f["window"] == {"start": W_START, "end": W_END, "days": 30,
                               "label": "trailing 30 full days (excludes today)"}
        assert f["total"] == {"dbus": 1000.0, "dsu": 40.0}
        assert [m["product"] for m in f["product_mix"]] == ["JOBS", "SQL", "DLT"]
        assert f["product_mix"][0] == {"product": "JOBS", "dbus": 600.0, "pct": 60.0}
        assert f["months"] == {"last_full": {"month": "2026-09", "dbus": 1000.0},
                               "prior_full": {"month": "2026-08", "dbus": 800.0},
                               "mom_growth_pct": 25.0}
        assert len(f["top_jobs"]) == 10
        assert f["top_jobs"][0]["job_id"] == "1"
        assert f["top_jobs"][0]["pct"] == 9.9
        assert f["top_pipelines"][0]["pipeline_id"] == "p1"
        assert f["step_change"]["date"] == "2026-09-14"
        assert f["step_change"]["lift_daily_dbus"] == 200.0
        sc = f["step_change"]
        assert (sc["before_start"], sc["before_end"]) == ("2026-09-07", "2026-09-13")
        assert (sc["after_start"], sc["after_end"]) == ("2026-09-14", "2026-09-20")
        assert "7 full days" in sc["method"]
        # Current run-rate: last 7 full window days vs the pre-step mean.
        assert (sc["current_7d_start"], sc["current_7d_end"]) == ("2026-09-24", W_END)
        assert sc["current_7d_avg_daily_dbus"] == 300.0
        assert sc["pre_step_avg_daily_dbus"] == sc["before_avg_daily_dbus"] == 100.0
        assert sc["current_vs_pre_ratio"] == 3.0
        assert f["top_warehouses"] == [
            {"warehouse_id": "w2", "name": "bi", "dbus": 200.0, "pct": 20.0,
             "workspace_id": WS},
            {"warehouse_id": "w1", "name": None, "dbus": 100.0, "pct": 10.0,
             "workspace_id": WS},
        ]
        assert f["sources"]["top_warehouses"] == "F-11"
        jr = f["job_reliability"]
        assert (jr["runs"], jr["failure_rate_pct"], jr["failure_or_cancel_rate_pct"]) == (
            200, 1.5, 2.0)
        assert f["performance_mode"] == {"pool_dbus": 400.0,
                                         "performance_optimized_pct": 75.0}
        assert f["warehouses"] == {"count": 4, "classic_dbus": 200.0,
                                   "serverless_dbus": 100.0}
        assert f["recent_config_changes"][0]["warehouse_id"] == "w1"
        assert f["unavailable"] == {}
        assert f["sources"]["total"] == "F-01"
        assert f["sources"]["warehouses"] == "F-08,F-09"

    def test_dbu_and_dsu_never_summed(self) -> None:
        f = build_facts([_f01([("JOBS", "DBU", 10), ("LAKEBASE", "DSU", 5)])], today=TODAY)
        assert f["total"] == {"dbus": 10.0, "dsu": 5.0}
        assert [m["product"] for m in f["product_mix"]] == ["JOBS"]

    def test_dsu_null_when_absent(self) -> None:
        f = build_facts([_f01([("JOBS", "DBU", 10)])], today=TODAY)
        assert f["total"]["dsu"] is None

    def test_window_excludes_today_when_rows_lack_bounds(self) -> None:
        f = build_facts([], today=TODAY)
        assert f["window"]["start"] == "2026-09-01"
        assert f["window"]["end"] == "2026-09-30"  # yesterday, never today

    def test_step_change_ignores_days_outside_window(self) -> None:
        # A huge "today" row (outside the full-day window) must not move the step.
        daily = _series("2026-08-25", W_END, 100.0)
        daily["2026-10-01"] = 1_000_000.0
        assert detect_step_change(daily, W_START, W_END) is None

    def test_step_change_tie_breaks_to_earliest(self) -> None:
        # Two identical isolated steps → identical lifts; earliest wins.
        daily = _series("2026-08-25", W_END, 0.0)
        for d in ("2026-09-05", "2026-09-20"):
            daily[d] = 70.0
        out1 = detect_step_change(daily, W_START, W_END)
        out2 = detect_step_change(dict(reversed(list(daily.items()))), W_START, W_END)
        assert out1 == out2
        assert out1 is not None and out1["date"] <= "2026-09-05"

    def test_step_change_bounds_reproduce_the_means(self) -> None:
        """C3: the carried bounds are exactly the 7-day spans averaged."""
        daily = _series("2026-08-25", W_END, 0.0)
        for i, d in enumerate(sorted(daily)):
            daily[d] = float(i * i)  # convex ramp: the step lands late in the window
        out = detect_step_change(daily, W_START, W_END)
        assert out is not None

        def _mean(a: str, b: str) -> float:
            return round(sum(v for d, v in daily.items() if a <= d <= b) / 7, 2)

        assert date.fromisoformat(out["before_end"]) + timedelta(days=1) == date.fromisoformat(
            out["after_start"]) == date.fromisoformat(out["date"])
        assert (date.fromisoformat(out["after_end"])
                - date.fromisoformat(out["after_start"])).days == 6
        assert (date.fromisoformat(out["before_end"])
                - date.fromisoformat(out["before_start"])).days == 6
        assert out["before_avg_daily_dbus"] == _mean(out["before_start"], out["before_end"])
        assert out["after_avg_daily_dbus"] == _mean(out["after_start"], out["after_end"])
        assert out["after_end"] <= W_END

    def test_step_change_current_run_rate_after_the_step(self) -> None:
        # Spend keeps climbing after the step: current run-rate > after mean.
        daily = _series("2026-08-25", "2026-09-09", 0.0)
        daily.update(_series("2026-09-10", "2026-09-23", 100.0))
        daily.update(_series("2026-09-24", W_END, 200.0))
        out = detect_step_change(daily, W_START, W_END)
        assert out is not None
        assert out["date"] == "2026-09-10"
        assert out["pre_step_avg_daily_dbus"] == 0.0
        assert out["current_7d_avg_daily_dbus"] == 200.0
        assert out["current_vs_pre_ratio"] is None  # pre-step mean is 0

    def test_step_change_none_when_flat_or_declining(self) -> None:
        assert detect_step_change(_series("2026-08-25", W_END, 5.0), W_START, W_END) is None

    @pytest.mark.parametrize("status", ["skipped", "failed"])
    def test_unavailable_source_nulls_field(self, status: str) -> None:
        qs = [q for q in _full_set() if q["query_id"] != "F-06"]
        qs.append(_q("F-06", [], status=status, error="table not mirrored"))
        f = build_facts(qs, today=TODAY)
        assert f["job_reliability"] is None
        assert "F-06" in f["unavailable"]["job_reliability"]
        assert status in f["unavailable"]["job_reliability"]
        assert "job_reliability" not in f["sources"]
        assert f["total"] is not None  # other fields unaffected

    def test_missing_source_nulls_every_field_never_raises(self) -> None:
        f = build_facts([], today=TODAY)
        for field in ("total", "product_mix", "months", "top_jobs", "top_pipelines",
                      "step_change", "job_reliability", "performance_mode",
                      "warehouses", "top_warehouses", "recent_config_changes"):
            assert f[field] is None
            assert field in f["unavailable"]
        assert f["sources"] == {}

    def test_multi_source_field_needs_all(self) -> None:
        qs = [q for q in _full_set() if q["query_id"] != "F-09"]
        f = build_facts(qs, today=TODAY)
        assert f["warehouses"] is None
        assert "F-09" in f["unavailable"]["warehouses"]

    def test_truncated_source_is_unavailable(self) -> None:
        q = _f01([("JOBS", "DBU", 10)])
        q["truncated"] = True
        f = build_facts([q], today=TODAY)
        assert f["total"] is None
        assert "truncated" in f["unavailable"]["total"]

    def test_zero_runs_has_null_rates(self) -> None:
        f = build_facts([_q("F-06", [])], today=TODAY)
        assert f["job_reliability"]["runs"] == 0
        assert f["job_reliability"]["failure_rate_pct"] is None

    def test_job_reliability_states_window_and_split(self) -> None:
        """Round-8: the failed-run definition is explicit and reconcilable with
        vt-job-failures (failed_runs = its FAILED + ERROR + TIMED_OUT rows)."""
        f = build_facts([_q("F-06", [{
            "workspace_id": WS, "window_start": "2026-09-01", "window_end": "2026-09-30",
            "runs": 14618, "failed_runs": 189, "failed_state_runs": 0, "error_runs": 184,
            "timed_out_runs": 5, "cancelled_runs": 110}])], today=TODAY)
        jr = f["job_reliability"]
        assert jr["failed_states"] == ["FAILED", "ERROR", "TIMED_OUT", "TIMEDOUT"]
        assert jr["window"]["start"] == "2026-09-01"
        assert jr["window"]["end"] == "2026-09-30"
        assert jr["failed_by_state"] == {"FAILED": 0, "ERROR": 184, "TIMED_OUT": 5}
        assert sum(jr["failed_by_state"].values()) == jr["failed_runs"]
        assert "latest period" in jr["definition"]
        assert "vt-job-failures" in jr["definition"]

    def test_job_reliability_window_defaults_to_facts_window(self) -> None:
        f = build_facts([_q("F-06", [{"workspace_id": WS, "runs": 10,
                                      "failed_runs": 1, "cancelled_runs": 0}])],
                        today=TODAY)
        jr = f["job_reliability"]
        assert (jr["window"]["start"], jr["window"]["end"]) == (
            f["window"]["start"], f["window"]["end"])
        # Older row shape without the per-state split -> None, not a fake 0.
        assert jr["failed_by_state"] == {"FAILED": None, "ERROR": None, "TIMED_OUT": None}

    def test_mom_growth_null_without_prior(self) -> None:
        f = build_facts([_q("F-02", [])], today=TODAY)
        assert f["months"]["prior_full"] == {"month": "2026-08", "dbus": 0.0}
        assert f["months"]["mom_growth_pct"] is None

    def test_deterministic(self) -> None:
        assert build_facts(_full_set(), today=TODAY) == build_facts(
            list(reversed(_full_set())), today=TODAY)


# --- serializer wiring ------------------------------------------------------ #
class _Df:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.columns = list(rows[0]) if rows else []

    def to_dicts(self) -> list[dict[str, Any]]:
        return list(self._rows)


def _engine_result() -> SimpleNamespace:
    qrs = [
        SimpleNamespace(query_id=q["query_id"], domain="billing", data=_Df(q["rows"]),
                        error=None, row_count=len(q["rows"]), succeeded=True,
                        skipped=False, status="succeeded", result_limit=None,
                        lookback_days=30)
        for q in _full_set()
    ]
    pack = SimpleNamespace(pack_id="facts", domain="billing", results=qrs)
    return SimpleNamespace(pack_results=[pack], errors=[], trace_id="t", elapsed_ms=1.0)


@pytest.mark.unit
def test_serialize_result_carries_facts() -> None:
    data = serialize_result(_engine_result())
    assert data["facts"]["total"]["dbus"] == 1000.0
    assert data["facts"]["step_change"]["date"] == "2026-09-14"


@pytest.mark.unit
def test_serialize_result_facts_present_without_facts_pack() -> None:
    empty = SimpleNamespace(pack_results=[], errors=[], trace_id="t", elapsed_ms=0.0)
    facts = serialize_result(empty)["facts"]
    assert facts["total"] is None
    assert "total" in facts["unavailable"]


@pytest.mark.unit
def test_write_result_files_manifest_carries_facts(tmp_path) -> None:
    out = write_result_files(_engine_result(), str(tmp_path))
    assert out["facts"]["warehouses"]["count"] == 4


# --- B2: fallbacks when F-04 / F-05 are unavailable ------------------------- #
def _without(*qids: str) -> list[dict[str, Any]]:
    return [q for q in _full_set() if q["query_id"] not in qids]


def _skipped(qid: str) -> dict[str, Any]:
    return _q(qid, [], status="skipped", error="unavailable: statement timed out")


@pytest.mark.unit
class TestFactsFallbacks:
    def test_primary_present_means_no_fallback(self) -> None:
        f = build_facts(_full_set(), today=TODAY)
        assert f["fallbacks"] == {}
        assert f["fallback_notes"] == {}

    def test_top_pipelines_from_p_dlt06(self) -> None:
        dlt06 = _q("P-DLT06", [
            {"workspace_id": WS, "pipeline_id": "p9", "pipeline_name": "silver",
             "pipeline_total_dbus": 80},
            {"workspace_id": WS, "pipeline_id": "p2", "pipeline_name": None,
             "pipeline_total_dbus": 20},
        ])
        dlt06["lookback_days"] = 30
        f = build_facts([*_without("F-05"), _skipped("F-05"), dlt06], today=TODAY)
        assert f["top_pipelines"][0] == {"pipeline_id": "p9", "name": "silver", "dbus": 80.0,
                                         "pct": 8.0, "workspace_id": WS}
        assert f["fallbacks"] == {"top_pipelines": "P-DLT06"}
        assert f["sources"]["top_pipelines"] == "P-DLT06"
        assert "top_pipelines" not in f["unavailable"]
        assert "F-05 skipped" in f["fallback_notes"]["top_pipelines"]
        assert "30 full days" in f["fallback_notes"]["top_pipelines"]

    def test_top_jobs_prefers_c_j01_and_omits_pct_on_other_window(self) -> None:
        cj01 = _q("C-J01", [{"workspace_id": WS, "job_id": "7", "name": "etl",
                             "total_dbus": 300}])
        cj01["lookback_days"] = 90
        cb04 = _q("C-B04", [{"workspace_id": WS, "job_id": "8", "avg_daily_dbu_before": 1,
                             "avg_daily_dbu_after": 2}])
        f = build_facts([*_without("F-04"), _skipped("F-04"), cb04, cj01], today=TODAY)
        assert f["fallbacks"] == {"top_jobs": "C-J01"}
        assert f["top_jobs"] == [{"job_id": "7", "name": "etl", "dbus": 300.0, "pct": None,
                                  "workspace_id": WS}]
        assert "pct omitted" in f["fallback_notes"]["top_jobs"]

    def test_top_jobs_falls_back_to_c_b04_when_c_j01_missing(self) -> None:
        cb04 = _q("C-B04", [{"workspace_id": WS, "job_id": "8", "avg_daily_dbu_before": 1,
                             "avg_daily_dbu_after": 2}])
        f = build_facts([*_without("F-04"), cb04], today=TODAY)
        assert f["fallbacks"] == {"top_jobs": "C-B04"}
        assert f["top_jobs"][0]["job_id"] == "8"
        assert f["top_jobs"][0]["dbus"] == 21.0  # 7 * (1 + 2): the 14 days around the step
        assert f["top_jobs"][0]["pct"] is None

    def test_no_fallback_source_keeps_field_unavailable(self) -> None:
        f = build_facts([*_without("F-04"), _skipped("F-04")], today=TODAY)
        assert f["top_jobs"] is None
        assert "F-04 skipped" in f["unavailable"]["top_jobs"]
        assert f["fallbacks"] == {}


@pytest.mark.unit
def test_write_result_files_writes_final_facts_json(tmp_path) -> None:
    import json

    out = write_result_files(_engine_result(), str(tmp_path))
    assert out["facts_path"] == "facts.json"
    on_disk = json.loads((tmp_path / "facts.json").read_text())
    assert on_disk["total"]["dbus"] == 1000.0
