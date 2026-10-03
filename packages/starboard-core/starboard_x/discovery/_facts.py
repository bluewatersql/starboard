# Copyright (c) 2025 Databricks, Inc.
# Licensed under the Databricks Open Model License. See LICENSE for the full text.
"""Deterministic headline-facts builder for the discovery envelope (``data.facts``).

Pure and stdlib-only (``starboard_x`` dep-light tier). Computes the headline
numbers of a discovery run from the rows of the ``facts`` query pack
(``F-01`` … ``F-11``) so every host quotes the **same** figures instead of
re-deriving them from other packs' rows with differing windows. Hosts must
quote ``data.facts`` verbatim and never recompute these headlines.

Input is the list of *serialized* query dicts (``query_id`` / ``status`` /
``error`` / ``rows``) produced by :func:`starboard_x.discovery._serialize._serialize_query`.
A field whose source query is missing (pack not selected), skipped
(unavailable on the source) or failed is set to ``None`` and explained under
``unavailable[<field>]`` — the builder never raises on bad / partial input.

Windows (all FULL DAYS — today is always excluded):

- ``window``: trailing 30 full days, ``[today - 30, today - 1]``.
- ``months``: the last full calendar month vs the prior full month.
- ``step_change``: 7-day means either side of the step date; the exact
  ``before_start`` / ``before_end`` / ``after_start`` / ``after_end`` bounds and
  the ``method`` are carried so a verify query reproduces the same figures.
  The current run-rate (``current_7d_avg_daily_dbus``, last 7 full window days)
  and ``current_vs_pre_ratio`` vs ``pre_step_avg_daily_dbus`` are carried too.
  ``F-03`` returns 37 days (window + 7-day pre-window baseline) for this.
- ``recent_config_changes``: config changes in the last 7 days (today included —
  a config fact, not a usage total).

Fallbacks: when ``F-04`` / ``F-05`` are unavailable (e.g. a statement timeout),
``top_jobs`` is served from ``C-J01`` (else ``C-B04``) and ``top_pipelines`` from
``P-DLT06``. The source is recorded in ``fallbacks[<field>]`` (and ``sources``),
with the window difference in ``fallback_notes[<field>]``; ``pct`` is only set
when the fallback's window is the same 30 days (else ``None``).

Multi-workspace scopes are aggregated (totals summed; top-N lists merged and
re-ranked); list items carry ``workspace_id`` because entity ids are unique only
within a workspace. DBU and DSU are never summed. ``pct`` values are percentages
of ``total.dbus`` (product mix, top jobs, top pipelines, top warehouses).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

#: Fixed headline window length (days), independent of ``--lookback-days``.
WINDOW_DAYS = 30
#: Trailing / leading average length (days) for step-change detection.
STEP_SPAN_DAYS = 7
#: Size of the top-jobs / top-pipelines lists.
TOP_N = 10

#: Terminal result_states counted as a failed run (F-06 / vt-job-failures).
#: ``TIMEDOUT`` is the legacy spelling of ``TIMED_OUT``.
FAILED_STATES: tuple[str, ...] = ("FAILED", "ERROR", "TIMED_OUT", "TIMEDOUT")
_FAILURE_STATES_NOTE = (
    "one row per run (job_id, run_id) over all its timeline periods; final state = "
    "result_state of the run's latest period (a repaired run counts once, by its final "
    "outcome); a run is in the window iff its last period ended within window.start.."
    "window.end (full days, today excluded — a run finishing today is not counted yet); "
    "in-flight runs (no final state) excluded; failure = FAILED/ERROR/TIMED_OUT; "
    "cancelled reported separately. Same definition as the vt-job-failures template "
    "(failed_runs = its FAILED + ERROR + TIMED_OUT rows for the same window)"
)
_STEP_METHOD = (
    "largest lift of mean daily DBU over the 7 full days from date (after_start..after_end) "
    "vs the 7 full days before it (before_start..before_end); missing day = 0 DBU; "
    "ties -> earliest date"
)

# field -> source query id(s). A field with several sources needs all of them.
_FIELD_SOURCES: dict[str, tuple[str, ...]] = {
    "total": ("F-01",),
    "product_mix": ("F-01",),
    "months": ("F-02",),
    "top_jobs": ("F-04",),
    "top_pipelines": ("F-05",),
    "step_change": ("F-03",),
    "job_reliability": ("F-06",),
    "performance_mode": ("F-07",),
    "warehouses": ("F-08", "F-09"),
    "top_warehouses": ("F-11",),
    "recent_config_changes": ("F-10",),
}


#: Fallback sources for a field whose primary facts query is unavailable, tried
#: in order: ``(query_id, id_column, name_column | None, dbus_fn)``. ``dbus_fn``
#: maps a row to its DBU figure (None skips the row).
_FALLBACKS: dict[str, tuple[tuple[str, str, str | None, Any], ...]] = {
    "top_jobs": (
        ("C-J01", "job_id", "name", lambda r: _num(r.get("total_dbus"))),
        (
            "C-B04",
            "job_id",
            None,
            # 7-day mean before + 7-day mean after the step date -> 14-day DBU.
            lambda r: (
                None
                if _num(r.get("avg_daily_dbu_before")) is None
                and _num(r.get("avg_daily_dbu_after")) is None
                else 7.0 * (
                    (_num(r.get("avg_daily_dbu_before")) or 0.0)
                    + (_num(r.get("avg_daily_dbu_after")) or 0.0)
                )
            ),
        ),
    ),
    "top_pipelines": (
        ("P-DLT06", "pipeline_id", "pipeline_name", lambda r: _num(r.get("pipeline_total_dbus"))),
    ),
}


def _num(value: Any) -> float | None:
    """Coerce a SQL numeric (int / float / Decimal / numeric string) to float."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "t", "yes"}
    return bool(value)


def _day(value: Any) -> str | None:
    """Normalize a date / datetime / ISO string to ``YYYY-MM-DD``."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    if isinstance(value, str) and len(value) >= 10:
        return value[:10]
    return None


def _r2(x: float) -> float:
    return round(x, 2)


def _pct(part: float, whole: float | None, ndigits: int = 1) -> float | None:
    if not whole:
        return None
    return round(part / whole * 100.0, ndigits)


def _month_label(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _prev_month_start(d: date) -> date:
    first = d.replace(day=1)
    return (first - timedelta(days=1)).replace(day=1)


class _Sources:
    """Index of serialized query results with honest unavailability reasons."""

    def __init__(self, queries: list[dict[str, Any]]) -> None:
        self._by_id: dict[str, dict[str, Any]] = {}
        for q in queries:
            qid = q.get("query_id") if isinstance(q, dict) else None
            if isinstance(qid, str) and qid not in self._by_id:
                self._by_id[qid] = q

    @staticmethod
    def _status(q: dict[str, Any]) -> str:
        status = q.get("status")
        if isinstance(status, str):
            return status
        return "succeeded" if q.get("succeeded") else "failed"

    def lookback_days(self, query_id: str) -> int | None:
        q = self._by_id.get(query_id)
        value = q.get("lookback_days") if q else None
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    def rows(self, query_id: str) -> list[dict[str, Any]] | None:
        q = self._by_id.get(query_id)
        # A truncated result dropped rows past the serializer cap: a sum would be wrong.
        if q is None or self._status(q) != "succeeded" or q.get("truncated"):
            return None
        rows = q.get("rows") or []
        return [r for r in rows if isinstance(r, dict)]

    def reason(self, query_id: str) -> str:
        q = self._by_id.get(query_id)
        if q is None:
            return f"source query {query_id} did not run (facts pack not selected)"
        status = self._status(q)
        if status == "succeeded" and q.get("truncated"):
            return f"source query {query_id} truncated (rows over the serializer cap)"
        err = q.get("error")
        detail = f": {err}" if err else ""
        return f"source query {query_id} {status}{detail}"


def _window(src: _Sources, today: date) -> dict[str, Any]:
    start = (today - timedelta(days=WINDOW_DAYS)).isoformat()
    end = (today - timedelta(days=1)).isoformat()
    for row in src.rows("F-01") or []:
        s, e = _day(row.get("window_start")), _day(row.get("window_end"))
        if s and e:
            start, end = s, e
            break
    return {
        "start": start,
        "end": end,
        "days": WINDOW_DAYS,
        "label": f"trailing {WINDOW_DAYS} full days (excludes today)",
    }


def _total_and_mix(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    dbus = 0.0
    dsu: float | None = None
    by_product: dict[str, float] = {}
    for row in rows:
        qty = _num(row.get("usage_quantity")) or 0.0
        unit = str(row.get("usage_unit") or "").upper()
        if unit == "DBU":
            dbus += qty
            product = str(row.get("billing_origin_product") or "UNKNOWN")
            by_product[product] = by_product.get(product, 0.0) + qty
        elif unit == "DSU":
            dsu = (dsu or 0.0) + qty
    total = {"dbus": _r2(dbus), "dsu": _r2(dsu) if dsu is not None else None}
    mix = [
        {"product": p, "dbus": _r2(v), "pct": _pct(v, dbus) or 0.0}
        for p, v in sorted(by_product.items(), key=lambda kv: (-kv[1], kv[0]))
        if v != 0
    ]
    return total, mix


def _months(rows: list[dict[str, Any]], today: date) -> dict[str, Any]:
    last_start = _prev_month_start(today)
    last_label = _month_label(last_start)
    prior_label = _month_label(_prev_month_start(last_start))
    for row in rows:
        lf, pf = row.get("last_full_month"), row.get("prior_full_month")
        if isinstance(lf, str) and isinstance(pf, str):
            last_label, prior_label = lf[:7], pf[:7]
            break
    totals: dict[str, float] = {}
    for row in rows:
        month = row.get("usage_month")
        label = month[:7] if isinstance(month, str) else _day(month)
        if label:
            totals[label[:7]] = totals.get(label[:7], 0.0) + (_num(row.get("dbus")) or 0.0)
    last, prior = totals.get(last_label, 0.0), totals.get(prior_label, 0.0)
    growth = round((last - prior) / prior * 100.0, 1) if prior > 0 else None
    return {
        "last_full": {"month": last_label, "dbus": _r2(last)},
        "prior_full": {"month": prior_label, "dbus": _r2(prior)},
        "mom_growth_pct": growth,
    }


def _top(
    rows: list[dict[str, Any]], id_key: str, name_key: str, total_dbus: float | None
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        ent = row.get(id_key)
        if ent is None:
            continue
        key = (str(row.get("workspace_id") or ""), str(ent))
        item = merged.setdefault(
            key, {"name": None, "dbus": 0.0, "workspace_id": key[0] or None}
        )
        item["dbus"] += _num(row.get("dbus")) or 0.0
        if item["name"] is None and row.get(name_key) is not None:
            item["name"] = str(row.get(name_key))
    ranked = sorted(merged.items(), key=lambda kv: (-kv[1]["dbus"], kv[0]))[:TOP_N]
    return [
        {
            id_key: ent,
            "name": item["name"],
            "dbus": _r2(item["dbus"]),
            "pct": _pct(item["dbus"], total_dbus),
            "workspace_id": item["workspace_id"],
        }
        for (_, ent), item in ranked
    ]


def _fallback_top(
    src: _Sources, field: str, id_key: str, name_key: str, total_dbus: float | None
) -> tuple[str, list[dict[str, Any]], str] | None:
    """First available fallback for ``field``: ``(query_id, items, note)``."""
    for qid, src_id, src_name, dbus_fn in _FALLBACKS.get(field, ()):
        rows = src.rows(qid)
        if not rows:
            continue
        normalized = [
            {
                "workspace_id": r.get("workspace_id"),
                id_key: r.get(src_id),
                name_key: r.get(src_name) if src_name else None,
                "dbus": dbus,
            }
            for r in rows
            if (dbus := dbus_fn(r)) is not None
        ]
        if not normalized:
            continue
        if qid == "C-B04":
            same_window = False
            window = "the 14 days around the C-B04 step date (job lift rows only)"
        elif qid == "P-DLT06" and src.lookback_days(qid) == WINDOW_DAYS:
            # P-DLT06 runs on the facts full-day window (today excluded).
            same_window = True
            window = f"the same trailing {WINDOW_DAYS} full days (excludes today)"
        else:
            lookback = src.lookback_days(qid)
            same_window = lookback == WINDOW_DAYS
            window = (
                f"lookback {lookback} days incl. today so far"
                if lookback is not None
                else "the run lookback (incl. today so far)"
            )
        items = _top(normalized, id_key, name_key, total_dbus if same_window else None)
        note = (
            f"{src.reason(_FIELD_SOURCES[field][0])}; served from {qid} — {window}, "
            f"capped at that query's row limit"
            + ("" if same_window else "; pct omitted (window differs from facts.window)")
        )
        return qid, items, note
    return None


def detect_step_change(
    daily_dbus: dict[str, float], window_start: str, window_end: str
) -> dict[str, Any] | None:
    """Largest trailing-7-day-average lift day within the window.

    Algorithm (deterministic):

    1. ``daily_dbus`` maps ``YYYY-MM-DD`` → DBU (summed across workspaces); a
       day with no row counts as 0 DBU.
    2. Candidate days ``d`` run from ``window_start`` to ``window_end - 6`` so
       both averages are made of full days: ``before`` = mean DBU of
       ``d-7 … d-1`` (the 7 days before ``d``; for the first window days this
       reaches into the 7-day pre-window baseline that ``F-03`` returns) and
       ``after`` = mean DBU of ``d … d+6`` (``d`` and the 6 days after it).
    3. ``lift = after - before``. The candidate with the largest lift wins;
       ties break to the **earliest** date.
    4. Returns ``None`` when no candidate exists (window shorter than 7 days)
       or the largest lift is not positive (no upward step in the window).

    The result carries the exact averaging bounds (``before_start`` …
    ``before_end`` = ``d-7 … d-1``; ``after_start`` … ``after_end`` =
    ``d … d+6``, all inclusive) and a ``method`` string, plus the current
    run-rate: ``current_7d_avg_daily_dbus`` = mean DBU of the last 7 full
    window days (``current_7d_start`` … ``current_7d_end`` =
    ``window_end-6 … window_end``), ``pre_step_avg_daily_dbus`` (= the
    ``before`` mean) and ``current_vs_pre_ratio`` = current / pre-step
    (``None`` when the pre-step mean is 0).
    """
    try:
        start = date.fromisoformat(window_start)
        end = date.fromisoformat(window_end)
    except ValueError:
        return None

    def _at(d: date) -> float:
        return daily_dbus.get(d.isoformat(), 0.0)

    best: tuple[float, date, float, float] | None = None
    d = start
    last_candidate = end - timedelta(days=STEP_SPAN_DAYS - 1)
    while d <= last_candidate:
        before = sum(_at(d - timedelta(days=i)) for i in range(1, STEP_SPAN_DAYS + 1))
        after = sum(_at(d + timedelta(days=i)) for i in range(STEP_SPAN_DAYS))
        before_avg, after_avg = before / STEP_SPAN_DAYS, after / STEP_SPAN_DAYS
        lift = after_avg - before_avg
        # Strict ">" keeps the earliest date on ties (iteration is ascending).
        if best is None or lift > best[0]:
            best = (lift, d, before_avg, after_avg)
        d += timedelta(days=1)
    if best is None or best[0] <= 0:
        return None
    lift, day, before_avg, after_avg = best
    # Current run-rate: mean of the last 7 full window days (window_end-6 …
    # window_end), so the narrative can quote "now vs before the step" verbatim.
    current_avg = (
        sum(_at(end - timedelta(days=i)) for i in range(STEP_SPAN_DAYS)) / STEP_SPAN_DAYS
    )
    return {
        "date": day.isoformat(),
        "before_start": (day - timedelta(days=STEP_SPAN_DAYS)).isoformat(),
        "before_end": (day - timedelta(days=1)).isoformat(),
        "after_start": day.isoformat(),
        "after_end": (day + timedelta(days=STEP_SPAN_DAYS - 1)).isoformat(),
        "before_avg_daily_dbus": _r2(before_avg),
        "after_avg_daily_dbus": _r2(after_avg),
        "lift_daily_dbus": _r2(lift),
        "pre_step_avg_daily_dbus": _r2(before_avg),
        "current_7d_start": (end - timedelta(days=STEP_SPAN_DAYS - 1)).isoformat(),
        "current_7d_end": end.isoformat(),
        "current_7d_avg_daily_dbus": _r2(current_avg),
        "current_vs_pre_ratio": _r2(current_avg / before_avg) if before_avg > 0 else None,
        "method": _STEP_METHOD,
    }


def _step_change(rows: list[dict[str, Any]], window: dict[str, Any]) -> dict[str, Any] | None:
    daily: dict[str, float] = {}
    for row in rows:
        day = _day(row.get("usage_date"))
        if day:
            daily[day] = daily.get(day, 0.0) + (_num(row.get("dbus")) or 0.0)
    return detect_step_change(daily, window["start"], window["end"])


def _job_reliability(rows: list[dict[str, Any]], window: dict[str, Any]) -> dict[str, Any]:
    def _sum(key: str) -> int:
        return sum(int(_num(r.get(key)) or 0) for r in rows)

    def _sum_opt(key: str) -> int | None:
        # Per-state split is absent on rows from an older F-06 shape.
        if not any(r.get(key) is not None for r in rows):
            return None
        return _sum(key)

    runs = _sum("runs")
    failed = _sum("failed_runs")
    cancelled = _sum("cancelled_runs")
    start, end = window["start"], window["end"]
    for row in rows:
        s, e = _day(row.get("window_start")), _day(row.get("window_end"))
        if s and e:
            start, end = s, e
            break
    return {
        "runs": runs,
        "failed_runs": failed,
        "failed_by_state": {
            "FAILED": _sum_opt("failed_state_runs"),
            "ERROR": _sum_opt("error_runs"),
            "TIMED_OUT": _sum_opt("timed_out_runs"),
        },
        "cancelled_runs": cancelled,
        "failure_rate_pct": _pct(failed, runs, 2),
        "failure_or_cancel_rate_pct": _pct(failed + cancelled, runs, 2),
        "failed_states": list(FAILED_STATES),
        "window": {"start": start, "end": end, "basis": "run's last period_end_time"},
        "definition": _FAILURE_STATES_NOTE,
    }


def _performance_mode(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pool = 0.0
    optimized = 0.0
    for row in rows:
        qty = _num(row.get("dbus")) or 0.0
        pool += qty
        if str(row.get("performance_target") or "").upper() == "PERFORMANCE_OPTIMIZED":
            optimized += qty
    return {"pool_dbus": _r2(pool), "performance_optimized_pct": _pct(optimized, pool)}


def _warehouses(
    dbu_rows: list[dict[str, Any]], count_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    classic = serverless = 0.0
    for row in dbu_rows:
        qty = _num(row.get("dbus")) or 0.0
        if _truthy(row.get("is_serverless")):
            serverless += qty
        else:
            classic += qty
    count = sum(int(_num(r.get("warehouse_count")) or 0) for r in count_rows)
    return {"count": count, "classic_dbus": _r2(classic), "serverless_dbus": _r2(serverless)}


def _config_changes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _s(value: Any) -> str | None:
        if value is None:
            return None
        return value.isoformat() if isinstance(value, (date, datetime)) else str(value)

    out = [
        {
            "warehouse_id": _s(row.get("warehouse_id")),
            "change_time": _s(row.get("change_time")),
            "change": str(row.get("change") or ""),
            "workspace_id": _s(row.get("workspace_id")),
        }
        for row in rows
    ]
    out.sort(
        key=lambda c: (c["change_time"] or "", c["workspace_id"] or "", c["warehouse_id"] or ""),
        reverse=True,
    )
    return out


def build_facts(queries: list[dict[str, Any]], today: date | None = None) -> dict[str, Any]:
    """Build the ``data.facts`` block from serialized discovery query results.

    Args:
        queries: Serialized query dicts (any order, any packs); only the
            ``facts`` pack ids (``F-01`` … ``F-11``) are read.
        today: Reference date used only when the rows do not carry the
            server-side window / month labels (defaults to ``date.today()``).

    Returns:
        The facts dict per the convergence contract §1. Never raises on
        missing / skipped / failed sources — those fields are ``None`` with a
        reason in ``unavailable``.
    """
    today = today or date.today()
    src = _Sources(queries)
    facts: dict[str, Any] = {"window": _window(src, today)}
    sources: dict[str, str] = {}
    unavailable: dict[str, str] = {}

    def _rows_for(field: str) -> list[list[dict[str, Any]]] | None:
        got: list[list[dict[str, Any]]] = []
        missing: list[str] = []
        for qid in _FIELD_SOURCES[field]:
            rows = src.rows(qid)
            if rows is None:
                missing.append(src.reason(qid))
            else:
                got.append(rows)
        if missing:
            unavailable[field] = "; ".join(missing)
            return None
        sources[field] = ",".join(_FIELD_SOURCES[field])
        return got

    if (r := _rows_for("total")) is not None:
        sources["window"] = "F-01"
    total_and_mix = _total_and_mix(r[0]) if r is not None else None
    facts["total"] = total_and_mix[0] if total_and_mix else None
    if _rows_for("product_mix") is not None and total_and_mix:
        facts["product_mix"] = total_and_mix[1]
    else:
        facts["product_mix"] = None
    total_dbus = facts["total"]["dbus"] if facts["total"] else None

    r = _rows_for("months")
    facts["months"] = _months(r[0], today) if r is not None else None

    fallbacks: dict[str, str] = {}
    fallback_notes: dict[str, str] = {}

    def _top_with_fallback(field: str, id_key: str, name_key: str) -> list[dict[str, Any]] | None:
        r = _rows_for(field)
        if r is not None:
            return _top(r[0], id_key, name_key, total_dbus)
        fb = _fallback_top(src, field, id_key, name_key, total_dbus)
        if fb is None:
            return None
        qid, items, note = fb
        unavailable.pop(field, None)
        sources[field] = qid
        fallbacks[field] = qid
        fallback_notes[field] = note
        return items

    facts["top_jobs"] = _top_with_fallback("top_jobs", "job_id", "job_name")
    facts["top_pipelines"] = _top_with_fallback("top_pipelines", "pipeline_id", "pipeline_name")

    r = _rows_for("step_change")
    facts["step_change"] = _step_change(r[0], facts["window"]) if r is not None else None

    r = _rows_for("job_reliability")
    facts["job_reliability"] = (
        _job_reliability(r[0], facts["window"]) if r is not None else None
    )

    r = _rows_for("performance_mode")
    facts["performance_mode"] = _performance_mode(r[0]) if r is not None else None

    r = _rows_for("warehouses")
    facts["warehouses"] = _warehouses(r[0], r[1]) if r is not None else None

    r = _rows_for("top_warehouses")
    facts["top_warehouses"] = (
        _top(r[0], "warehouse_id", "warehouse_name", total_dbus) if r is not None else None
    )

    r = _rows_for("recent_config_changes")
    facts["recent_config_changes"] = _config_changes(r[0]) if r is not None else None

    facts["sources"] = sources
    facts["unavailable"] = unavailable
    facts["fallbacks"] = fallbacks
    facts["fallback_notes"] = fallback_notes
    return facts
